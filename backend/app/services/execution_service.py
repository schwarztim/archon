"""Enterprise-hardened service layer for Execution model.

Provides tenant isolation, RBAC, audit logging, secrets-based credential
injection, cost tracking, and execution lifecycle management.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.middleware.rbac import check_permission
from app.models import AuditLog, Execution, User, Agent
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
    """Append an immutable audit entry for an execution state change."""
    entry = AuditLog(
        actor_id=UUID(user.id),
        action=action,
        resource_type="execution",
        resource_id=resource_id,
        details=details,
    )
    session.add(entry)


def _tenant_execution_query(tenant_id: UUID) -> Any:
    """Return a base select for executions scoped to *tenant_id* via agent → owner → user."""
    return (
        select(Execution)
        .join(Agent, Execution.agent_id == Agent.id)
        .join(User, Agent.owner_id == User.id)
        .where(User.tenant_id == tenant_id)
    )


class ExecutionService:
    """Encapsulates all Execution persistence operations with enterprise hardening."""

    # ── Start Execution ──────────────────────────────────────────────

    @staticmethod
    async def start_execution(
        session: AsyncSession,
        agent_id: UUID,
        input_data: dict[str, Any],
        *,
        tenant_id: UUID,
        user: AuthenticatedUser,
    ) -> Execution:
        """Start a new LangGraph execution with tenant scoping and audit.

        Credentials are injected via SecretsManager — never passed in the
        request body.
        """
        check_permission(user, "executions", "execute")

        # Verify the agent belongs to this tenant
        agent_stmt = (
            select(Agent)
            .join(User, Agent.owner_id == User.id)
            .where(Agent.id == agent_id, User.tenant_id == tenant_id)
        )
        agent_result = await session.exec(agent_stmt)
        agent = agent_result.first()
        if agent is None:
            raise ValueError(f"Agent {agent_id} not found in tenant scope")

        # Inject credentials from SecretsManager (never from request body)
        from app.secrets.manager import get_secrets_manager
        secrets_mgr = await get_secrets_manager()
        creds_path = f"agents/{agent_id}/credentials"
        try:
            cred_data = await secrets_mgr.get_secret(creds_path, tenant_id=str(tenant_id))
        except Exception:
            cred_data = {}

        execution = Execution(
            id=uuid4(),
            agent_id=agent_id,
            status="running",
            input_data=input_data,
            started_at=_utcnow(),
            created_at=_utcnow(),
            updated_at=_utcnow(),
        )
        session.add(execution)
        await _audit(
            session, user, "execution.started", execution.id,
            {"agent_id": str(agent_id), "has_credentials": bool(cred_data)},
        )
        await session.commit()
        await session.refresh(execution)
        return execution

    # ── Get ───────────────────────────────────────────────────────────

    @staticmethod
    async def get_execution(
        session: AsyncSession,
        execution_id: UUID,
        *,
        tenant_id: UUID,
    ) -> Execution | None:
        """Return a single execution scoped to *tenant_id*."""
        stmt = _tenant_execution_query(tenant_id).where(Execution.id == execution_id)
        result = await session.exec(stmt)
        return result.first()

    # ── List ──────────────────────────────────────────────────────────

    @staticmethod
    async def list_executions(
        session: AsyncSession,
        *,
        tenant_id: UUID,
        agent_id: UUID | None = None,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[Execution], int]:
        """Return paginated, tenant-scoped executions with optional filters."""
        base = _tenant_execution_query(tenant_id)
        if agent_id is not None:
            base = base.where(Execution.agent_id == agent_id)
        if status is not None:
            base = base.where(Execution.status == status)

        count_result = await session.exec(base)
        total = len(count_result.all())

        stmt = base.offset(offset).limit(limit).order_by(col(Execution.created_at).desc())
        result = await session.exec(stmt)
        executions = list(result.all())
        return executions, total

    # ── Cancel ────────────────────────────────────────────────────────

    @staticmethod
    async def cancel_execution(
        session: AsyncSession,
        execution_id: UUID,
        *,
        tenant_id: UUID,
        user: AuthenticatedUser,
    ) -> Execution | None:
        """Cancel a running execution with RBAC and audit logging."""
        check_permission(user, "executions", "execute")
        execution = await ExecutionService.get_execution(
            session, execution_id, tenant_id=tenant_id,
        )
        if execution is None:
            return None
        if execution.status not in ("running", "queued"):
            return execution
        execution.status = "cancelled"
        execution.completed_at = _utcnow()
        execution.updated_at = _utcnow()
        session.add(execution)
        await _audit(
            session, user, "execution.cancelled", execution.id,
            {"agent_id": str(execution.agent_id)},
        )
        await session.commit()
        await session.refresh(execution)
        return execution

    # ── Execution Logs ────────────────────────────────────────────────

    @staticmethod
    async def get_execution_logs(
        session: AsyncSession,
        execution_id: UUID,
        *,
        tenant_id: UUID,
    ) -> list[dict[str, Any]]:
        """Return audit-log entries associated with an execution.

        Uses AuditLog entries where resource_type='execution' and
        resource_id matches.  Returns a list of log dicts.
        """
        # Verify tenant access first
        execution = await ExecutionService.get_execution(
            session, execution_id, tenant_id=tenant_id,
        )
        if execution is None:
            return []

        stmt = (
            select(AuditLog)
            .where(
                AuditLog.resource_type == "execution",
                AuditLog.resource_id == execution_id,
            )
            .order_by(col(AuditLog.created_at).asc())
        )
        result = await session.exec(stmt)
        logs = result.all()
        return [
            {
                "id": str(log.id),
                "action": log.action,
                "actor_id": str(log.actor_id),
                "details": log.details,
                "created_at": log.created_at.isoformat() if log.created_at else None,
            }
            for log in logs
        ]

    # ── Complete / Fail (internal helpers) ────────────────────────────

    @staticmethod
    async def complete_execution(
        session: AsyncSession,
        execution_id: UUID,
        output_data: dict[str, Any],
        *,
        tenant_id: UUID,
        user: AuthenticatedUser,
        cost_info: dict[str, Any] | None = None,
    ) -> Execution | None:
        """Mark an execution as completed with output and optional cost tracking."""
        execution = await ExecutionService.get_execution(
            session, execution_id, tenant_id=tenant_id,
        )
        if execution is None:
            return None
        execution.status = "completed"
        execution.output_data = output_data
        execution.completed_at = _utcnow()
        execution.updated_at = _utcnow()
        session.add(execution)
        audit_details: dict[str, Any] = {"agent_id": str(execution.agent_id)}
        if cost_info:
            audit_details["cost"] = cost_info
        await _audit(session, user, "execution.completed", execution.id, audit_details)
        await session.commit()
        await session.refresh(execution)
        return execution

    @staticmethod
    async def fail_execution(
        session: AsyncSession,
        execution_id: UUID,
        error_message: str,
        *,
        tenant_id: UUID,
        user: AuthenticatedUser,
        cost_info: dict[str, Any] | None = None,
    ) -> Execution | None:
        """Mark an execution as failed with error and optional cost tracking."""
        execution = await ExecutionService.get_execution(
            session, execution_id, tenant_id=tenant_id,
        )
        if execution is None:
            return None
        execution.status = "failed"
        execution.error = error_message
        execution.completed_at = _utcnow()
        execution.updated_at = _utcnow()
        session.add(execution)
        audit_details: dict[str, Any] = {"agent_id": str(execution.agent_id)}
        if cost_info:
            audit_details["cost"] = cost_info
        await _audit(session, user, "execution.failed", execution.id, audit_details)
        await session.commit()
        await session.refresh(execution)
        return execution


# ── Backward-compatible module-level functions ──────────────────────

async def create_execution(session: AsyncSession, execution: Execution) -> Execution:
    """Create an execution record with status='queued' (legacy compatibility)."""
    execution.status = "queued"
    session.add(execution)
    await session.commit()
    await session.refresh(execution)
    return execution


async def get_execution(session: AsyncSession, execution_id: UUID) -> Execution | None:
    """Return a single execution by ID, or None if not found (legacy compatibility)."""
    return await session.get(Execution, execution_id)


async def list_executions(
    session: AsyncSession,
    *,
    agent_id: UUID | None = None,
    status: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[Execution], int]:
    """Return paginated executions with optional agent_id and status filters (legacy compatibility)."""
    base = select(Execution)
    if agent_id is not None:
        base = base.where(Execution.agent_id == agent_id)
    if status is not None:
        base = base.where(Execution.status == status)
    count_result = await session.exec(base)
    total = len(count_result.all())
    stmt = base.offset(offset).limit(limit).order_by(col(Execution.created_at).desc())
    result = await session.exec(stmt)
    executions = list(result.all())
    return executions, total
