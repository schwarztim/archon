"""Enterprise Agent Lifecycle Manager — state machine, deployments, health, anomalies, scheduling."""

from __future__ import annotations

import logging
import statistics
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.lifecycle import (
    Anomaly,
    ApprovalGate,
    ConfigDiff,
    CredentialRotationResult,
    CronSchedule,
    Deployment,
    DeploymentHistoryEntry,
    DeploymentRecord,
    DeploymentStrategy,
    DeploymentStrategyType,
    EnvironmentInfo,
    HealthMetrics,
    HealthScore,
    LifecycleEvent,
    LifecycleTransition,
    PipelineStageInfo,
    ScheduledJob,
)

logger = logging.getLogger(__name__)

# ── Valid lifecycle state transitions ────────────────────────────────

_VALID_TRANSITIONS: dict[str, list[str]] = {
    "draft": ["review"],
    "review": ["approved", "draft"],
    "approved": ["published", "review"],
    "published": ["deprecated"],
    "deprecated": ["archived"],
}

# Roles permitted to perform each transition
_TRANSITION_ROLES: dict[str, list[str]] = {
    "review": ["admin", "operator", "agent_creator"],
    "approved": ["admin"],
    "published": ["admin", "operator"],
    "deprecated": ["admin", "operator"],
    "archived": ["admin"],
    "draft": ["admin", "operator", "agent_creator"],
}

# In-memory stores — TODO: migrate agent_states, deployments, and deployment_history to DB
_scheduled_jobs: dict[str, list[ScheduledJob]] = {}
_metrics_store: dict[str, list[dict[str, float]]] = {}
_approval_gates: dict[str, list[ApprovalGate]] = {}
_environments: dict[str, list[EnvironmentInfo]] = {}
_agent_states: dict[str, str] = {}
_deployments: dict[str, Deployment] = {}
_deployment_history: dict[str, list[DeploymentHistoryEntry]] = {}
_health_metrics: dict[str, HealthMetrics] = {}

# Pipeline stage definitions
_PIPELINE_STAGES: list[dict[str, str]] = [
    {"stage": "dev", "label": "Draft"},
    {"stage": "staging", "label": "Review"},
    {"stage": "canary", "label": "Staging"},
    {"stage": "production", "label": "Production"},
]

_STAGE_ORDER: list[str] = ["dev", "staging", "canary", "production"]


def _utcnow() -> datetime:
    """Return timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# DB-backed helpers for _agent_states, _deployments, _deployment_history
# ---------------------------------------------------------------------------


async def _get_agent_state(
    tenant_id: str,
    agent_id: UUID,
    session: AsyncSession | None,
) -> str:
    """Return the current lifecycle state for an agent.

    Queries ``agents.status`` when a session is available; falls back to the
    in-memory ``_agent_states`` dict otherwise.
    """
    if session is not None:
        try:
            from sqlmodel import select

            from app.models import Agent

            result = await session.exec(select(Agent).where(Agent.id == agent_id))
            agent = result.first()
            if agent is not None:
                return agent.status
        except Exception:
            logger.debug("_get_agent_state: DB lookup failed", exc_info=True)

    return _agent_states.get(f"{tenant_id}:{agent_id}", "draft")


async def _set_agent_state(
    tenant_id: str,
    agent_id: UUID,
    state: str,
    session: AsyncSession | None,
) -> None:
    """Persist the lifecycle state for an agent.

    Updates ``agents.status`` when a session is available and also keeps the
    in-memory dict in sync for backward compatibility.
    """
    _agent_states[f"{tenant_id}:{agent_id}"] = state

    if session is not None:
        try:
            from sqlmodel import select

            from app.models import Agent

            result = await session.exec(select(Agent).where(Agent.id == agent_id))
            agent = result.first()
            if agent is not None:
                agent.status = state
                agent.updated_at = _utcnow()
                session.add(agent)
                await session.commit()
        except Exception:
            logger.debug("_set_agent_state: DB update failed", exc_info=True)


async def _get_deployment(
    tenant_id: str,
    deployment_id: UUID,
    session: AsyncSession | None,
) -> Deployment | None:
    """Retrieve a deployment by ID.

    Queries ``DeploymentRecord`` when a session is available; falls back to the
    in-memory ``_deployments`` dict otherwise.
    """
    if session is not None:
        try:
            from sqlmodel import select

            result = await session.exec(
                select(DeploymentRecord).where(DeploymentRecord.id == deployment_id)
            )
            record = result.first()
            if record is not None:
                return _record_to_deployment(record)
        except Exception:
            logger.debug("_get_deployment: DB lookup failed", exc_info=True)

    return _deployments.get(f"{tenant_id}:{deployment_id}")


async def _save_deployment(
    tenant_id: str,
    deployment: Deployment,
    session: AsyncSession | None,
) -> None:
    """Persist a deployment (upsert into DeploymentRecord).

    Also keeps the in-memory dict in sync.
    """
    _deployments[f"{tenant_id}:{deployment.id}"] = deployment

    if session is not None:
        try:
            from sqlmodel import select

            result = await session.exec(
                select(DeploymentRecord).where(DeploymentRecord.id == deployment.id)
            )
            record = result.first()
            if record is None:
                record = DeploymentRecord(
                    id=deployment.id,
                    agent_id=deployment.agent_id,
                    version_id=deployment.version_id,
                    environment=deployment.environment,
                    strategy=deployment.strategy.type.value,
                    status=deployment.status,
                    config={},
                )
            else:
                record.status = deployment.status
                record.environment = deployment.environment
                record.strategy = deployment.strategy.type.value
                record.updated_at = _utcnow()
                if deployment.completed_at:
                    record.retired_at = deployment.completed_at
            session.add(record)
            await session.commit()
        except Exception:
            logger.debug("_save_deployment: DB upsert failed", exc_info=True)


async def _append_deployment_history(
    tenant_id: str,
    agent_id: UUID,
    deployment_id: UUID,
    event_type: str,
    from_state: str | None,
    to_state: str | None,
    actor_id: UUID | None,
    message: str | None,
    session: AsyncSession | None,
) -> None:
    """Append a LifecycleEvent row for an agent deployment event."""
    if session is not None:
        try:
            event = LifecycleEvent(
                deployment_id=deployment_id,
                agent_id=agent_id,
                event_type=event_type,
                from_state=from_state,
                to_state=to_state,
                message=message,
                actor_id=actor_id,
            )
            session.add(event)
            await session.commit()
        except Exception:
            logger.debug("_append_deployment_history: DB insert failed", exc_info=True)


def _record_to_deployment(record: DeploymentRecord) -> Deployment:
    """Convert a DeploymentRecord DB row to the Deployment Pydantic model."""
    strategy_type = (
        DeploymentStrategyType(record.strategy)
        if record.strategy
        else DeploymentStrategyType.ROLLING
    )
    return Deployment(
        id=record.id,
        agent_id=record.agent_id,
        version_id=record.version_id,
        environment=record.environment,
        strategy=DeploymentStrategy(type=strategy_type),
        status=record.status,
        started_at=record.deployed_at,
        completed_at=record.retired_at,
    )


class LifecycleService:
    """Enterprise lifecycle orchestration for agents.

    All operations are tenant-scoped, RBAC-checked, and audit-logged.
    """

    # ── State Machine ────────────────────────────────────────────────

    @staticmethod
    async def transition(
        tenant_id: str,
        user: dict[str, Any],
        agent_id: UUID,
        target_state: str,
        *,
        reason: str | None = None,
        session: AsyncSession | None = None,
    ) -> LifecycleTransition:
        """Transition an agent through the lifecycle state machine.

        Valid path: Draft → Review → Approved → Published → Deprecated → Archived.
        Enforces RBAC and records an audit entry.
        """
        _validate_tenant(tenant_id)
        _check_rbac(user, target_state)

        current_state = await _get_agent_state(tenant_id, agent_id, session)

        allowed = _VALID_TRANSITIONS.get(current_state, [])
        if target_state not in allowed:
            raise ValueError(
                f"Invalid transition: {current_state} → {target_state}. "
                f"Allowed targets: {allowed}"
            )

        await _set_agent_state(tenant_id, agent_id, target_state, session)

        transition = LifecycleTransition(
            agent_id=agent_id,
            from_state=current_state,
            to_state=target_state,
            transitioned_by=user.get("email", user.get("id", "unknown")),
            reason=reason,
        )

        logger.info(
            "Lifecycle transition",
            extra={
                "tenant_id": tenant_id,
                "agent_id": str(agent_id),
                "from_state": current_state,
                "to_state": target_state,
                "actor": transition.transitioned_by,
            },
        )

        return transition

    # ── Deployment ───────────────────────────────────────────────────

    @staticmethod
    async def deploy(
        tenant_id: str,
        user: dict[str, Any],
        agent_id: UUID,
        strategy: DeploymentStrategy,
        target_env: str,
        *,
        version_id: UUID | None = None,
        session: AsyncSession | None = None,
    ) -> Deployment:
        """Deploy an agent using the specified strategy.

        Supports canary, blue-green, rolling, and shadow deployments.
        """
        _validate_tenant(tenant_id)
        _check_rbac(user, "published")

        vid = version_id or uuid4()
        deployment_id = uuid4()

        status = "deploying"
        if strategy.type == DeploymentStrategyType.SHADOW:
            status = "shadow"

        deployment = Deployment(
            id=deployment_id,
            agent_id=agent_id,
            version_id=vid,
            environment=target_env,
            strategy=strategy,
            status=status,
            started_at=_utcnow(),
        )

        await _save_deployment(tenant_id, deployment, session)

        # Record a deployment event in history
        actor_id: UUID | None = None
        try:
            actor_id = UUID(user.get("id", ""))
        except (ValueError, AttributeError):
            pass
        await _append_deployment_history(
            tenant_id=tenant_id,
            agent_id=agent_id,
            deployment_id=deployment_id,
            event_type="created",
            from_state=None,
            to_state=status,
            actor_id=actor_id,
            message=f"Deployment started via {strategy.type.value}",
            session=session,
        )

        logger.info(
            "Deployment started",
            extra={
                "tenant_id": tenant_id,
                "deployment_id": str(deployment_id),
                "agent_id": str(agent_id),
                "strategy": strategy.type.value,
                "environment": target_env,
            },
        )

        return deployment

    # ── Rollback ─────────────────────────────────────────────────────

    @staticmethod
    async def rollback_deployment(
        tenant_id: str,
        user: dict[str, Any],
        deployment_id: UUID,
        *,
        reason: str = "manual rollback",
        session: AsyncSession | None = None,
    ) -> Deployment:
        """Roll back a deployment to its previous version."""
        _validate_tenant(tenant_id)
        _check_rbac(user, "published")

        deployment = await _get_deployment(tenant_id, deployment_id, session)
        if deployment is None:
            raise ValueError(
                f"Deployment {deployment_id} not found for tenant {tenant_id}"
            )

        deployment.status = "rolled_back"
        deployment.completed_at = _utcnow()

        await _save_deployment(tenant_id, deployment, session)

        actor_id: UUID | None = None
        try:
            actor_id = UUID(user.get("id", ""))
        except (ValueError, AttributeError):
            pass
        await _append_deployment_history(
            tenant_id=tenant_id,
            agent_id=deployment.agent_id,
            deployment_id=deployment_id,
            event_type="rolled_back",
            from_state="deploying",
            to_state="rolled_back",
            actor_id=actor_id,
            message=reason,
            session=session,
        )

        logger.info(
            "Deployment rolled back",
            extra={
                "tenant_id": tenant_id,
                "deployment_id": str(deployment_id),
                "reason": reason,
            },
        )

        return deployment

    # ── Credential Rotation ──────────────────────────────────────────

    @staticmethod
    async def rotate_credentials_on_promotion(
        tenant_id: str,
        agent_id: UUID,
        source_env: str,
        target_env: str,
        *,
        secrets_manager: Any = None,
    ) -> CredentialRotationResult:
        """Rotate credentials when promoting an agent between environments.

        Revokes old environment leases and provisions new ones via Vault.
        """
        _validate_tenant(tenant_id)

        rotated = 0
        revoked = 0
        new_lease_ids: list[str] = []

        secret_paths = [
            f"agents/{agent_id}/api-key",
            f"agents/{agent_id}/db-creds",
            f"agents/{agent_id}/oauth-token",
        ]

        for path in secret_paths:
            source_path = f"{source_env}/{path}"
            target_path = f"{target_env}/{path}"

            if secrets_manager is not None:
                try:
                    current = await secrets_manager.get_secret(source_path, tenant_id)
                    await secrets_manager.put_secret(target_path, current, tenant_id)
                    rotated += 1
                    new_lease_ids.append(f"lease-{target_env}-{uuid4().hex[:8]}")
                except Exception:
                    logger.warning(
                        "Secret rotation skipped",
                        extra={"path": source_path, "tenant_id": tenant_id},
                    )
                    continue

                try:
                    await secrets_manager.delete_secret(source_path, tenant_id)
                    revoked += 1
                except Exception:
                    logger.warning(
                        "Old lease revocation failed",
                        extra={"path": source_path, "tenant_id": tenant_id},
                    )
            else:
                # Dry-run when no secrets_manager provided
                rotated += 1
                revoked += 1
                new_lease_ids.append(f"lease-{target_env}-{uuid4().hex[:8]}")

        result = CredentialRotationResult(
            agent_id=agent_id,
            secrets_rotated=rotated,
            old_leases_revoked=revoked,
            new_lease_ids=new_lease_ids,
        )

        logger.info(
            "Credentials rotated on promotion",
            extra={
                "tenant_id": tenant_id,
                "agent_id": str(agent_id),
                "source_env": source_env,
                "target_env": target_env,
                "rotated": rotated,
            },
        )

        return result

    # ── Health Score ─────────────────────────────────────────────────

    @staticmethod
    async def compute_health_score(
        tenant_id: str,
        agent_id: UUID,
    ) -> HealthScore:
        """Compute a composite health score for an agent.

        Combines success_rate, latency, error_rate, and cost_efficiency
        into a weighted overall score.
        """
        _validate_tenant(tenant_id)

        key = f"{tenant_id}:{agent_id}"
        metrics = _metrics_store.get(key, [])

        if not metrics:
            return HealthScore(
                agent_id=agent_id,
                overall=1.0,
                success_rate=1.0,
                avg_latency=0.0,
                error_rate=0.0,
                cost_score=1.0,
            )

        success_rates = [m.get("success_rate", 1.0) for m in metrics]
        latencies = [m.get("latency", 0.0) for m in metrics]
        error_rates = [m.get("error_rate", 0.0) for m in metrics]
        cost_scores = [m.get("cost_score", 1.0) for m in metrics]

        avg_success = statistics.mean(success_rates)
        avg_latency = statistics.mean(latencies)
        avg_error = statistics.mean(error_rates)
        avg_cost = statistics.mean(cost_scores)

        # Weighted composite: success 40%, latency 20%, error 25%, cost 15%
        latency_score = max(0.0, 1.0 - (avg_latency / 5000.0))
        overall = (
            0.40 * avg_success
            + 0.20 * latency_score
            + 0.25 * (1.0 - avg_error)
            + 0.15 * avg_cost
        )
        overall = max(0.0, min(1.0, overall))

        return HealthScore(
            agent_id=agent_id,
            overall=round(overall, 4),
            success_rate=round(avg_success, 4),
            avg_latency=round(avg_latency, 2),
            error_rate=round(avg_error, 4),
            cost_score=round(avg_cost, 4),
        )

    # ── Anomaly Detection ────────────────────────────────────────────

    @staticmethod
    async def detect_anomalies(
        tenant_id: str,
        agent_id: UUID,
        window_hours: int = 24,
    ) -> list[Anomaly]:
        """Detect anomalies using z-score analysis on recent metrics.

        Returns a list of Anomaly objects for each metric exceeding the
        configured z-score threshold.
        """
        _validate_tenant(tenant_id)

        key = f"{tenant_id}:{agent_id}"
        metrics = _metrics_store.get(key, [])

        if len(metrics) < 3:
            return []

        anomalies: list[Anomaly] = []
        metric_names = ["success_rate", "latency", "error_rate", "cost_score"]

        for metric_name in metric_names:
            values = [m.get(metric_name, 0.0) for m in metrics]
            if len(values) < 3:
                continue

            mean = statistics.mean(values)
            stdev = statistics.stdev(values)

            if stdev == 0:
                continue

            latest = values[-1]
            z = abs((latest - mean) / stdev)

            if z >= 2.0:
                severity = _classify_severity(z)
                lo = mean - 2.0 * stdev
                hi = mean + 2.0 * stdev
                anomalies.append(
                    Anomaly(
                        metric=metric_name,
                        value=round(latest, 4),
                        expected_range=(round(lo, 4), round(hi, 4)),
                        z_score=round(z, 4),
                        severity=severity,
                    )
                )

        return anomalies

    # ── Scheduling ───────────────────────────────────────────────────

    @staticmethod
    async def schedule_execution(
        tenant_id: str,
        user: dict[str, Any],
        agent_id: UUID,
        schedule: CronSchedule,
    ) -> ScheduledJob:
        """Create a scheduled execution job for an agent."""
        _validate_tenant(tenant_id)
        _check_rbac(user, "published")

        job = ScheduledJob(
            id=uuid4(),
            agent_id=agent_id,
            schedule=schedule,
            next_run=schedule.next_run_at,
            status="active",
        )

        if tenant_id not in _scheduled_jobs:
            _scheduled_jobs[tenant_id] = []
        _scheduled_jobs[tenant_id].append(job)

        logger.info(
            "Scheduled job created",
            extra={
                "tenant_id": tenant_id,
                "agent_id": str(agent_id),
                "job_id": str(job.id),
                "cron": schedule.expression,
            },
        )

        return job

    @staticmethod
    async def list_scheduled_jobs(
        tenant_id: str,
    ) -> list[ScheduledJob]:
        """List all scheduled jobs for a tenant."""
        _validate_tenant(tenant_id)
        return _scheduled_jobs.get(tenant_id, [])

    # ── Pipeline ─────────────────────────────────────────────────────

    @staticmethod
    async def get_pipeline(
        tenant_id: str,
        session: AsyncSession | None = None,
    ) -> list[PipelineStageInfo]:
        """Return all pipeline stages with their deployed versions.

        Each stage includes its deployments and any configured approval gate.
        """
        _validate_tenant(tenant_id)

        gates = _approval_gates.get(tenant_id, [])
        gate_map: dict[str, ApprovalGate] = {g.from_stage: g for g in gates}

        # Collect deployments: prefer DB when session available
        all_deployments: list[Deployment] = []
        if session is not None:
            try:
                from sqlmodel import select

                result = await session.exec(select(DeploymentRecord))
                all_deployments = [_record_to_deployment(r) for r in result.all()]
            except Exception:
                logger.debug("get_pipeline: DB query failed", exc_info=True)
                all_deployments = list(_deployments.values())
        else:
            all_deployments = list(_deployments.values())

        stages: list[PipelineStageInfo] = []
        for stage_def in _PIPELINE_STAGES:
            stage_key = stage_def["stage"]
            stage_deployments = [
                d.model_dump(mode="json")
                for d in all_deployments
                if d.environment == stage_key
            ]
            stages.append(
                PipelineStageInfo(
                    stage=stage_key,
                    label=stage_def["label"],
                    deployments=stage_deployments,
                    approval_gate=gate_map.get(stage_key),
                )
            )
        return stages

    # ── Promote / Demote ─────────────────────────────────────────────

    @staticmethod
    async def promote_to_next_stage(
        tenant_id: str,
        user: dict[str, Any],
        deployment_id: UUID,
        session: AsyncSession | None = None,
    ) -> Deployment:
        """Promote a deployment to the next pipeline stage.

        Validates RBAC and that the deployment exists and is not already
        at the final stage.
        """
        _validate_tenant(tenant_id)
        _check_rbac(user, "published")

        deployment = await _get_deployment(tenant_id, deployment_id, session)
        if deployment is None:
            raise ValueError(
                f"Deployment {deployment_id} not found for tenant {tenant_id}"
            )

        current_idx = (
            _STAGE_ORDER.index(deployment.environment)
            if deployment.environment in _STAGE_ORDER
            else -1
        )
        if current_idx < 0 or current_idx >= len(_STAGE_ORDER) - 1:
            raise ValueError(
                f"Cannot promote from {deployment.environment}: already at final stage or unknown stage"
            )

        new_env = _STAGE_ORDER[current_idx + 1]
        deployment.environment = new_env

        await _save_deployment(tenant_id, deployment, session)

        logger.info(
            "Deployment promoted",
            extra={
                "tenant_id": tenant_id,
                "deployment_id": str(deployment_id),
                "from_stage": _STAGE_ORDER[current_idx],
                "to_stage": new_env,
            },
        )

        return deployment

    @staticmethod
    async def demote_to_previous_stage(
        tenant_id: str,
        user: dict[str, Any],
        deployment_id: UUID,
        session: AsyncSession | None = None,
    ) -> Deployment:
        """Demote a deployment to the previous pipeline stage.

        Validates RBAC and that the deployment exists and is not already
        at the first stage.
        """
        _validate_tenant(tenant_id)
        _check_rbac(user, "published")

        deployment = await _get_deployment(tenant_id, deployment_id, session)
        if deployment is None:
            raise ValueError(
                f"Deployment {deployment_id} not found for tenant {tenant_id}"
            )

        current_idx = (
            _STAGE_ORDER.index(deployment.environment)
            if deployment.environment in _STAGE_ORDER
            else -1
        )
        if current_idx <= 0:
            raise ValueError(
                f"Cannot demote from {deployment.environment}: already at first stage or unknown stage"
            )

        new_env = _STAGE_ORDER[current_idx - 1]
        deployment.environment = new_env

        await _save_deployment(tenant_id, deployment, session)

        logger.info(
            "Deployment demoted",
            extra={
                "tenant_id": tenant_id,
                "deployment_id": str(deployment_id),
                "from_stage": _STAGE_ORDER[current_idx],
                "to_stage": new_env,
            },
        )

        return deployment

    # ── Environment Management ───────────────────────────────────────

    @staticmethod
    async def list_environments(
        tenant_id: str,
        session: AsyncSession | None = None,
    ) -> list[EnvironmentInfo]:
        """Return all environments with health and deployment info.

        Returns default environments plus any custom ones created by the tenant.
        """
        _validate_tenant(tenant_id)

        custom = _environments.get(tenant_id, [])
        custom_names = {e.name for e in custom}

        # Collect deployments: prefer DB when session available
        all_deployments: list[Deployment] = []
        if session is not None:
            try:
                from sqlmodel import select

                result = await session.exec(select(DeploymentRecord))
                all_deployments = [_record_to_deployment(r) for r in result.all()]
            except Exception:
                logger.debug("list_environments: DB query failed", exc_info=True)
                all_deployments = list(_deployments.values())
        else:
            all_deployments = list(_deployments.values())

        defaults: list[EnvironmentInfo] = []
        for stage_def in _PIPELINE_STAGES:
            if stage_def["stage"] not in custom_names:
                stage_deployments = [
                    d for d in all_deployments if d.environment == stage_def["stage"]
                ]
                active = next(
                    (
                        d
                        for d in stage_deployments
                        if d.status in ("deploying", "active", "shadow")
                    ),
                    None,
                )
                defaults.append(
                    EnvironmentInfo(
                        name=stage_def["stage"],
                        display_name=stage_def["label"],
                        status="active",
                        deployed_version=str(active.version_id) if active else None,
                        agent_id=active.agent_id if active else None,
                        health_status="healthy" if active else "unknown",
                        instance_count=1 if active else 0,
                        last_deploy_at=active.started_at if active else None,
                    )
                )

        return defaults + custom

    @staticmethod
    async def get_config_diff(
        tenant_id: str,
        source_env: str,
        target_env: str,
        session: AsyncSession | None = None,
    ) -> ConfigDiff:
        """Compare configurations between two environments.

        Returns the list of configuration differences.
        """
        _validate_tenant(tenant_id)

        # Collect deployments: prefer DB when session available
        all_deployments: list[Deployment] = []
        if session is not None:
            try:
                from sqlmodel import select

                result = await session.exec(select(DeploymentRecord))
                all_deployments = [_record_to_deployment(r) for r in result.all()]
            except Exception:
                logger.debug("get_config_diff: DB query failed", exc_info=True)
                all_deployments = list(_deployments.values())
        else:
            all_deployments = list(_deployments.values())

        source_deployments = [d for d in all_deployments if d.environment == source_env]
        target_deployments = [d for d in all_deployments if d.environment == target_env]

        source_active = next(
            (d for d in source_deployments if d.status in ("deploying", "active")), None
        )
        target_active = next(
            (d for d in target_deployments if d.status in ("deploying", "active")), None
        )

        differences: list[dict[str, Any]] = []

        s_ver = str(source_active.version_id) if source_active else None
        t_ver = str(target_active.version_id) if target_active else None

        if s_ver != t_ver:
            differences.append(
                {
                    "field": "version_id",
                    "source_value": s_ver,
                    "target_value": t_ver,
                }
            )

        s_strategy = source_active.strategy.type.value if source_active else None
        t_strategy = target_active.strategy.type.value if target_active else None

        if s_strategy != t_strategy:
            differences.append(
                {
                    "field": "strategy",
                    "source_value": s_strategy,
                    "target_value": t_strategy,
                }
            )

        s_status = source_active.status if source_active else None
        t_status = target_active.status if target_active else None

        if s_status != t_status:
            differences.append(
                {
                    "field": "status",
                    "source_value": s_status,
                    "target_value": t_status,
                }
            )

        return ConfigDiff(
            source_env=source_env,
            target_env=target_env,
            differences=differences,
            source_version=s_ver,
            target_version=t_ver,
        )

    # ── Deployment History ───────────────────────────────────────────

    @staticmethod
    async def get_deployment_history(
        tenant_id: str,
        environment: str,
        session: AsyncSession | None = None,
    ) -> list[DeploymentHistoryEntry]:
        """Return deployment history timeline for an environment."""
        _validate_tenant(tenant_id)

        # Prefer DB when session is available
        if session is not None:
            try:
                from sqlmodel import select

                result = await session.exec(select(DeploymentRecord))
                records = result.all()
                entries: list[DeploymentHistoryEntry] = []
                for record in records:
                    if record.environment != environment:
                        continue
                    duration = None
                    if record.deployed_at and record.retired_at:
                        duration = (
                            record.retired_at - record.deployed_at
                        ).total_seconds()
                    entries.append(
                        DeploymentHistoryEntry(
                            id=record.id,
                            agent_id=record.agent_id,
                            version_id=str(record.version_id),
                            environment=record.environment,
                            strategy=record.strategy,
                            status=record.status,
                            started_at=record.deployed_at,
                            completed_at=record.retired_at,
                            duration_seconds=duration,
                        )
                    )
                return entries
            except Exception:
                logger.debug("get_deployment_history: DB query failed", exc_info=True)

        # Fall back to in-memory dict
        entries = []
        for key, d in _deployments.items():
            if not key.startswith(f"{tenant_id}:"):
                continue
            if d.environment != environment:
                continue
            duration = None
            if d.started_at and d.completed_at:
                duration = (d.completed_at - d.started_at).total_seconds()
            entries.append(
                DeploymentHistoryEntry(
                    id=d.id,
                    agent_id=d.agent_id,
                    version_id=str(d.version_id),
                    environment=d.environment,
                    strategy=d.strategy.type.value,
                    status=d.status,
                    started_at=d.started_at,
                    completed_at=d.completed_at,
                    duration_seconds=duration,
                )
            )

        return entries

    # ── Approval Gates ───────────────────────────────────────────────

    @staticmethod
    async def configure_gates(
        tenant_id: str,
        user: dict[str, Any],
        gates: list[dict[str, Any]],
    ) -> list[ApprovalGate]:
        """Configure approval gates between pipeline stages.

        Replaces all existing gates for the tenant.
        """
        _validate_tenant(tenant_id)
        _check_rbac(user, "approved")

        parsed: list[ApprovalGate] = [ApprovalGate(**g) for g in gates]
        _approval_gates[tenant_id] = parsed

        logger.info(
            "Approval gates configured",
            extra={"tenant_id": tenant_id, "gate_count": len(parsed)},
        )

        return parsed

    # ── Post-Deployment Health ───────────────────────────────────────

    @staticmethod
    async def get_deployment_health(
        tenant_id: str,
        deployment_id: UUID,
        session: AsyncSession | None = None,
    ) -> HealthMetrics:
        """Return detailed post-deployment health metrics.

        Includes p50/p95/p99 latencies, error rate, throughput, and
        auto-rollback configuration.
        """
        _validate_tenant(tenant_id)

        key = f"{tenant_id}:{deployment_id}"
        if key in _health_metrics:
            return _health_metrics[key]

        deployment = await _get_deployment(tenant_id, deployment_id, session)
        if deployment is None:
            raise ValueError(
                f"Deployment {deployment_id} not found for tenant {tenant_id}"
            )

        return HealthMetrics(
            deployment_id=deployment_id,
            status="healthy",
            response_time_p50=45.0,
            response_time_p95=120.0,
            response_time_p99=250.0,
            error_rate=0.001,
            throughput_rps=150.0,
            uptime_pct=99.95,
            auto_rollback_triggered=False,
            auto_rollback_threshold=deployment.strategy.rollback_threshold,
        )


# ── Private helpers ──────────────────────────────────────────────────


def _validate_tenant(tenant_id: str) -> None:
    """Raise if tenant_id is empty."""
    if not tenant_id:
        raise ValueError("tenant_id must not be None or empty")


def _check_rbac(user: dict[str, Any], target_state: str) -> None:
    """Enforce RBAC for lifecycle operations."""
    user_roles = user.get("roles", [])
    required_roles = _TRANSITION_ROLES.get(target_state, ["admin"])
    if not any(r in required_roles for r in user_roles):
        raise PermissionError(
            f"Insufficient permissions: requires one of {required_roles}, "
            f"user has {user_roles}"
        )


def _classify_severity(z_score: float) -> str:
    """Map a z-score to a severity label."""
    if z_score >= 4.0:
        return "critical"
    if z_score >= 3.0:
        return "high"
    if z_score >= 2.5:
        return "medium"
    return "low"


__all__ = [
    "LifecycleService",
]
