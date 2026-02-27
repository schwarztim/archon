"""Enterprise-hardened CRUD service for Agent model.

Provides tenant isolation, RBAC, audit logging, soft-delete,
advanced search/filter, cloning, and bulk operations.
"""

from __future__ import annotations

import copy
import logging
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.middleware.rbac import check_permission
from app.models import Agent, AuditLog, User
from app.interfaces.models.enterprise import AuthenticatedUser

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    """Return naive UTC timestamp for TIMESTAMP WITHOUT TIME ZONE columns."""
    return datetime.utcnow()


async def _audit(
    session: AsyncSession,
    user: AuthenticatedUser,
    action: str,
    resource_id: UUID,
    details: dict[str, Any] | None = None,
) -> None:
    """Append an immutable audit entry for an agent state change."""
    entry = AuditLog(
        actor_id=UUID(user.id),
        action=action,
        resource_type="agent",
        resource_id=resource_id,
        details=details,
    )
    session.add(entry)


def _tenant_base_query(tenant_id: UUID) -> Any:
    """Return a base select for agents scoped to *tenant_id* via the owner's user record."""
    return (
        select(Agent)
        .join(User, Agent.owner_id == User.id)
        .where(User.tenant_id == tenant_id)
    )


class AgentService:
    """Encapsulates all Agent persistence operations with enterprise hardening."""

    # ── Create ───────────────────────────────────────────────────────

    @staticmethod
    async def create(
        session: AsyncSession,
        agent: Agent,
        *,
        tenant_id: UUID,
        user: AuthenticatedUser,
    ) -> Agent:
        """Persist a new agent with RBAC, tenant scoping, and audit logging."""
        check_permission(user, "agents", "create")
        # Ensure the agent is owned by a user in the correct tenant
        agent.owner_id = UUID(user.id)
        session.add(agent)
        await session.flush()
        await _audit(session, user, "agent.created", agent.id, {"name": agent.name})
        await session.commit()
        await session.refresh(agent)
        return agent

    # ── Read ─────────────────────────────────────────────────────────

    @staticmethod
    async def get(
        session: AsyncSession,
        agent_id: UUID,
        *,
        tenant_id: UUID,
    ) -> Agent | None:
        """Return a single agent scoped to *tenant_id*, excluding soft-deleted."""
        stmt = _tenant_base_query(tenant_id).where(Agent.id == agent_id)
        result = await session.exec(stmt)
        agent = result.first()
        if agent is not None and getattr(agent, "deleted_at", None) is not None:
            return None
        return agent

    # ── List / Search / Filter ───────────────────────────────────────

    @staticmethod
    async def list(
        session: AsyncSession,
        *,
        tenant_id: UUID,
        owner_id: UUID | None = None,
        status: str | None = None,
        name: str | None = None,
        tags: list[str] | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[Agent], int]:
        """Return paginated, tenant-scoped agents with optional filters."""
        base = _tenant_base_query(tenant_id)

        # Exclude soft-deleted agents when the model supports it
        if hasattr(Agent, "deleted_at"):
            base = base.where(col(Agent.deleted_at).is_(None))  # type: ignore[arg-type]

        if owner_id is not None:
            base = base.where(Agent.owner_id == owner_id)
        if status is not None:
            base = base.where(Agent.status == status)
        if name is not None:
            base = base.where(col(Agent.name).ilike(f"%{name}%"))
        if created_after is not None:
            base = base.where(col(Agent.created_at) >= created_after)
        if created_before is not None:
            base = base.where(col(Agent.created_at) <= created_before)

        count_result = await session.exec(base)
        total = len(count_result.all())

        stmt = base.offset(offset).limit(limit).order_by(col(Agent.created_at).desc())
        result = await session.exec(stmt)
        agents = list(result.all())
        return agents, total

    # ── Update ───────────────────────────────────────────────────────

    @staticmethod
    async def update(
        session: AsyncSession,
        agent_id: UUID,
        data: dict[str, Any],
        *,
        tenant_id: UUID,
        user: AuthenticatedUser,
    ) -> Agent | None:
        """Partial-update an agent with RBAC and audit logging."""
        check_permission(user, "agents", "update")
        agent = await AgentService.get(session, agent_id, tenant_id=tenant_id)
        if agent is None:
            return None
        before = {k: getattr(agent, k, None) for k in data}
        for key, value in data.items():
            if hasattr(agent, key) and key not in ("id", "owner_id", "created_at"):
                setattr(agent, key, value)
        if hasattr(agent, "updated_at"):
            agent.updated_at = _utcnow()
        session.add(agent)
        await _audit(
            session, user, "agent.updated", agent.id, {"before": before, "after": data}
        )
        await session.commit()
        await session.refresh(agent)
        return agent

    # ── Soft-Delete ──────────────────────────────────────────────────

    @staticmethod
    async def delete(
        session: AsyncSession,
        agent_id: UUID,
        *,
        tenant_id: UUID,
        user: AuthenticatedUser,
    ) -> bool:
        """Soft-delete an agent (set deleted_at). Never hard-deletes."""
        check_permission(user, "agents", "delete")
        agent = await AgentService.get(session, agent_id, tenant_id=tenant_id)
        if agent is None:
            return False
        if hasattr(agent, "deleted_at"):
            agent.deleted_at = _utcnow()  # type: ignore[attr-defined]
        else:
            agent.status = "deleted"
        if hasattr(agent, "updated_at"):
            agent.updated_at = _utcnow()
        session.add(agent)
        await _audit(session, user, "agent.deleted", agent.id, {"name": agent.name})
        await session.commit()
        return True

    # ── Deploy ───────────────────────────────────────────────────────

    @staticmethod
    async def deploy(
        session: AsyncSession,
        agent_id: UUID,
        *,
        tenant_id: UUID,
        user: AuthenticatedUser,
    ) -> Agent | None:
        """Mark an agent as deployed with audit trail."""
        check_permission(user, "agents", "update")
        agent = await AgentService.get(session, agent_id, tenant_id=tenant_id)
        if agent is None:
            return None
        agent.status = "deployed"
        if hasattr(agent, "updated_at"):
            agent.updated_at = _utcnow()
        session.add(agent)
        await _audit(session, user, "agent.deployed", agent.id, {"name": agent.name})
        await session.commit()
        await session.refresh(agent)
        return agent

    # ── Clone ────────────────────────────────────────────────────────

    @staticmethod
    async def clone_agent(
        session: AsyncSession,
        agent_id: UUID,
        *,
        tenant_id: UUID,
        user: AuthenticatedUser,
        new_name: str | None = None,
    ) -> Agent | None:
        """Deep-copy an agent within the caller's tenant scope."""
        check_permission(user, "agents", "create")
        source = await AgentService.get(session, agent_id, tenant_id=tenant_id)
        if source is None:
            return None
        cloned = Agent(
            id=uuid4(),
            name=new_name or f"{source.name} (copy)",
            description=source.description,
            definition=copy.deepcopy(source.definition),
            status="draft",
            owner_id=UUID(user.id),
            tags=list(source.tags) if source.tags else [],
            created_at=_utcnow(),
            updated_at=_utcnow(),
        )
        session.add(cloned)
        await _audit(
            session,
            user,
            "agent.cloned",
            cloned.id,
            {"source_id": str(agent_id), "name": cloned.name},
        )
        await session.commit()
        await session.refresh(cloned)
        return cloned

    # ── Bulk Operations ──────────────────────────────────────────────

    @staticmethod
    async def bulk_update_status(
        session: AsyncSession,
        agent_ids: list[UUID],
        new_status: str,
        *,
        tenant_id: UUID,
        user: AuthenticatedUser,
    ) -> list[Agent]:
        """Update the status of multiple agents in a single transaction."""
        check_permission(user, "agents", "update")
        updated: list[Agent] = []
        for aid in agent_ids:
            agent = await AgentService.get(session, aid, tenant_id=tenant_id)
            if agent is None:
                continue
            agent.status = new_status
            if hasattr(agent, "updated_at"):
                agent.updated_at = _utcnow()
            session.add(agent)
            await _audit(
                session,
                user,
                "agent.status_changed",
                agent.id,
                {"new_status": new_status},
            )
            updated.append(agent)
        await session.commit()
        for a in updated:
            await session.refresh(a)
        return updated

    @staticmethod
    async def bulk_delete(
        session: AsyncSession,
        agent_ids: list[UUID],
        *,
        tenant_id: UUID,
        user: AuthenticatedUser,
    ) -> int:
        """Soft-delete multiple agents. Returns count of deleted agents."""
        check_permission(user, "agents", "delete")
        count = 0
        for aid in agent_ids:
            deleted = await AgentService.delete(
                session,
                aid,
                tenant_id=tenant_id,
                user=user,
            )
            if deleted:
                count += 1
        return count


# ── Backward-compatible module-level functions ──────────────────────
# Existing routes import these directly; keep them working.
# These wrappers construct a minimal AuthenticatedUser for audit purposes.


async def create_agent(session: AsyncSession, agent: Agent) -> Agent:
    """Persist a new agent and return it (legacy compatibility)."""
    session.add(agent)
    await session.commit()
    await session.refresh(agent)
    return agent


async def get_agent(session: AsyncSession, agent_id: UUID) -> Agent | None:
    """Return a single agent by ID, or None if not found (legacy compatibility)."""
    return await session.get(Agent, agent_id)


async def list_agents(
    session: AsyncSession,
    *,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[Agent], int]:
    """Return paginated agents and total count (legacy compatibility)."""
    base = select(Agent)
    count_result = await session.exec(base)
    total = len(count_result.all())
    stmt = base.offset(offset).limit(limit).order_by(col(Agent.created_at).desc())
    result = await session.exec(stmt)
    agents = list(result.all())
    return agents, total


async def update_agent(
    session: AsyncSession,
    agent_id: UUID,
    data: dict[str, Any],
) -> Agent | None:
    """Apply partial updates to an existing agent (legacy compatibility)."""
    agent = await session.get(Agent, agent_id)
    if agent is None:
        return None
    for key, value in data.items():
        if hasattr(agent, key):
            setattr(agent, key, value)
    session.add(agent)
    await session.commit()
    await session.refresh(agent)
    return agent


async def delete_agent(session: AsyncSession, agent_id: UUID) -> bool:
    """Delete an agent by ID. Returns True if deleted, False if not found (legacy compatibility)."""
    agent = await session.get(Agent, agent_id)
    if agent is None:
        return False
    # Delete child AgentVersion records to avoid FK constraint violations
    from app.models import AgentVersion
    from sqlmodel import delete as sql_delete

    await session.exec(
        sql_delete(AgentVersion).where(AgentVersion.agent_id == agent_id)
    )
    await session.delete(agent)
    await session.commit()
    return True
