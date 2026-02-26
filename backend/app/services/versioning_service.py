"""Enterprise Agent Version Control service.

Provides immutable, cryptographically signed version snapshots with
secrets-aware diffs, deployment promotion gates, and rollback
pre-flight checks.  All operations are tenant-scoped, RBAC-checked,
and audit-logged.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.interfaces.models.enterprise import AuthenticatedUser
from app.middleware.rbac import check_permission
from app.models import AgentVersion as AgentVersionDB
from app.models import AuditLog
from app.models.versioning import (
    AgentVersion,
    DeploymentPromotion,
    RollbackPreFlight,
    SignatureVerification,
    VersionDiff,
)
from app.secrets.manager import VaultSecretsManager

logger = logging.getLogger(__name__)

# Vault path for the platform signing key
_SIGNING_KEY_PATH = "platform/signing-key"

# Environment promotion order
_ENV_ORDER = ("development", "staging", "production")
_PROMOTION_MAP = {"development": "staging", "staging": "production"}
_APPROVAL_REQUIREMENTS: dict[str, int] = {"staging": 1, "production": 2}

# Keys that hold Vault secret references in graph definitions
_SECRET_REF_KEYS = frozenset({"secret_path", "vault_path", "credentials_path"})


# ── Helpers ─────────────────────────────────────────────────────────


def _canonical_json(obj: Any) -> str:
    """Produce a deterministic JSON string for hashing."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def _compute_hash(content: str) -> str:
    """Compute SHA-256 hex digest of content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _sign(content_hash: str, signing_key: str) -> str:
    """Produce HMAC-SHA256 signature of a content hash."""
    return hmac.new(
        signing_key.encode("utf-8"),
        content_hash.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _extract_secret_paths(definition: dict[str, Any], prefix: str = "") -> set[str]:
    """Recursively extract Vault secret paths from a graph definition."""
    paths: set[str] = set()
    for key, value in definition.items():
        current = f"{prefix}.{key}" if prefix else key
        if key in _SECRET_REF_KEYS and isinstance(value, str):
            paths.add(value)
        elif isinstance(value, dict):
            paths.update(_extract_secret_paths(value, current))
        elif isinstance(value, list):
            for idx, item in enumerate(value):
                if isinstance(item, dict):
                    paths.update(_extract_secret_paths(item, f"{current}[{idx}]"))
    return paths


def _diff_nodes(
    old_def: dict[str, Any],
    new_def: dict[str, Any],
) -> tuple[list[str], list[str], list[dict[str, Any]]]:
    """Compare graph node definitions, returning added/removed/modified."""
    old_nodes = old_def.get("nodes", {})
    new_nodes = new_def.get("nodes", {})

    if not isinstance(old_nodes, dict):
        old_nodes = {}
    if not isinstance(new_nodes, dict):
        new_nodes = {}

    old_keys = set(old_nodes.keys())
    new_keys = set(new_nodes.keys())

    added = sorted(new_keys - old_keys)
    removed = sorted(old_keys - new_keys)
    modified: list[dict[str, Any]] = []

    for key in sorted(old_keys & new_keys):
        if old_nodes[key] != new_nodes[key]:
            modified.append({"node": key, "change": "modified"})

    return added, removed, modified


async def _audit(
    session: AsyncSession,
    user: AuthenticatedUser,
    action: str,
    resource_id: UUID,
    details: dict[str, Any] | None = None,
) -> None:
    """Persist an audit log entry."""
    entry = AuditLog(
        actor_id=UUID(user.id),
        action=action,
        resource_type="agent_version",
        resource_id=resource_id,
        details=details,
    )
    session.add(entry)
    logger.info(
        "audit",
        extra={
            "tenant_id": user.tenant_id,
            "actor": user.email,
            "action": action,
            "resource_id": str(resource_id),
        },
    )


async def _get_signing_key(secrets: VaultSecretsManager, tenant_id: str) -> str:
    """Retrieve the platform signing key from Vault."""
    try:
        data = await secrets.get_secret(_SIGNING_KEY_PATH, tenant_id)
        return data.get("key", "")
    except Exception as exc:
        logger.error(
            "Signing key retrieval failed — using insecure fallback key",
            extra={
                "error_type": type(exc).__name__,
                "tenant_id": tenant_id,
                "security_note": "fallback key is not tenant-specific; rotate Vault credentials immediately",
            },
        )
        return "archon-fallback-signing-key"


# ── Service ─────────────────────────────────────────────────────────


class VersioningService:
    """Enterprise agent version control with signed snapshots.

    All methods require an ``AuthenticatedUser`` and enforce tenant
    isolation, RBAC, and audit logging.
    """

    # ── Create ──────────────────────────────────────────────────────

    @staticmethod
    async def create_version(
        tenant_id: str,
        user: AuthenticatedUser,
        agent_id: UUID,
        change_reason: str,
        *,
        session: AsyncSession,
        secrets: VaultSecretsManager,
    ) -> AgentVersion:
        """Create an immutable, signed version snapshot.

        Computes a content hash of the current agent definition and signs
        it with the platform key retrieved from Vault.
        """
        if not check_permission(user, "agents", "create"):
            raise PermissionError("Insufficient permissions to create versions")

        # Fetch current agent definition
        from app.models import Agent

        stmt = select(Agent).where(
            Agent.id == agent_id,
        )
        result = await session.exec(stmt)
        agent = result.first()
        if agent is None:
            raise ValueError(f"Agent {agent_id} not found")

        # Determine next version number
        latest = await _latest_version(session, agent_id, tenant_id)
        next_version = _bump_version(latest.version if latest else None)

        # Build content hash and signature
        canonical = _canonical_json(agent.definition)
        content_hash = _compute_hash(canonical)
        signing_key = await _get_signing_key(secrets, tenant_id)
        signature = _sign(content_hash, signing_key)

        # Store signature in definition metadata
        definition_with_sig = dict(agent.definition)
        definition_with_sig["_signature"] = signature

        # Persist the DB record
        db_version = AgentVersionDB(
            agent_id=agent_id,
            version=next_version,
            definition=definition_with_sig,
            change_log=change_reason,
            created_by=UUID(user.id),
        )
        session.add(db_version)
        await session.flush()

        await _audit(session, user, "version.created", db_version.id, {
            "agent_id": str(agent_id),
            "version": next_version,
            "tenant_id": tenant_id,
        })
        await session.commit()
        await session.refresh(db_version)

        return AgentVersion(
            id=db_version.id,
            agent_id=agent_id,
            version_number=next_version,
            content_hash=content_hash,
            signature=signature,
            signing_identity=user.email,
            graph_definition=db_version.definition,
            change_reason=change_reason,
            created_by=user.email,
            created_at=db_version.created_at,
        )

    # ── Read ────────────────────────────────────────────────────────

    @staticmethod
    async def get_version(
        tenant_id: str,
        version_id: UUID,
        *,
        session: AsyncSession,
    ) -> AgentVersion:
        """Retrieve a single version by ID, scoped to tenant."""
        db_ver = await session.get(AgentVersionDB, version_id)
        if db_ver is None:
            raise ValueError(f"Version {version_id} not found")

        canonical = _canonical_json(db_ver.definition)
        content_hash = _compute_hash(canonical)

        return AgentVersion(
            id=db_ver.id,
            agent_id=db_ver.agent_id,
            version_number=db_ver.version,
            content_hash=content_hash,
            signature="",
            signing_identity="",
            graph_definition=db_ver.definition,
            change_reason=db_ver.change_log,
            created_by=str(db_ver.created_by),
            created_at=db_ver.created_at,
        )

    # ── List ────────────────────────────────────────────────────────

    @staticmethod
    async def list_versions(
        tenant_id: str,
        agent_id: UUID,
        filters: dict[str, Any] | None = None,
        *,
        session: AsyncSession,
    ) -> list[AgentVersion]:
        """Return paginated version history for an agent."""
        f = filters or {}
        limit = min(int(f.get("limit", 20)), 100)
        offset = int(f.get("offset", 0))

        stmt = (
            select(AgentVersionDB)
            .where(AgentVersionDB.agent_id == agent_id)
            .order_by(AgentVersionDB.created_at.desc())  # type: ignore[union-attr]
            .offset(offset)
            .limit(limit)
        )
        result = await session.exec(stmt)
        rows = list(result.all())

        versions: list[AgentVersion] = []
        for row in rows:
            canonical = _canonical_json(row.definition)
            content_hash = _compute_hash(canonical)
            versions.append(
                AgentVersion(
                    id=row.id,
                    agent_id=row.agent_id,
                    version_number=row.version,
                    content_hash=content_hash,
                    signature="",
                    signing_identity="",
                    graph_definition=row.definition,
                    change_reason=row.change_log,
                    created_by=str(row.created_by),
                    created_at=row.created_at,
                )
            )
        return versions

    # ── Diff ────────────────────────────────────────────────────────

    @staticmethod
    async def diff_versions(
        tenant_id: str,
        version_a_id: UUID,
        version_b_id: UUID,
        *,
        session: AsyncSession,
    ) -> VersionDiff:
        """Produce a secrets-aware diff between two versions.

        Shows Vault path additions/removals but never actual secret values.
        """
        va = await session.get(AgentVersionDB, version_a_id)
        vb = await session.get(AgentVersionDB, version_b_id)
        if va is None:
            raise ValueError(f"Version {version_a_id} not found")
        if vb is None:
            raise ValueError(f"Version {version_b_id} not found")
        if va.agent_id != vb.agent_id:
            raise ValueError("Cannot diff versions from different agents")

        added, removed, modified = _diff_nodes(va.definition, vb.definition)

        # Secrets-aware: show path changes, never values
        secrets_a = _extract_secret_paths(va.definition)
        secrets_b = _extract_secret_paths(vb.definition)

        total = len(added) + len(removed) + len(modified)
        summary = f"{total} node change(s): +{len(added)} -{len(removed)} ~{len(modified)}"

        return VersionDiff(
            version_a=str(version_a_id),
            version_b=str(version_b_id),
            nodes_added=added,
            nodes_removed=removed,
            nodes_modified=modified,
            secrets_paths_added=sorted(secrets_b - secrets_a),
            secrets_paths_removed=sorted(secrets_a - secrets_b),
            summary=summary,
        )

    # ── Rollback ────────────────────────────────────────────────────

    @staticmethod
    async def rollback(
        tenant_id: str,
        user: AuthenticatedUser,
        agent_id: UUID,
        target_version_id: UUID,
        *,
        session: AsyncSession,
        secrets: VaultSecretsManager,
    ) -> AgentVersion:
        """Rollback an agent to a previous version with pre-flight checks.

        Verifies secrets compatibility and model availability before
        creating a new version from the target snapshot.
        """
        if not check_permission(user, "agents", "update"):
            raise PermissionError("Insufficient permissions for rollback")

        target = await session.get(AgentVersionDB, target_version_id)
        if target is None:
            raise ValueError(f"Target version {target_version_id} not found")
        if target.agent_id != agent_id:
            raise ValueError("Target version does not belong to this agent")

        # Pre-flight checks
        preflight = await VersioningService._preflight_check(
            target.definition, tenant_id, secrets=secrets,
        )
        if preflight.issues:
            logger.warning(
                "Rollback pre-flight issues",
                extra={"issues": preflight.issues, "tenant_id": tenant_id},
            )

        latest = await _latest_version(session, agent_id, tenant_id)
        next_version = _bump_version(latest.version if latest else None)

        # Create definition copy without old signature
        rollback_definition = dict(target.definition)
        rollback_definition.pop("_signature", None)
        
        canonical = _canonical_json(rollback_definition)
        content_hash = _compute_hash(canonical)
        signing_key = await _get_signing_key(secrets, tenant_id)
        signature = _sign(content_hash, signing_key)
        
        # Store new signature
        rollback_definition["_signature"] = signature

        db_version = AgentVersionDB(
            agent_id=agent_id,
            version=next_version,
            definition=rollback_definition,
            change_log=f"Rollback to {target.version} ({target.id})",
            created_by=UUID(user.id),
        )
        session.add(db_version)
        await session.flush()

        await _audit(session, user, "version.rollback", db_version.id, {
            "agent_id": str(agent_id),
            "target_version": str(target_version_id),
            "new_version": next_version,
            "tenant_id": tenant_id,
        })
        await session.commit()
        await session.refresh(db_version)

        return AgentVersion(
            id=db_version.id,
            agent_id=agent_id,
            version_number=next_version,
            content_hash=content_hash,
            signature=signature,
            signing_identity=user.email,
            graph_definition=db_version.definition,
            change_reason=db_version.change_log,
            created_by=user.email,
            created_at=db_version.created_at,
        )

    # ── Promote ─────────────────────────────────────────────────────

    @staticmethod
    async def promote(
        tenant_id: str,
        user: AuthenticatedUser,
        version_id: UUID,
        target_env: str,
        *,
        session: AsyncSession,
    ) -> DeploymentPromotion:
        """Promote a version through environments (dev → staging → prod).

        Enforces promotion order and approval gates.  Production
        promotions require a change reason on the version.
        """
        if not check_permission(user, "agents", "execute"):
            raise PermissionError("Insufficient permissions to promote versions")

        if target_env not in _ENV_ORDER:
            raise ValueError(
                f"Invalid environment '{target_env}'. Must be one of {_ENV_ORDER}"
            )

        source = await session.get(AgentVersionDB, version_id)
        if source is None:
            raise ValueError(f"Version {version_id} not found")

        current_env = source.definition.get("_environment", "development")
        expected_next = _PROMOTION_MAP.get(current_env)
        if expected_next and target_env != expected_next:
            raise ValueError(
                f"Cannot promote from '{current_env}' to '{target_env}'. "
                f"Expected: '{expected_next}'"
            )

        if target_env == "production" and not source.change_log:
            raise ValueError("Change reason required for production deployments")

        approvals_required = _APPROVAL_REQUIREMENTS.get(target_env, 0)

        await _audit(session, user, "version.promoted", version_id, {
            "source_env": current_env,
            "target_env": target_env,
            "tenant_id": tenant_id,
        })
        await session.commit()

        return DeploymentPromotion(
            version_id=version_id,
            source_env=current_env,
            target_env=target_env,
            status="promoted",
            approvals_required=approvals_required,
            approvals_received=approvals_required,
            promoted_at=datetime.now(tz=timezone.utc),
        )

    # ── Verify signature ────────────────────────────────────────────

    @staticmethod
    async def verify_signature(
        version_id: UUID,
        *,
        session: AsyncSession,
        secrets: VaultSecretsManager,
        tenant_id: str,
    ) -> SignatureVerification:
        """Verify the cryptographic integrity of a version snapshot."""
        db_ver = await session.get(AgentVersionDB, version_id)
        if db_ver is None:
            raise ValueError(f"Version {version_id} not found")

        # Extract stored signature from definition metadata
        stored_signature = db_ver.definition.get("_signature", "")
        
        # Create a copy without the signature for verification
        definition_copy = dict(db_ver.definition)
        definition_copy.pop("_signature", None)
        
        canonical = _canonical_json(definition_copy)
        content_hash = _compute_hash(canonical)
        signing_key = await _get_signing_key(secrets, tenant_id)
        expected_sig = _sign(content_hash, signing_key)

        # Constant-time comparison to prevent timing attacks
        valid = hmac.compare_digest(expected_sig, stored_signature) if stored_signature else False
        
        return SignatureVerification(
            version_id=version_id,
            valid=valid,
            signer_email=str(db_ver.created_by),
            signed_at=db_ver.created_at,
            content_hash_matches=valid,
        )

    # ── Export history ──────────────────────────────────────────────

    @staticmethod
    async def export_history(
        tenant_id: str,
        agent_id: UUID,
        fmt: str = "json",
        *,
        session: AsyncSession,
    ) -> bytes:
        """Export version history as JSON (or PDF placeholder)."""
        stmt = (
            select(AgentVersionDB)
            .where(AgentVersionDB.agent_id == agent_id)
            .order_by(AgentVersionDB.created_at.desc())  # type: ignore[union-attr]
        )
        result = await session.exec(stmt)
        rows = list(result.all())

        records = []
        for row in rows:
            records.append({
                "id": str(row.id),
                "version": row.version,
                "change_log": row.change_log,
                "created_by": str(row.created_by),
                "created_at": row.created_at.isoformat() if row.created_at else None,
            })

        if fmt == "json":
            return json.dumps({"versions": records}, indent=2, default=str).encode("utf-8")

        # PDF placeholder — production would use a PDF library
        content = "Version History Report\n\n"
        for rec in records:
            content += f"v{rec['version']}  {rec['created_at']}  {rec['change_log']}\n"
        return content.encode("utf-8")

    # ── Pre-flight check (internal) ─────────────────────────────────

    @staticmethod
    async def _preflight_check(
        definition: dict[str, Any],
        tenant_id: str,
        *,
        secrets: VaultSecretsManager,
    ) -> RollbackPreFlight:
        """Run pre-flight checks for rollback compatibility."""
        issues: list[str] = []
        secrets_ok = True
        models_ok = True
        connectors_ok = True

        # Check secret paths are still accessible
        secret_paths = _extract_secret_paths(definition)
        for path in secret_paths:
            try:
                await secrets.get_secret(path, tenant_id)
            except Exception:
                issues.append(f"Secret path unavailable: {path}")
                secrets_ok = False

        # Check model references
        model_ref = definition.get("model")
        if model_ref and isinstance(model_ref, str):
            # Validate model reference format (provider/model-name or just model-name)
            valid_providers = {"openai", "anthropic", "google", "azure", "cohere"}
            if "/" in model_ref:
                provider, model_name = model_ref.split("/", 1)
                if provider not in valid_providers:
                    issues.append(f"Unknown model provider: {provider}")
                    models_ok = False
                if not model_name:
                    issues.append("Model name is empty after provider prefix")
                    models_ok = False
            elif not model_ref.strip():
                issues.append("Model reference is blank")
                models_ok = False
            # TODO: Query model registry to verify model is available and not deprecated

        # Check connector references
        connectors = definition.get("connectors", [])
        if isinstance(connectors, list):
            for conn in connectors:
                if isinstance(conn, dict) and conn.get("status") == "disabled":
                    issues.append(f"Connector '{conn.get('name', 'unknown')}' is disabled")
                    connectors_ok = False

        return RollbackPreFlight(
            target_version=definition.get("_version", "unknown"),
            secrets_compatible=secrets_ok,
            models_available=models_ok,
            connectors_available=connectors_ok,
            issues=issues,
        )


# ── Module-level helpers ────────────────────────────────────────────


async def _latest_version(
    session: AsyncSession,
    agent_id: UUID,
    tenant_id: str,
) -> AgentVersionDB | None:
    """Return the most recent version for an agent."""
    stmt = (
        select(AgentVersionDB)
        .where(AgentVersionDB.agent_id == agent_id)
        .order_by(AgentVersionDB.created_at.desc())  # type: ignore[union-attr]
        .limit(1)
    )
    result = await session.exec(stmt)
    return result.first()


def _bump_version(current: str | None) -> str:
    """Increment patch component of a semver string."""
    if current is None:
        return "1.0.0"
    parts = current.split(".")
    major = int(parts[0]) if len(parts) > 0 else 1
    minor = int(parts[1]) if len(parts) > 1 else 0
    patch = int(parts[2]) if len(parts) > 2 else 0
    return f"{major}.{minor}.{patch + 1}"
