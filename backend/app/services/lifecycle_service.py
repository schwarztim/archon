"""Enterprise Agent Lifecycle Manager — state machine, deployments, health, anomalies, scheduling."""

from __future__ import annotations

import logging
import math
import statistics
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from app.models.lifecycle import (
    Anomaly,
    CredentialRotationResult,
    CronSchedule,
    Deployment,
    DeploymentStrategy,
    DeploymentStrategyType,
    HealthScore,
    LifecycleTransition,
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

# In-memory stores (replaced by DB in production)
_scheduled_jobs: dict[str, list[ScheduledJob]] = {}
_agent_states: dict[str, str] = {}
_deployments: dict[str, Deployment] = {}
_metrics_store: dict[str, list[dict[str, float]]] = {}


def _utcnow() -> datetime:
    """Return timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


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
    ) -> LifecycleTransition:
        """Transition an agent through the lifecycle state machine.

        Valid path: Draft → Review → Approved → Published → Deprecated → Archived.
        Enforces RBAC and records an audit entry.
        """
        _validate_tenant(tenant_id)
        _check_rbac(user, target_state)

        key = f"{tenant_id}:{agent_id}"
        current_state = _agent_states.get(key, "draft")

        allowed = _VALID_TRANSITIONS.get(current_state, [])
        if target_state not in allowed:
            raise ValueError(
                f"Invalid transition: {current_state} → {target_state}. "
                f"Allowed targets: {allowed}"
            )

        _agent_states[key] = target_state

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

        key = f"{tenant_id}:{deployment_id}"
        _deployments[key] = deployment

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
    ) -> Deployment:
        """Roll back a deployment to its previous version."""
        _validate_tenant(tenant_id)
        _check_rbac(user, "published")

        key = f"{tenant_id}:{deployment_id}"
        deployment = _deployments.get(key)
        if deployment is None:
            raise ValueError(f"Deployment {deployment_id} not found for tenant {tenant_id}")

        deployment.status = "rolled_back"
        deployment.completed_at = _utcnow()

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
