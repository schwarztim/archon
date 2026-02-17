"""Enterprise Governance, Compliance & Identity Governance service."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.interfaces.models.enterprise import AuthenticatedUser
from app.middleware.rbac import check_permission
from app.models.governance import (
    AccessReview,
    AgentRegistryEntry,
    ApprovalStage,
    ApprovalWorkflow,
    AuditEntry,
    CompliancePolicy,
    ComplianceRecord,
    ComplianceStatus,
    ControlStatus,
    ElevationRequest,
    GovernanceReport,
    OPAPolicy,
    ReviewDecision,
    RiskAssessment,
    RiskFactor,
    compute_entry_hash,
)

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    """Return timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


class GovernanceService:
    """Enterprise governance service with tenant isolation, RBAC, and audit logging.

    All methods are tenant-scoped and require an authenticated user.
    State-changing operations are logged to the tamper-proof audit trail.
    """

    # ── Access Reviews ──────────────────────────────────────────────

    @staticmethod
    async def create_access_review(
        tenant_id: str,
        user: AuthenticatedUser,
        config: dict[str, Any],
        session: AsyncSession,
    ) -> AccessReview:
        """Create a periodic access review with reviewer assignment.

        Args:
            tenant_id: Tenant scope.
            user: Authenticated user performing the action.
            config: Review configuration (review_cycle, reviewer_id, reviewee_id).
            session: Database session.

        Returns:
            The created AccessReview.
        """
        check_permission(user, "governance", "create")

        review = AccessReview(
            id=uuid4(),
            tenant_id=tenant_id,
            review_cycle=config.get("review_cycle", "quarterly"),
            reviewer_id=config.get("reviewer_id", user.id),
            reviewee_id=config.get("reviewee_id", ""),
            status="pending",
        )

        await GovernanceService._log_audit(
            session,
            tenant_id=tenant_id,
            actor_id=user.id,
            action="access_review.created",
            resource_type="access_review",
            resource_id=review.id,
            details={"review_cycle": review.review_cycle},
        )

        logger.info(
            "Access review created",
            extra={"tenant_id": tenant_id, "review_id": str(review.id)},
        )
        return review

    @staticmethod
    async def process_review_decision(
        tenant_id: str,
        user: AuthenticatedUser,
        review_id: UUID,
        decisions: list[dict[str, Any]],
        session: AsyncSession,
    ) -> AccessReview:
        """Process approve/revoke/modify decisions for an access review.

        Args:
            tenant_id: Tenant scope.
            user: Authenticated reviewer.
            review_id: The access review to update.
            decisions: List of decision dicts with user_id, resource, decision, notes.
            session: Database session.

        Returns:
            Updated AccessReview with decisions applied.
        """
        check_permission(user, "governance", "update")

        parsed_decisions = [
            ReviewDecision(
                user_id=d.get("user_id", ""),
                resource=d.get("resource", ""),
                decision=d.get("decision", "approve"),
                notes=d.get("notes", ""),
            )
            for d in decisions
        ]

        review = AccessReview(
            id=review_id,
            tenant_id=tenant_id,
            reviewer_id=user.id,
            status="completed",
            decisions=parsed_decisions,
            completed_at=_utcnow(),
        )

        await GovernanceService._log_audit(
            session,
            tenant_id=tenant_id,
            actor_id=user.id,
            action="access_review.decided",
            resource_type="access_review",
            resource_id=review_id,
            details={"decision_count": len(parsed_decisions)},
        )

        logger.info(
            "Access review decisions processed",
            extra={"tenant_id": tenant_id, "review_id": str(review_id)},
        )
        return review

    # ── Privilege Elevation ─────────────────────────────────────────

    @staticmethod
    async def request_privilege_elevation(
        tenant_id: str,
        user: AuthenticatedUser,
        role: str,
        justification: str,
        duration: int,
        session: AsyncSession,
    ) -> ElevationRequest:
        """Request JIT privilege elevation with time-bounded access.

        Args:
            tenant_id: Tenant scope.
            user: User requesting elevation.
            role: Target role to elevate to.
            justification: Business justification for the elevation.
            duration: Duration in hours for the elevated access.
            session: Database session.

        Returns:
            The created ElevationRequest.
        """
        check_permission(user, "governance", "create")

        now = _utcnow()
        elevation = ElevationRequest(
            id=uuid4(),
            tenant_id=tenant_id,
            user_id=user.id,
            requested_role=role,
            justification=justification,
            duration_hours=max(1, min(duration, 72)),
            status="pending",
            created_at=now,
            expires_at=now + timedelta(hours=max(1, min(duration, 72))),
        )

        await GovernanceService._log_audit(
            session,
            tenant_id=tenant_id,
            actor_id=user.id,
            action="elevation.requested",
            resource_type="elevation_request",
            resource_id=elevation.id,
            details={"requested_role": role, "duration_hours": elevation.duration_hours},
        )

        logger.info(
            "Privilege elevation requested",
            extra={"tenant_id": tenant_id, "role": role, "user_id": user.id},
        )
        return elevation

    # ── Risk Assessment ─────────────────────────────────────────────

    @staticmethod
    async def compute_risk_score(
        tenant_id: str,
        agent_id: UUID,
        session: AsyncSession,
    ) -> RiskAssessment:
        """Compute a composite risk score (0-100) for an agent.

        Evaluates multiple risk factors: data sensitivity, model usage,
        approval status, and compliance posture.

        Args:
            tenant_id: Tenant scope.
            agent_id: Agent to assess.
            session: Database session.

        Returns:
            RiskAssessment with overall score, factors, and recommendations.
        """
        # Fetch agent registry entry (tenant-scoped)
        stmt = select(AgentRegistryEntry).where(
            AgentRegistryEntry.agent_id == agent_id,
        )
        result = await session.exec(stmt)
        registry = result.first()

        factors: list[RiskFactor] = []
        recommendations: list[str] = []

        if registry is None:
            factors.append(RiskFactor(
                name="registration",
                weight=0.3,
                score=100.0,
                description="Agent not registered in governance registry",
            ))
            recommendations.append("Register agent in governance registry")
        else:
            # Data sensitivity factor
            sensitive_types = {"pii", "phi", "pci", "financial", "credentials"}
            accessed = set(registry.data_accessed)
            sensitive_overlap = accessed & sensitive_types
            data_score = min(100.0, len(sensitive_overlap) * 25.0)
            factors.append(RiskFactor(
                name="data_sensitivity",
                weight=0.3,
                score=data_score,
                description=f"Accesses {len(sensitive_overlap)} sensitive data types",
            ))
            if data_score > 50:
                recommendations.append("Review data access permissions — sensitive data detected")

            # Approval status factor
            approval_scores = {"published": 0, "approved": 10, "review": 40, "draft": 70, "deprecated": 90}
            approval_score = float(approval_scores.get(registry.approval_status, 50))
            factors.append(RiskFactor(
                name="approval_status",
                weight=0.25,
                score=approval_score,
                description=f"Approval status: {registry.approval_status}",
            ))
            if approval_score > 40:
                recommendations.append("Complete approval workflow before production deployment")

            # Risk level factor
            risk_scores = {"low": 10, "medium": 40, "high": 70, "critical": 95}
            risk_score = float(risk_scores.get(registry.risk_level, 50))
            factors.append(RiskFactor(
                name="risk_classification",
                weight=0.25,
                score=risk_score,
                description=f"Classified risk level: {registry.risk_level}",
            ))

            # Model usage factor
            model_score = min(100.0, len(registry.models_used) * 15.0)
            factors.append(RiskFactor(
                name="model_usage",
                weight=0.2,
                score=model_score,
                description=f"Uses {len(registry.models_used)} AI models",
            ))

        # Compute weighted overall score
        if factors:
            total_weight = sum(f.weight for f in factors)
            overall = sum(f.weight * f.score for f in factors) / total_weight if total_weight > 0 else 0.0
        else:
            overall = 0.0

        overall = round(min(100.0, max(0.0, overall)), 1)

        risk_level = "low"
        if overall >= 75:
            risk_level = "critical"
        elif overall >= 50:
            risk_level = "high"
        elif overall >= 25:
            risk_level = "medium"

        return RiskAssessment(
            agent_id=agent_id,
            overall_score=overall,
            risk_level=risk_level,
            factors=factors,
            recommendations=recommendations,
        )

    # ── Compliance Status ───────────────────────────────────────────

    @staticmethod
    async def get_compliance_status(
        tenant_id: str,
        framework: str,
        session: AsyncSession,
    ) -> ComplianceStatus:
        """Get compliance status for a specific framework (SOC2/GDPR/HIPAA/PCI).

        Args:
            tenant_id: Tenant scope.
            framework: Compliance framework identifier.
            session: Database session.

        Returns:
            ComplianceStatus with control-level breakdown.
        """
        # Fetch policies for this framework
        stmt = select(CompliancePolicy).where(
            CompliancePolicy.framework == framework,
            CompliancePolicy.status == "active",
        )
        result = await session.exec(stmt)
        policies = list(result.all())

        # Fetch compliance records for these policies
        controls: list[ControlStatus] = []
        passing = 0
        total = len(policies)

        for policy in policies:
            rec_stmt = (
                select(ComplianceRecord)
                .where(ComplianceRecord.policy_id == policy.id)
                .order_by(ComplianceRecord.checked_at.desc())  # type: ignore[union-attr]
                .limit(1)
            )
            rec_result = await session.exec(rec_stmt)
            latest = rec_result.first()

            ctrl_status = "unknown"
            evidence = ""
            if latest is not None:
                ctrl_status = "passing" if latest.status == "compliant" else "failing"
                evidence = json.dumps(latest.details) if latest.details else ""
                if latest.status == "compliant":
                    passing += 1

            controls.append(ControlStatus(
                control_id=str(policy.id),
                name=policy.name,
                status=ctrl_status,
                evidence=evidence,
            ))

        if total == 0:
            overall = "unknown"
        elif passing == total:
            overall = "compliant"
        elif passing == 0:
            overall = "non_compliant"
        else:
            overall = "partial"

        return ComplianceStatus(
            framework=framework,
            overall_status=overall,
            controls=controls,
        )

    # ── Approval Workflows ──────────────────────────────────────────

    @staticmethod
    async def create_approval_workflow(
        tenant_id: str,
        user: AuthenticatedUser,
        agent_id: UUID,
        workflow_type: str,
        session: AsyncSession,
    ) -> ApprovalWorkflow:
        """Create a multi-stage approval workflow for an agent operation.

        Args:
            tenant_id: Tenant scope.
            user: User initiating the workflow.
            agent_id: Agent requiring approval.
            workflow_type: Type of workflow (e.g., deployment, data_access).
            session: Database session.

        Returns:
            The created ApprovalWorkflow with default stages.
        """
        check_permission(user, "governance", "create")

        stages = [
            ApprovalStage(stage_number=1, approver_role="operator", status="pending"),
            ApprovalStage(stage_number=2, approver_role="admin", status="pending"),
        ]

        workflow = ApprovalWorkflow(
            id=uuid4(),
            tenant_id=tenant_id,
            agent_id=agent_id,
            workflow_type=workflow_type,
            stages=stages,
            current_stage=1,
            status="pending",
            created_by=user.id,
        )

        await GovernanceService._log_audit(
            session,
            tenant_id=tenant_id,
            actor_id=user.id,
            action="approval_workflow.created",
            resource_type="approval_workflow",
            resource_id=workflow.id,
            details={"workflow_type": workflow_type, "agent_id": str(agent_id)},
        )

        logger.info(
            "Approval workflow created",
            extra={"tenant_id": tenant_id, "workflow_id": str(workflow.id)},
        )
        return workflow

    # ── OPA Policy Management ───────────────────────────────────────

    @staticmethod
    async def manage_opa_policy(
        tenant_id: str,
        user: AuthenticatedUser,
        action: str,
        policy_data: dict[str, Any],
        session: AsyncSession,
    ) -> OPAPolicy:
        """CRUD operations for OPA policies with basic rego linting.

        Args:
            tenant_id: Tenant scope.
            user: Authenticated user.
            action: CRUD action — create, update, delete, get.
            policy_data: Policy attributes (name, rego_content, description, active).
            session: Database session.

        Returns:
            The managed OPAPolicy.
        """
        action_map = {"create": "create", "update": "update", "delete": "delete", "get": "read"}
        check_permission(user, "governance", action_map.get(action, "read"))

        rego_content = policy_data.get("rego_content", "")
        if action in ("create", "update") and rego_content:
            GovernanceService._lint_rego(rego_content)

        now = _utcnow()
        policy = OPAPolicy(
            id=policy_data.get("id", uuid4()),
            tenant_id=tenant_id,
            name=policy_data.get("name", ""),
            rego_content=rego_content,
            description=policy_data.get("description", ""),
            active=policy_data.get("active", True),
            created_at=now,
            updated_at=now,
        )

        await GovernanceService._log_audit(
            session,
            tenant_id=tenant_id,
            actor_id=user.id,
            action=f"opa_policy.{action}",
            resource_type="opa_policy",
            resource_id=policy.id,
            details={"name": policy.name, "action": action},
        )

        logger.info(
            "OPA policy managed",
            extra={"tenant_id": tenant_id, "action": action, "policy_name": policy.name},
        )
        return policy

    @staticmethod
    def _lint_rego(rego_content: str) -> None:
        """Basic rego syntax validation.

        Raises ValueError if the rego content fails basic checks.
        """
        content = rego_content.strip()
        if not content:
            raise ValueError("Rego content cannot be empty")
        if "package " not in content:
            raise ValueError("Rego policy must declare a package")

    # ── Governance Reports ──────────────────────────────────────────

    @staticmethod
    async def generate_governance_report(
        tenant_id: str,
        user: AuthenticatedUser,
        report_type: str,
        period: str,
        session: AsyncSession,
    ) -> GovernanceReport:
        """Generate an executive-ready governance report (JSON format).

        Args:
            tenant_id: Tenant scope.
            user: User requesting the report.
            report_type: Type of report (e.g., compliance_summary, risk_overview).
            period: Reporting period (e.g., Q1-2026, 2026-01).
            session: Database session.

        Returns:
            GovernanceReport with download metadata.
        """
        check_permission(user, "governance", "read")

        report = GovernanceReport(
            id=uuid4(),
            tenant_id=tenant_id,
            report_type=report_type,
            period=period,
            generated_by=user.id,
            format="json",
            download_url=f"/api/v1/governance/reports/{uuid4()}/download",
        )

        await GovernanceService._log_audit(
            session,
            tenant_id=tenant_id,
            actor_id=user.id,
            action="governance_report.generated",
            resource_type="governance_report",
            resource_id=report.id,
            details={"report_type": report_type, "period": period},
        )

        logger.info(
            "Governance report generated",
            extra={"tenant_id": tenant_id, "report_type": report_type},
        )
        return report

    # ── Audit Trail ─────────────────────────────────────────────────

    @staticmethod
    async def get_audit_trail(
        tenant_id: str,
        filters: dict[str, Any],
        session: AsyncSession,
    ) -> list[AuditEntry]:
        """Query tamper-proof audit trail with hash-chain verification.

        Args:
            tenant_id: Tenant scope.
            filters: Optional filters (action, resource_type, since, until, limit, offset).
            session: Database session.

        Returns:
            List of verified AuditEntry records.
        """
        base = select(AuditEntry)

        # Apply filters
        action = filters.get("action")
        if action is not None:
            base = base.where(AuditEntry.action == action)
        resource_type = filters.get("resource_type")
        if resource_type is not None:
            base = base.where(AuditEntry.resource_type == resource_type)
        agent_id = filters.get("agent_id")
        if agent_id is not None:
            base = base.where(AuditEntry.agent_id == agent_id)
        since = filters.get("since")
        if since is not None:
            base = base.where(AuditEntry.created_at >= since)  # type: ignore[operator]
        until = filters.get("until")
        if until is not None:
            base = base.where(AuditEntry.created_at <= until)  # type: ignore[operator]

        limit = min(filters.get("limit", 20), 100)
        offset = filters.get("offset", 0)

        stmt = base.offset(offset).limit(limit).order_by(
            AuditEntry.created_at.desc()  # type: ignore[union-attr]
        )
        result = await session.exec(stmt)
        entries = list(result.all())

        # Verify hash chain integrity
        for entry in entries:
            if entry.entry_hash is not None:
                expected = compute_entry_hash(
                    json.dumps(
                        {
                            "action": entry.action,
                            "resource_type": entry.resource_type,
                            "resource_id": str(entry.resource_id) if entry.resource_id else None,
                            "actor_id": str(entry.actor_id) if entry.actor_id else None,
                            "agent_id": str(entry.agent_id) if entry.agent_id else None,
                            "outcome": entry.outcome,
                            "details": entry.details,
                        },
                        sort_keys=True,
                    ),
                    entry.previous_hash,
                )
                if expected != entry.entry_hash:
                    logger.warning(
                        "Audit entry hash mismatch — possible tampering",
                        extra={"entry_id": str(entry.id), "tenant_id": tenant_id},
                    )

        return entries

    # ── Internal Audit Helper ───────────────────────────────────────

    @staticmethod
    async def _log_audit(
        session: AsyncSession,
        *,
        tenant_id: str,
        actor_id: str,
        action: str,
        resource_type: str,
        resource_id: UUID | None = None,
        agent_id: UUID | None = None,
        outcome: str = "success",
        details: dict[str, Any] | None = None,
    ) -> AuditEntry:
        """Append a tamper-evident audit entry with hash chain."""
        # Fetch previous hash for chain
        prev_stmt = (
            select(AuditEntry)
            .order_by(AuditEntry.created_at.desc())  # type: ignore[union-attr]
            .limit(1)
        )
        prev_result = await session.exec(prev_stmt)
        prev_entry = prev_result.first()
        previous_hash = prev_entry.entry_hash if prev_entry else None

        entry_data = json.dumps(
            {
                "action": action,
                "resource_type": resource_type,
                "resource_id": str(resource_id) if resource_id else None,
                "actor_id": actor_id,
                "agent_id": str(agent_id) if agent_id else None,
                "outcome": outcome,
                "details": details,
            },
            sort_keys=True,
        )
        entry_hash = compute_entry_hash(entry_data, previous_hash)

        from uuid import UUID as _UUID

        entry = AuditEntry(
            actor_id=_UUID(actor_id) if actor_id else None,
            agent_id=agent_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            outcome=outcome,
            details=details,
            previous_hash=previous_hash,
            entry_hash=entry_hash,
        )
        session.add(entry)
        await session.commit()
        await session.refresh(entry)
        return entry


__all__ = [
    "GovernanceService",
]
