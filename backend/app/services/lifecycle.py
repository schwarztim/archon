"""Lifecycle management service for Archon agents."""

from __future__ import annotations

from datetime import datetime

from app.utils.time import utcnow as _utcnow
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.lifecycle import DeploymentRecord, HealthCheck, LifecycleEvent


class LifecycleManager:
    """Manages agent deployments, health monitoring, scaling, and retirement."""

    # ── Deploy ──────────────────────────────────────────────────────

    @staticmethod
    async def deploy(
        session: AsyncSession,
        *,
        agent_id: UUID,
        version_id: UUID,
        environment: str = "staging",
        strategy: str = "rolling",
        replicas: int = 1,
        min_replicas: int = 1,
        max_replicas: int = 10,
        error_rate_threshold: float = 0.05,
        config: dict[str, Any] | None = None,
        deployed_by: UUID | None = None,
    ) -> DeploymentRecord:
        """Create and activate a new deployment for an agent version.

        If a previous active deployment exists for the same agent+environment,
        it is linked via ``previous_deployment_id`` for rollback purposes.
        """
        # Find current active deployment for rollback chain
        prev = await LifecycleManager._active_deployment(
            session,
            agent_id=agent_id,
            environment=environment,
        )

        initial_traffic = 100
        if strategy == "canary":
            initial_traffic = 5
        elif strategy == "blue_green":
            initial_traffic = 0

        record = DeploymentRecord(
            agent_id=agent_id,
            version_id=version_id,
            environment=environment,
            strategy=strategy,
            status="deploying",
            traffic_percentage=initial_traffic,
            error_rate_threshold=error_rate_threshold,
            replicas=replicas,
            min_replicas=min_replicas,
            max_replicas=max_replicas,
            previous_deployment_id=prev.id if prev else None,
            config=config or {},
            deployed_by=deployed_by,
            deployed_at=_utcnow(),
        )
        session.add(record)

        # Mark deploying → active
        record.status = "active"

        await session.commit()
        await session.refresh(record)

        # Record lifecycle event
        await LifecycleManager._record_event(
            session,
            deployment_id=record.id,
            agent_id=agent_id,
            event_type="deployed",
            from_state="pending",
            to_state="active",
            message=f"Deployed via {strategy} strategy to {environment}",
            actor_id=deployed_by,
        )

        return record

    # ── Promote canary traffic ──────────────────────────────────────

    @staticmethod
    async def promote_canary(
        session: AsyncSession,
        deployment_id: UUID,
        *,
        traffic_percentage: int,
    ) -> DeploymentRecord | None:
        """Increase canary traffic percentage for a deployment."""
        record = await session.get(DeploymentRecord, deployment_id)
        if record is None:
            return None

        old_pct = record.traffic_percentage
        record.traffic_percentage = min(traffic_percentage, 100)
        record.updated_at = _utcnow()
        session.add(record)
        await session.commit()
        await session.refresh(record)

        await LifecycleManager._record_event(
            session,
            deployment_id=record.id,
            agent_id=record.agent_id,
            event_type="scaled",
            from_state=f"traffic:{old_pct}%",
            to_state=f"traffic:{record.traffic_percentage}%",
            message=f"Canary promoted from {old_pct}% to {record.traffic_percentage}%",
        )

        return record

    # ── Scale ───────────────────────────────────────────────────────

    @staticmethod
    async def scale(
        session: AsyncSession,
        deployment_id: UUID,
        *,
        replicas: int,
    ) -> DeploymentRecord | None:
        """Scale a deployment to the given replica count (within bounds)."""
        record = await session.get(DeploymentRecord, deployment_id)
        if record is None:
            return None

        old_replicas = record.replicas
        record.replicas = max(record.min_replicas, min(replicas, record.max_replicas))
        record.updated_at = _utcnow()
        session.add(record)
        await session.commit()
        await session.refresh(record)

        await LifecycleManager._record_event(
            session,
            deployment_id=record.id,
            agent_id=record.agent_id,
            event_type="scaled",
            from_state=f"replicas:{old_replicas}",
            to_state=f"replicas:{record.replicas}",
            message=f"Scaled from {old_replicas} to {record.replicas} replicas",
        )

        return record

    # ── Rollback ────────────────────────────────────────────────────

    @staticmethod
    async def rollback(
        session: AsyncSession,
        deployment_id: UUID,
        *,
        reason: str = "manual rollback",
        actor_id: UUID | None = None,
    ) -> DeploymentRecord | None:
        """Roll back a deployment to its predecessor.

        Marks the current deployment as ``rolled_back`` and reactivates
        the previous deployment if one exists.  Returns the reactivated
        deployment, or the current one if no predecessor was found.
        """
        record = await session.get(DeploymentRecord, deployment_id)
        if record is None:
            return None

        old_status = record.status
        record.status = "rolled_back"
        record.updated_at = _utcnow()
        session.add(record)

        reactivated = record
        if record.previous_deployment_id:
            prev = await session.get(DeploymentRecord, record.previous_deployment_id)
            if prev is not None:
                prev.status = "active"
                prev.traffic_percentage = 100
                prev.updated_at = _utcnow()
                session.add(prev)
                reactivated = prev

        await session.commit()
        await session.refresh(record)
        if reactivated is not record:
            await session.refresh(reactivated)

        await LifecycleManager._record_event(
            session,
            deployment_id=record.id,
            agent_id=record.agent_id,
            event_type="rolled_back",
            from_state=old_status,
            to_state="rolled_back",
            message=reason,
            actor_id=actor_id,
        )

        return reactivated

    # ── Retire ──────────────────────────────────────────────────────

    @staticmethod
    async def retire(
        session: AsyncSession,
        deployment_id: UUID,
        *,
        reason: str = "retirement",
        actor_id: UUID | None = None,
    ) -> DeploymentRecord | None:
        """Retire a deployment, taking it permanently offline."""
        record = await session.get(DeploymentRecord, deployment_id)
        if record is None:
            return None

        old_status = record.status
        record.status = "retired"
        record.traffic_percentage = 0
        record.replicas = 0
        record.retired_at = _utcnow()
        record.updated_at = _utcnow()
        session.add(record)
        await session.commit()
        await session.refresh(record)

        await LifecycleManager._record_event(
            session,
            deployment_id=record.id,
            agent_id=record.agent_id,
            event_type="retired",
            from_state=old_status,
            to_state="retired",
            message=reason,
            actor_id=actor_id,
        )

        return record

    # ── Record health check ─────────────────────────────────────────

    @staticmethod
    async def record_health_check(
        session: AsyncSession,
        *,
        deployment_id: UUID,
        status: str = "healthy",
        health_score: float = 1.0,
        error_rate: float = 0.0,
        avg_latency_ms: float = 0.0,
        p95_latency_ms: float = 0.0,
        request_count: int = 0,
        details: dict[str, Any] | None = None,
    ) -> HealthCheck | None:
        """Record a health check and auto-rollback if error rate exceeds threshold."""
        record = await session.get(DeploymentRecord, deployment_id)
        if record is None:
            return None

        check = HealthCheck(
            deployment_id=deployment_id,
            status=status,
            health_score=health_score,
            error_rate=error_rate,
            avg_latency_ms=avg_latency_ms,
            p95_latency_ms=p95_latency_ms,
            request_count=request_count,
            details=details or {},
        )
        session.add(check)
        await session.commit()
        await session.refresh(check)

        # Auto-rollback on high error rate
        if error_rate > record.error_rate_threshold and record.status == "active":
            await LifecycleManager.rollback(
                session,
                deployment_id,
                reason=f"Auto-rollback: error rate {error_rate:.2%} exceeds threshold {record.error_rate_threshold:.2%}",
            )

        # Record health change event if status changed
        if status != "healthy":
            await LifecycleManager._record_event(
                session,
                deployment_id=deployment_id,
                agent_id=record.agent_id,
                event_type="health_changed",
                to_state=status,
                message=f"Health: {status}, error_rate={error_rate:.2%}, score={health_score:.2f}",
                details={"health_score": health_score, "error_rate": error_rate},
            )

        return check

    # ── Queries ──────────────────────────────────────────────────────

    @staticmethod
    async def get_deployment(
        session: AsyncSession,
        deployment_id: UUID,
    ) -> DeploymentRecord | None:
        """Return a single deployment record by ID."""
        return await session.get(DeploymentRecord, deployment_id)

    @staticmethod
    async def list_deployments(
        session: AsyncSession,
        *,
        agent_id: UUID | None = None,
        environment: str | None = None,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[DeploymentRecord], int]:
        """Return paginated deployment records with optional filters."""
        base = select(DeploymentRecord)
        if agent_id is not None:
            base = base.where(DeploymentRecord.agent_id == agent_id)
        if environment is not None:
            base = base.where(DeploymentRecord.environment == environment)
        if status is not None:
            base = base.where(DeploymentRecord.status == status)

        count_result = await session.exec(base)
        total = len(count_result.all())

        stmt = (
            base.offset(offset)
            .limit(limit)
            .order_by(
                DeploymentRecord.created_at.desc()  # type: ignore[union-attr]
            )
        )
        result = await session.exec(stmt)
        records = list(result.all())
        return records, total

    @staticmethod
    async def list_health_checks(
        session: AsyncSession,
        deployment_id: UUID,
        *,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[HealthCheck], int]:
        """Return paginated health checks for a deployment."""
        base = select(HealthCheck).where(
            HealthCheck.deployment_id == deployment_id,
        )
        count_result = await session.exec(base)
        total = len(count_result.all())

        stmt = (
            base.offset(offset)
            .limit(limit)
            .order_by(
                HealthCheck.checked_at.desc()  # type: ignore[union-attr]
            )
        )
        result = await session.exec(stmt)
        checks = list(result.all())
        return checks, total

    @staticmethod
    async def list_events(
        session: AsyncSession,
        *,
        deployment_id: UUID | None = None,
        agent_id: UUID | None = None,
        event_type: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[LifecycleEvent], int]:
        """Return paginated lifecycle events with optional filters."""
        base = select(LifecycleEvent)
        if deployment_id is not None:
            base = base.where(LifecycleEvent.deployment_id == deployment_id)
        if agent_id is not None:
            base = base.where(LifecycleEvent.agent_id == agent_id)
        if event_type is not None:
            base = base.where(LifecycleEvent.event_type == event_type)

        count_result = await session.exec(base)
        total = len(count_result.all())

        stmt = (
            base.offset(offset)
            .limit(limit)
            .order_by(
                LifecycleEvent.created_at.desc()  # type: ignore[union-attr]
            )
        )
        result = await session.exec(stmt)
        events = list(result.all())
        return events, total

    # ── Internals ───────────────────────────────────────────────────

    @staticmethod
    async def _active_deployment(
        session: AsyncSession,
        *,
        agent_id: UUID,
        environment: str,
    ) -> DeploymentRecord | None:
        """Find the currently active deployment for an agent in an environment."""
        stmt = (
            select(DeploymentRecord)
            .where(DeploymentRecord.agent_id == agent_id)
            .where(DeploymentRecord.environment == environment)
            .where(DeploymentRecord.status == "active")
            .order_by(DeploymentRecord.created_at.desc())  # type: ignore[union-attr]
        )
        result = await session.exec(stmt)
        return result.first()

    @staticmethod
    async def _record_event(
        session: AsyncSession,
        *,
        deployment_id: UUID,
        agent_id: UUID,
        event_type: str,
        from_state: str | None = None,
        to_state: str | None = None,
        message: str | None = None,
        actor_id: UUID | None = None,
        details: dict[str, Any] | None = None,
    ) -> LifecycleEvent:
        """Persist an immutable lifecycle event."""
        event = LifecycleEvent(
            deployment_id=deployment_id,
            agent_id=agent_id,
            event_type=event_type,
            from_state=from_state,
            to_state=to_state,
            message=message,
            actor_id=actor_id,
            details=details or {},
        )
        session.add(event)
        await session.commit()
        await session.refresh(event)
        return event


__all__ = [
    "LifecycleManager",
]
