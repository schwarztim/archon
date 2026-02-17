"""Governance engine for Archon — policy management, compliance, audit, and agent registry."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.governance import (
    AgentRegistryEntry,
    ApprovalRequest,
    AuditEntry,
    CompliancePolicy,
    ComplianceRecord,
    compute_entry_hash,
)


def _utcnow() -> datetime:
    """Return timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


class GovernanceEngine:
    """Manages governance policies, compliance checks, audit trails, and agent registry.

    All methods are async statics that accept an ``AsyncSession``,
    following the same pattern as ``RoutingEngine`` and ``ModelRegistry``.
    """

    # ── Policy Management ───────────────────────────────────────────

    @staticmethod
    async def create_policy(
        session: AsyncSession,
        policy: CompliancePolicy,
    ) -> CompliancePolicy:
        """Create a new governance policy."""
        session.add(policy)
        await session.commit()
        await session.refresh(policy)
        return policy

    @staticmethod
    async def get_policy(
        session: AsyncSession,
        policy_id: UUID,
    ) -> CompliancePolicy | None:
        """Return a single policy by ID."""
        return await session.get(CompliancePolicy, policy_id)

    @staticmethod
    async def list_policies(
        session: AsyncSession,
        *,
        framework: str | None = None,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[CompliancePolicy], int]:
        """Return paginated policies with optional filters and total count."""
        base = select(CompliancePolicy)
        if framework is not None:
            base = base.where(CompliancePolicy.framework == framework)
        if status is not None:
            base = base.where(CompliancePolicy.status == status)

        count_result = await session.exec(base)
        total = len(count_result.all())

        stmt = base.offset(offset).limit(limit).order_by(
            CompliancePolicy.created_at.desc()  # type: ignore[union-attr]
        )
        result = await session.exec(stmt)
        return list(result.all()), total

    @staticmethod
    async def update_policy(
        session: AsyncSession,
        policy_id: UUID,
        data: dict[str, Any],
    ) -> CompliancePolicy | None:
        """Partial-update a policy. Returns None if not found."""
        policy = await session.get(CompliancePolicy, policy_id)
        if policy is None:
            return None
        for key, value in data.items():
            if hasattr(policy, key):
                setattr(policy, key, value)
        policy.updated_at = _utcnow()
        session.add(policy)
        await session.commit()
        await session.refresh(policy)
        return policy

    @staticmethod
    async def delete_policy(session: AsyncSession, policy_id: UUID) -> bool:
        """Delete a policy. Returns True if deleted."""
        policy = await session.get(CompliancePolicy, policy_id)
        if policy is None:
            return False
        await session.delete(policy)
        await session.commit()
        return True

    # ── Compliance Checking ─────────────────────────────────────────

    @staticmethod
    async def check_compliance(
        session: AsyncSession,
        *,
        agent_id: UUID,
        policy_id: UUID | None = None,
    ) -> list[ComplianceRecord]:
        """Check agent compliance against one or all active policies.

        Returns a list of ``ComplianceRecord`` objects with pass/fail status.
        """
        if policy_id is not None:
            policies_stmt = select(CompliancePolicy).where(
                CompliancePolicy.id == policy_id
            )
        else:
            policies_stmt = select(CompliancePolicy).where(
                CompliancePolicy.status == "active"
            )

        result = await session.exec(policies_stmt)
        policies = list(result.all())

        # Look up the agent registry entry for rule evaluation
        reg_stmt = select(AgentRegistryEntry).where(
            AgentRegistryEntry.agent_id == agent_id
        )
        reg_result = await session.exec(reg_stmt)
        registry_entry = reg_result.first()

        records: list[ComplianceRecord] = []
        for policy in policies:
            status, details = GovernanceEngine._evaluate_policy(
                policy, registry_entry
            )
            record = ComplianceRecord(
                agent_id=agent_id,
                policy_id=policy.id,
                status=status,
                details=details,
                checked_at=_utcnow(),
            )
            session.add(record)
            records.append(record)

        if records:
            await session.commit()
            for r in records:
                await session.refresh(r)

        return records

    @staticmethod
    def _evaluate_policy(
        policy: CompliancePolicy,
        registry_entry: AgentRegistryEntry | None,
    ) -> tuple[str, dict[str, Any]]:
        """Evaluate a single policy against an agent's registry data.

        Returns (status, details) tuple.
        """
        if registry_entry is None:
            return "non_compliant", {
                "reason": "Agent not found in governance registry",
                "policy": policy.name,
            }

        violations: list[str] = []
        rules = policy.rules or {}

        # Check required approval status
        required_status = rules.get("required_approval_status")
        if required_status and registry_entry.approval_status != required_status:
            violations.append(
                f"Approval status '{registry_entry.approval_status}' "
                f"does not meet required '{required_status}'"
            )

        # Check maximum risk level
        risk_hierarchy = {"low": 0, "medium": 1, "high": 2, "critical": 3}
        max_risk = rules.get("max_risk_level")
        if max_risk:
            entry_rank = risk_hierarchy.get(registry_entry.risk_level, 0)
            max_rank = risk_hierarchy.get(max_risk, 3)
            if entry_rank > max_rank:
                violations.append(
                    f"Risk level '{registry_entry.risk_level}' exceeds maximum '{max_risk}'"
                )

        # Check required data classifications
        forbidden_data = rules.get("forbidden_data_types", [])
        for data_type in registry_entry.data_accessed:
            if data_type in forbidden_data:
                violations.append(f"Accesses forbidden data type: {data_type}")

        if violations:
            return "non_compliant", {
                "violations": violations,
                "policy": policy.name,
                "framework": policy.framework,
            }

        return "compliant", {
            "policy": policy.name,
            "framework": policy.framework,
        }

    # ── Audit Logging ───────────────────────────────────────────────

    @staticmethod
    async def log_audit_event(
        session: AsyncSession,
        *,
        action: str,
        resource_type: str,
        resource_id: UUID | None = None,
        actor_id: UUID | None = None,
        agent_id: UUID | None = None,
        outcome: str = "success",
        details: dict[str, Any] | None = None,
    ) -> AuditEntry:
        """Append a tamper-evident entry to the governance audit trail."""
        # Get previous hash for chain integrity
        prev_stmt = (
            select(AuditEntry)
            .order_by(AuditEntry.created_at.desc())  # type: ignore[union-attr]
            .limit(1)
        )
        prev_result = await session.exec(prev_stmt)
        prev_entry = prev_result.first()
        previous_hash = prev_entry.entry_hash if prev_entry else None

        # Compute hash for this entry
        entry_data = json.dumps(
            {
                "action": action,
                "resource_type": resource_type,
                "resource_id": str(resource_id) if resource_id else None,
                "actor_id": str(actor_id) if actor_id else None,
                "agent_id": str(agent_id) if agent_id else None,
                "outcome": outcome,
                "details": details,
            },
            sort_keys=True,
        )
        entry_hash = compute_entry_hash(entry_data, previous_hash)

        entry = AuditEntry(
            actor_id=actor_id,
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

    @staticmethod
    async def get_audit_trail(
        session: AsyncSession,
        *,
        agent_id: UUID | None = None,
        action: str | None = None,
        resource_type: str | None = None,
        outcome: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[AuditEntry], int]:
        """Return paginated audit entries with optional filters and total count."""
        base = select(AuditEntry)
        if agent_id is not None:
            base = base.where(AuditEntry.agent_id == agent_id)
        if action is not None:
            base = base.where(AuditEntry.action == action)
        if resource_type is not None:
            base = base.where(AuditEntry.resource_type == resource_type)
        if outcome is not None:
            base = base.where(AuditEntry.outcome == outcome)
        if since is not None:
            base = base.where(AuditEntry.created_at >= since)  # type: ignore[operator]
        if until is not None:
            base = base.where(AuditEntry.created_at <= until)  # type: ignore[operator]

        count_result = await session.exec(base)
        total = len(count_result.all())

        stmt = base.offset(offset).limit(limit).order_by(
            AuditEntry.created_at.desc()  # type: ignore[union-attr]
        )
        result = await session.exec(stmt)
        return list(result.all()), total

    # ── Agent Registry ──────────────────────────────────────────────

    @staticmethod
    async def register_agent(
        session: AsyncSession,
        entry: AgentRegistryEntry,
    ) -> AgentRegistryEntry:
        """Register an agent in the governance registry."""
        session.add(entry)
        await session.commit()
        await session.refresh(entry)
        return entry

    @staticmethod
    async def get_agent_registration(
        session: AsyncSession,
        agent_id: UUID,
    ) -> AgentRegistryEntry | None:
        """Look up an agent's governance registry entry by agent_id."""
        stmt = select(AgentRegistryEntry).where(
            AgentRegistryEntry.agent_id == agent_id
        )
        result = await session.exec(stmt)
        return result.first()

    @staticmethod
    async def list_registered_agents(
        session: AsyncSession,
        *,
        department: str | None = None,
        approval_status: str | None = None,
        risk_level: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[AgentRegistryEntry], int]:
        """Return paginated agent registry entries with optional filters."""
        base = select(AgentRegistryEntry)
        if department is not None:
            base = base.where(AgentRegistryEntry.department == department)
        if approval_status is not None:
            base = base.where(AgentRegistryEntry.approval_status == approval_status)
        if risk_level is not None:
            base = base.where(AgentRegistryEntry.risk_level == risk_level)

        count_result = await session.exec(base)
        total = len(count_result.all())

        stmt = base.offset(offset).limit(limit).order_by(
            AgentRegistryEntry.registered_at.desc()  # type: ignore[union-attr]
        )
        result = await session.exec(stmt)
        return list(result.all()), total

    @staticmethod
    async def update_agent_registration(
        session: AsyncSession,
        agent_id: UUID,
        data: dict[str, Any],
    ) -> AgentRegistryEntry | None:
        """Partial-update an agent's governance registry entry."""
        stmt = select(AgentRegistryEntry).where(
            AgentRegistryEntry.agent_id == agent_id
        )
        result = await session.exec(stmt)
        entry = result.first()
        if entry is None:
            return None
        for key, value in data.items():
            if hasattr(entry, key):
                setattr(entry, key, value)
        entry.updated_at = _utcnow()
        session.add(entry)
        await session.commit()
        await session.refresh(entry)
        return entry

    # ── Registry Detail with Compliance History ─────────────────────

    @staticmethod
    async def get_agent_detail(
        session: AsyncSession,
        agent_id: UUID,
    ) -> dict[str, Any] | None:
        """Return agent registry entry with compliance scan history and risk score."""
        stmt = select(AgentRegistryEntry).where(
            AgentRegistryEntry.agent_id == agent_id
        )
        result = await session.exec(stmt)
        entry = result.first()
        if entry is None:
            return None

        # Fetch compliance history
        history_stmt = (
            select(ComplianceRecord)
            .where(ComplianceRecord.agent_id == agent_id)
            .order_by(ComplianceRecord.checked_at.desc())  # type: ignore[union-attr]
            .limit(50)
        )
        history_result = await session.exec(history_stmt)
        records = list(history_result.all())

        # Compute compliance score
        total = len(records)
        passed = sum(1 for r in records if r.status == "compliant")
        compliance_score = round((passed / total) * 100, 1) if total > 0 else 0.0

        # Compute risk score
        risk_scores = {"low": 20, "medium": 50, "high": 75, "critical": 95}
        risk_score = risk_scores.get(entry.risk_level, 50)

        # Determine compliance status
        if total == 0:
            compliance_status = "unknown"
        elif compliance_score >= 80:
            compliance_status = "compliant"
        elif compliance_score >= 50:
            compliance_status = "at_risk"
        else:
            compliance_status = "non_compliant"

        return {
            "registry": entry.model_dump(mode="json"),
            "compliance_history": [r.model_dump(mode="json") for r in records],
            "compliance_score": compliance_score,
            "compliance_status": compliance_status,
            "risk_score": risk_score,
            "total_scans": total,
            "passed_scans": passed,
        }

    # ── Compliance Scan (for single agent) ──────────────────────────

    @staticmethod
    async def scan_agent(
        session: AsyncSession,
        agent_id: UUID,
    ) -> dict[str, Any]:
        """Run a full compliance scan for an agent against all active policies."""
        records = await GovernanceEngine.check_compliance(
            session, agent_id=agent_id
        )

        total = len(records)
        passed = sum(1 for r in records if r.status == "compliant")
        compliance_score = round((passed / total) * 100, 1) if total > 0 else 0.0

        return {
            "agent_id": str(agent_id),
            "records": [r.model_dump(mode="json") for r in records],
            "compliance_score": compliance_score,
            "total_policies": total,
            "passed": passed,
            "failed": total - passed,
            "scanned_at": _utcnow().isoformat(),
        }

    # ── Approval Request CRUD ───────────────────────────────────────

    @staticmethod
    async def create_approval(
        session: AsyncSession,
        approval: ApprovalRequest,
    ) -> ApprovalRequest:
        """Create a new approval request."""
        session.add(approval)
        await session.commit()
        await session.refresh(approval)
        return approval

    @staticmethod
    async def list_approvals(
        session: AsyncSession,
        *,
        status: str | None = None,
        agent_id: UUID | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[ApprovalRequest], int]:
        """Return paginated approval requests with optional filters."""
        base = select(ApprovalRequest)
        if status is not None:
            base = base.where(ApprovalRequest.status == status)
        if agent_id is not None:
            base = base.where(ApprovalRequest.agent_id == agent_id)

        count_result = await session.exec(base)
        total = len(count_result.all())

        stmt = base.offset(offset).limit(limit).order_by(
            ApprovalRequest.created_at.desc()  # type: ignore[union-attr]
        )
        result = await session.exec(stmt)
        return list(result.all()), total

    @staticmethod
    async def get_approval(
        session: AsyncSession,
        approval_id: UUID,
    ) -> ApprovalRequest | None:
        """Get a single approval request by ID."""
        return await session.get(ApprovalRequest, approval_id)

    @staticmethod
    async def approve_request(
        session: AsyncSession,
        approval_id: UUID,
        reviewer: str,
        comment: str = "",
    ) -> ApprovalRequest | None:
        """Approve an approval request."""
        approval = await session.get(ApprovalRequest, approval_id)
        if approval is None:
            return None

        decision = {
            "reviewer": reviewer,
            "decision": "approved",
            "comment": comment,
            "decided_at": _utcnow().isoformat(),
        }
        decisions = list(approval.decisions or [])
        decisions.append(decision)
        approval.decisions = decisions

        # Check approval rule
        rule = approval.approval_rule
        reviewers_count = len(approval.reviewers) if approval.reviewers else 1
        approvals_count = sum(1 for d in decisions if d.get("decision") == "approved")

        if rule == "any_one" and approvals_count >= 1:
            approval.status = "approved"
        elif rule == "all" and approvals_count >= reviewers_count:
            approval.status = "approved"
        elif rule == "majority" and approvals_count > reviewers_count / 2:
            approval.status = "approved"

        approval.updated_at = _utcnow()
        session.add(approval)
        await session.commit()
        await session.refresh(approval)
        return approval

    @staticmethod
    async def reject_request(
        session: AsyncSession,
        approval_id: UUID,
        reviewer: str,
        comment: str = "",
    ) -> ApprovalRequest | None:
        """Reject an approval request."""
        approval = await session.get(ApprovalRequest, approval_id)
        if approval is None:
            return None

        decision = {
            "reviewer": reviewer,
            "decision": "rejected",
            "comment": comment,
            "decided_at": _utcnow().isoformat(),
        }
        decisions = list(approval.decisions or [])
        decisions.append(decision)
        approval.decisions = decisions
        approval.status = "rejected"
        approval.updated_at = _utcnow()

        session.add(approval)
        await session.commit()
        await session.refresh(approval)
        return approval


__all__ = [
    "GovernanceEngine",
]
