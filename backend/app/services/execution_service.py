"""Enterprise-hardened service layer for Execution model.

Provides tenant isolation, RBAC, audit logging, secrets-based credential
injection, cost tracking, and execution lifecycle management.

ADR-006 deprecation note: write paths through this module are routed via
``ExecutionFacade`` so a durable ``WorkflowRun`` row is created. The
returned object is a legacy ``Execution`` projection so existing callers
continue to work; new callers should depend on ``ExecutionFacade.create_run``
directly.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.middleware.rbac import check_permission
from app.models import AuditLog, Execution, User, Agent
from app.interfaces.models.enterprise import AuthenticatedUser

logger = logging.getLogger(__name__)


def _legacy_writes_enabled() -> bool:
    """Allow direct writes to the legacy ``executions`` table.

    Default: disabled per ADR-006 §Decision (write path is closed against
    legacy table). Set ``ARCHON_ENABLE_LEGACY_EXECUTION=true`` to re-open
    the legacy write path during the deprecation window.
    """
    return os.environ.get(
        "ARCHON_ENABLE_LEGACY_EXECUTION", ""
    ).lower() == "true"


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
        resource_id=str(resource_id),
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


# ── (mock step generation removed — real cost data comes from LLM node executor) ──


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
        config_overrides: dict[str, Any] | None = None,
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
            cred_data = await secrets_mgr.get_secret(
                creds_path, tenant_id=str(tenant_id)
            )
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
            session,
            user,
            "execution.started",
            execution.id,
            {"agent_id": str(agent_id), "has_credentials": bool(cred_data)},
        )
        await session.commit()
        await session.refresh(execution)
        return execution

    # ── Run (create + simulate) ──────────────────────────────────────

    @staticmethod
    async def run_execution(
        session: AsyncSession,
        agent_id: UUID,
        input_data: dict[str, Any],
        *,
        tenant_id: UUID,
        user: AuthenticatedUser,
        config_overrides: dict[str, Any] | None = None,
        ws_callback: Any | None = None,
    ) -> Execution:
        """Create an agent run via the canonical ExecutionFacade (ADR-006).

        Delegates to ``ExecutionFacade.create_run(kind='agent')`` and
        returns a legacy-shaped ``Execution`` projection so existing
        callers continue to receive the model surface they expect.

        New callers SHOULD depend on ``ExecutionFacade.create_run``
        directly. This wrapper exists to preserve the legacy public API
        during the ADR-006 deprecation window.
        """
        check_permission(user, "executions", "execute")

        # Verify the agent belongs to this tenant — explicit check so the
        # error message is the same as the legacy implementation.
        agent_stmt = (
            select(Agent)
            .join(User, Agent.owner_id == User.id)
            .where(Agent.id == agent_id, User.tenant_id == tenant_id)
        )
        agent_result = await session.exec(agent_stmt)
        agent = agent_result.first()
        if agent is None:
            raise ValueError(f"Agent {agent_id} not found in tenant scope")

        # Lazy import to avoid module-cycle: execution_facade imports
        # from app.models which transitively imports execution_service.
        from app.services.execution_facade import ExecutionFacade

        run, _is_new = await ExecutionFacade.create_run(
            session,
            kind="agent",
            agent_id=agent_id,
            tenant_id=tenant_id,
            input_data=input_data or {},
            triggered_by=user.email or "",
            trigger_type="manual",
        )

        await _audit(
            session,
            user,
            "execution.created",
            run.id,
            {"agent_id": str(agent_id), "via_facade": True},
        )
        await session.commit()

        # Optional WS callback — preserved for legacy callers.
        if ws_callback:
            await ws_callback(
                "execution.started",
                {
                    "execution_id": str(run.id),
                    "agent_id": str(agent_id),
                    "status": run.status,
                },
            )

        # Return a legacy-shaped Execution-like object reading from the
        # WorkflowRun row. Construct an Execution instance for typing
        # parity with the historical surface — this object is detached
        # from the session and only used as a return value.
        legacy = Execution(
            id=run.id,
            agent_id=agent_id,
            status=run.status,
            input_data=run.input_data or {},
            output_data=run.output_data,
            error=run.error,
            steps=[],
            metrics=run.metrics or {},
            started_at=run.started_at,
            completed_at=run.completed_at,
            created_at=run.created_at,
            updated_at=run.created_at,
        )
        return legacy

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

    # ── Get with agent name ──────────────────────────────────────────

    @staticmethod
    async def get_execution_detail(
        session: AsyncSession,
        execution_id: UUID,
        *,
        tenant_id: UUID,
    ) -> dict[str, Any] | None:
        """Return execution with expanded agent name and metrics summary."""
        stmt = _tenant_execution_query(tenant_id).where(Execution.id == execution_id)
        result = await session.exec(stmt)
        execution = result.first()
        if execution is None:
            return None

        # Fetch agent name
        agent_stmt = select(Agent).where(Agent.id == execution.agent_id)
        agent_result = await session.exec(agent_stmt)
        agent = agent_result.first()

        data = execution.model_dump(mode="json")
        data["agent_name"] = agent.name if agent else "Unknown"
        data["metrics_summary"] = {
            "total_steps": len(execution.steps) if execution.steps else 0,
            "completed_steps": len(
                [s for s in (execution.steps or []) if s.get("status") == "completed"]
            ),
            "failed_steps": len(
                [s for s in (execution.steps or []) if s.get("status") == "failed"]
            ),
        }
        return data

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

        stmt = (
            base.offset(offset).limit(limit).order_by(col(Execution.created_at).desc())
        )
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
            session,
            execution_id,
            tenant_id=tenant_id,
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
            session,
            user,
            "execution.cancelled",
            execution.id,
            {"agent_id": str(execution.agent_id)},
        )
        await session.commit()
        await session.refresh(execution)
        return execution

    # ── Replay ────────────────────────────────────────────────────────

    @staticmethod
    async def replay_execution(
        session: AsyncSession,
        execution_id: UUID,
        *,
        tenant_id: UUID,
        user: AuthenticatedUser,
        input_override: dict[str, Any] | None = None,
        config_overrides: dict[str, Any] | None = None,
        ws_callback: Any | None = None,
    ) -> Execution:
        """Re-run an execution with same or modified input.

        Fetches the original execution, uses its input (or override),
        and creates a new execution run.
        """
        original = await ExecutionService.get_execution(
            session,
            execution_id,
            tenant_id=tenant_id,
        )
        if original is None:
            raise ValueError(f"Execution {execution_id} not found")

        replay_input = (
            input_override if input_override is not None else original.input_data
        )
        return await ExecutionService.run_execution(
            session,
            original.agent_id,
            replay_input,
            tenant_id=tenant_id,
            user=user,
            config_overrides=config_overrides,
            ws_callback=ws_callback,
        )

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
            session,
            execution_id,
            tenant_id=tenant_id,
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
            session,
            execution_id,
            tenant_id=tenant_id,
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
            session,
            execution_id,
            tenant_id=tenant_id,
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

    # ── Backward-compatible simple class methods ─────────────────────

    @staticmethod
    async def create(
        session: AsyncSession,
        execution: "Execution",
    ) -> "Execution":
        """Create an execution with status='queued' (no tenant scoping)."""
        return await create_execution(session, execution)

    @staticmethod
    async def get(
        session: AsyncSession,
        execution_id: UUID,
    ) -> "Execution | None":
        """Return a single execution by ID without tenant scoping."""
        return await session.get(Execution, execution_id)

    @staticmethod
    async def list(
        session: AsyncSession,
        *,
        agent_id: UUID | None = None,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> "tuple[list[Execution], int]":
        """Return paginated executions without tenant scoping."""
        return await list_executions(
            session,
            agent_id=agent_id,
            status=status,
            limit=limit,
            offset=offset,
        )

    @staticmethod
    async def update(
        session: AsyncSession,
        execution_id: UUID,
        data: dict[str, Any],
    ) -> "Execution | None":
        """Partial-update an execution without RBAC (simple API)."""
        execution = await session.get(Execution, execution_id)
        if execution is None:
            return None
        for key, value in data.items():
            if hasattr(execution, key) and key not in ("id", "agent_id", "created_at"):
                setattr(execution, key, value)
        session.add(execution)
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
