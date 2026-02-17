"""Service for AgentVersion management (immutable snapshots).

Includes version comparison (diff), rollback, and deployment promotion.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models import AgentVersion


# ── Diff helpers ────────────────────────────────────────────────────


def _diff_dicts(
    old: dict[str, Any],
    new: dict[str, Any],
    path: str = "",
) -> list[dict[str, Any]]:
    """Recursively diff two dicts, returning a list of change records.

    Each record has: ``path``, ``type`` (added | removed | changed),
    ``old_value`` (if applicable), ``new_value`` (if applicable).
    """
    changes: list[dict[str, Any]] = []
    all_keys = sorted(set(old) | set(new))

    for key in all_keys:
        current_path = f"{path}.{key}" if path else key
        in_old = key in old
        in_new = key in new

        if in_old and not in_new:
            changes.append({
                "path": current_path,
                "type": "removed",
                "old_value": old[key],
            })
        elif in_new and not in_old:
            changes.append({
                "path": current_path,
                "type": "added",
                "new_value": new[key],
            })
        elif old[key] != new[key]:
            # Recurse into nested dicts
            if isinstance(old[key], dict) and isinstance(new[key], dict):
                changes.extend(_diff_dicts(old[key], new[key], current_path))
            else:
                changes.append({
                    "path": current_path,
                    "type": "changed",
                    "old_value": old[key],
                    "new_value": new[key],
                })

    return changes


# ── Version string helpers ──────────────────────────────────────────


def _parse_semver(version: str) -> tuple[int, int, int]:
    """Parse a semver string into (major, minor, patch)."""
    parts = version.split(".")
    major = int(parts[0]) if len(parts) > 0 else 0
    minor = int(parts[1]) if len(parts) > 1 else 0
    patch = int(parts[2]) if len(parts) > 2 else 0
    return major, minor, patch


def _bump_patch(version: str) -> str:
    """Increment the patch component of a semver string."""
    major, minor, patch = _parse_semver(version)
    return f"{major}.{minor}.{patch + 1}"


class AgentVersionService:
    """Manages immutable agent version snapshots.

    Versions are append-only — no update or delete is allowed.
    """

    @staticmethod
    async def create(session: AsyncSession, version: AgentVersion) -> AgentVersion:
        """Persist a new agent version snapshot and return it."""
        session.add(version)
        await session.commit()
        await session.refresh(version)
        return version

    @staticmethod
    async def get(session: AsyncSession, version_id: UUID) -> AgentVersion | None:
        """Return a single agent version by ID, or None if not found."""
        return await session.get(AgentVersion, version_id)

    @staticmethod
    async def list_by_agent(
        session: AsyncSession,
        *,
        agent_id: UUID,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[AgentVersion], int]:
        """Return paginated versions for a given agent, newest first."""
        base = select(AgentVersion).where(AgentVersion.agent_id == agent_id)

        count_result = await session.exec(base)
        total = len(count_result.all())

        stmt = base.offset(offset).limit(limit).order_by(AgentVersion.created_at.desc())  # type: ignore[union-attr]
        result = await session.exec(stmt)
        versions = list(result.all())
        return versions, total

    @staticmethod
    async def get_latest(
        session: AsyncSession,
        agent_id: UUID,
    ) -> AgentVersion | None:
        """Return the most recent version for an agent, or None."""
        stmt = (
            select(AgentVersion)
            .where(AgentVersion.agent_id == agent_id)
            .order_by(AgentVersion.created_at.desc())  # type: ignore[union-attr]
            .limit(1)
        )
        result = await session.exec(stmt)
        return result.first()

    # ── Comparison ──────────────────────────────────────────────────

    @staticmethod
    async def compare(
        session: AsyncSession,
        version_id_1: UUID,
        version_id_2: UUID,
    ) -> dict[str, Any]:
        """Return a JSON diff between two agent versions.

        Both versions must exist and belong to the same agent.
        Returns ``{"changes": [...], "v1": ..., "v2": ..., "summary": ...}``.

        Raises ``ValueError`` when a version is not found or agents differ.
        """
        v1 = await session.get(AgentVersion, version_id_1)
        if v1 is None:
            raise ValueError(f"Version {version_id_1} not found")

        v2 = await session.get(AgentVersion, version_id_2)
        if v2 is None:
            raise ValueError(f"Version {version_id_2} not found")

        if v1.agent_id != v2.agent_id:
            raise ValueError("Cannot compare versions from different agents")

        changes = _diff_dicts(v1.definition, v2.definition)

        added = sum(1 for c in changes if c["type"] == "added")
        removed = sum(1 for c in changes if c["type"] == "removed")
        changed = sum(1 for c in changes if c["type"] == "changed")

        return {
            "v1": {"id": str(v1.id), "version": v1.version},
            "v2": {"id": str(v2.id), "version": v2.version},
            "agent_id": str(v1.agent_id),
            "changes": changes,
            "summary": {
                "total_changes": len(changes),
                "added": added,
                "removed": removed,
                "changed": changed,
            },
        }

    # ── Rollback ────────────────────────────────────────────────────

    @staticmethod
    async def rollback(
        session: AsyncSession,
        agent_id: UUID,
        target_version_id: UUID,
        created_by: UUID,
    ) -> AgentVersion:
        """Rollback an agent to a previous version.

        Creates a **new** version with the definition from the target
        version (non-destructive).  The new version string is the latest
        version's patch incremented, and the change_log records it as a
        rollback.

        Raises ``ValueError`` when the target version is not found or
        does not belong to the specified agent.
        """
        target = await session.get(AgentVersion, target_version_id)
        if target is None:
            raise ValueError(f"Target version {target_version_id} not found")
        if target.agent_id != agent_id:
            raise ValueError("Target version does not belong to this agent")

        # Determine new version string
        latest = await AgentVersionService.get_latest(session, agent_id)
        new_version_str = _bump_patch(latest.version) if latest else "1.0.0"

        new_version = AgentVersion(
            agent_id=agent_id,
            version=new_version_str,
            definition=dict(target.definition),  # deep-copy the snapshot
            change_log=f"Rollback to version {target.version} ({target.id})",
            created_by=created_by,
        )
        session.add(new_version)
        await session.commit()
        await session.refresh(new_version)
        return new_version

    # ── Promotion ───────────────────────────────────────────────────

    VALID_ENVIRONMENTS = ("development", "staging", "production")
    PROMOTION_ORDER = {
        "development": "staging",
        "staging": "production",
    }

    @staticmethod
    async def promote(
        session: AsyncSession,
        version_id: UUID,
        target_environment: str,
        created_by: UUID,
    ) -> AgentVersion:
        """Promote a version to a target deployment environment.

        Creates a new version whose definition includes an
        ``_environment`` field set to the target environment.

        Raises ``ValueError`` for invalid environment or if the version
        is not found.
        """
        if target_environment not in AgentVersionService.VALID_ENVIRONMENTS:
            raise ValueError(
                f"Invalid environment '{target_environment}'. "
                f"Must be one of {AgentVersionService.VALID_ENVIRONMENTS}"
            )

        source = await session.get(AgentVersion, version_id)
        if source is None:
            raise ValueError(f"Version {version_id} not found")

        current_env = source.definition.get("_environment", "development")
        expected_next = AgentVersionService.PROMOTION_ORDER.get(current_env)
        if expected_next and target_environment != expected_next:
            raise ValueError(
                f"Cannot promote from '{current_env}' to '{target_environment}'. "
                f"Expected next environment: '{expected_next}'"
            )

        latest = await AgentVersionService.get_latest(session, source.agent_id)
        new_version_str = _bump_patch(latest.version) if latest else "1.0.0"

        promoted_def = dict(source.definition)
        promoted_def["_environment"] = target_environment

        new_version = AgentVersion(
            agent_id=source.agent_id,
            version=new_version_str,
            definition=promoted_def,
            change_log=f"Promoted to {target_environment} from version {source.version}",
            created_by=created_by,
        )
        session.add(new_version)
        await session.commit()
        await session.refresh(new_version)
        return new_version
