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


__all__ = [
    "GovernanceEngine",
]
