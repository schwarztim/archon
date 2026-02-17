"""Unit tests for GovernanceEngine — policy CRUD, compliance checks,
audit trail with hash-chain integrity, and agent registry.

All tests mock the async database session so no live DB is required.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from app.models.governance import (
    AgentRegistryEntry,
    AuditEntry,
    CompliancePolicy,
    ComplianceRecord,
    compute_entry_hash,
)
from app.services.governance import GovernanceEngine

# ── Fixed UUIDs ─────────────────────────────────────────────────────

AGENT_ID = UUID("aa000001-0001-0001-0001-000000000001")
AGENT_ID_2 = UUID("aa000002-0002-0002-0002-000000000002")
POLICY_ID = UUID("bb000001-0001-0001-0001-000000000001")
POLICY_ID_2 = UUID("bb000002-0002-0002-0002-000000000002")
USER_ID = UUID("00000001-0001-0001-0001-000000000001")
RESOURCE_ID = UUID("cc000001-0001-0001-0001-000000000001")
ENTRY_ID = UUID("ee000001-0001-0001-0001-000000000001")
NOW = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)


# ── Factories ───────────────────────────────────────────────────────


def _mock_session() -> AsyncMock:
    """Create a mock AsyncSession with standard ORM method stubs."""
    session = AsyncMock()
    session.add = MagicMock()
    return session


def _exec_result(rows: list[Any]) -> MagicMock:
    """Create a mock result object whose .all() and .first() work."""
    result = MagicMock()
    result.all.return_value = rows
    result.first.return_value = rows[0] if rows else None
    return result


def _policy(
    *,
    pid: UUID = POLICY_ID,
    name: str = "Test Policy",
    framework: str = "SOC2",
    status: str = "active",
    severity: str = "medium",
    rules: dict[str, Any] | None = None,
    enforcement_action: str = "warn",
) -> CompliancePolicy:
    """Build a CompliancePolicy with controllable fields."""
    return CompliancePolicy(
        id=pid,
        name=name,
        framework=framework,
        status=status,
        severity=severity,
        rules=rules if rules is not None else {},
        enforcement_action=enforcement_action,
        created_at=NOW,
        updated_at=NOW,
    )


def _registry_entry(
    *,
    eid: UUID = ENTRY_ID,
    agent_id: UUID = AGENT_ID,
    owner: str = "team-alpha",
    department: str = "engineering",
    approval_status: str = "approved",
    risk_level: str = "low",
    models_used: list[str] | None = None,
    data_accessed: list[str] | None = None,
) -> AgentRegistryEntry:
    """Build an AgentRegistryEntry with controllable fields."""
    return AgentRegistryEntry(
        id=eid,
        agent_id=agent_id,
        owner=owner,
        department=department,
        approval_status=approval_status,
        risk_level=risk_level,
        models_used=models_used if models_used is not None else ["gpt-4o"],
        data_accessed=data_accessed if data_accessed is not None else [],
        extra_metadata={},
        registered_at=NOW,
        updated_at=NOW,
    )


def _audit_entry(
    *,
    action: str = "agent.deploy",
    resource_type: str = "agent",
    outcome: str = "success",
    agent_id: UUID | None = AGENT_ID,
    entry_hash: str | None = "abc123",
    previous_hash: str | None = None,
) -> AuditEntry:
    """Build an AuditEntry with controllable fields."""
    return AuditEntry(
        id=uuid4(),
        actor_id=USER_ID,
        agent_id=agent_id,
        action=action,
        resource_type=resource_type,
        resource_id=RESOURCE_ID,
        outcome=outcome,
        details={"note": "test"},
        previous_hash=previous_hash,
        entry_hash=entry_hash,
        created_at=NOW,
    )


# ═══════════════════════════════════════════════════════════════════
# Policy Management
# ═══════════════════════════════════════════════════════════════════


class TestCreatePolicy:
    """Tests for GovernanceEngine.create_policy."""

    @pytest.mark.asyncio
    async def test_create_policy_adds_and_commits(self) -> None:
        """create_policy should add the policy, commit, and refresh."""
        session = _mock_session()
        policy = _policy()

        result = await GovernanceEngine.create_policy(session, policy)

        session.add.assert_called_once_with(policy)
        session.commit.assert_awaited_once()
        session.refresh.assert_awaited_once_with(policy)
        assert result is policy

    @pytest.mark.asyncio
    async def test_create_policy_preserves_fields(self) -> None:
        """All policy fields should be preserved after creation."""
        session = _mock_session()
        rules = {"required_approval_status": "approved"}
        policy = _policy(name="GDPR Check", framework="GDPR", rules=rules)

        result = await GovernanceEngine.create_policy(session, policy)

        assert result.name == "GDPR Check"
        assert result.framework == "GDPR"
        assert result.rules == rules


class TestListPolicies:
    """Tests for GovernanceEngine.list_policies."""

    @pytest.mark.asyncio
    async def test_list_policies_returns_items_and_count(self) -> None:
        """list_policies returns (list, total_count) tuple."""
        session = _mock_session()
        policies = [_policy(), _policy(pid=POLICY_ID_2, name="Second")]
        # Two exec calls: first for count, second for paginated results
        session.exec = AsyncMock(side_effect=[
            _exec_result(policies),
            _exec_result(policies),
        ])

        items, total = await GovernanceEngine.list_policies(session)

        assert total == 2
        assert len(items) == 2

    @pytest.mark.asyncio
    async def test_list_policies_filters_by_framework(self) -> None:
        """list_policies with framework filter should pass it through."""
        session = _mock_session()
        p = _policy(framework="HIPAA")
        session.exec = AsyncMock(side_effect=[
            _exec_result([p]),
            _exec_result([p]),
        ])

        items, total = await GovernanceEngine.list_policies(
            session, framework="HIPAA"
        )

        assert total == 1
        assert items[0].framework == "HIPAA"

    @pytest.mark.asyncio
    async def test_list_policies_filters_by_status(self) -> None:
        """list_policies with status filter should pass it through."""
        session = _mock_session()
        p = _policy(status="draft")
        session.exec = AsyncMock(side_effect=[
            _exec_result([p]),
            _exec_result([p]),
        ])

        items, total = await GovernanceEngine.list_policies(
            session, status="draft"
        )

        assert total == 1
        assert items[0].status == "draft"

    @pytest.mark.asyncio
    async def test_list_policies_empty(self) -> None:
        """list_policies returns empty list and zero count when no data."""
        session = _mock_session()
        session.exec = AsyncMock(side_effect=[
            _exec_result([]),
            _exec_result([]),
        ])

        items, total = await GovernanceEngine.list_policies(session)

        assert items == []
        assert total == 0

    @pytest.mark.asyncio
    async def test_list_policies_pagination(self) -> None:
        """list_policies respects limit and offset parameters."""
        session = _mock_session()
        all_policies = [_policy(pid=uuid4(), name=f"P{i}") for i in range(5)]
        page = all_policies[2:4]
        session.exec = AsyncMock(side_effect=[
            _exec_result(all_policies),
            _exec_result(page),
        ])

        items, total = await GovernanceEngine.list_policies(
            session, limit=2, offset=2
        )

        assert total == 5
        assert len(items) == 2


# ═══════════════════════════════════════════════════════════════════
# Compliance Checking
# ═══════════════════════════════════════════════════════════════════


class TestCheckCompliance:
    """Tests for GovernanceEngine.check_compliance."""

    @pytest.mark.asyncio
    async def test_compliant_agent(self) -> None:
        """Agent that meets all policy rules is compliant."""
        session = _mock_session()
        policy = _policy(rules={"required_approval_status": "approved"})
        reg = _registry_entry(approval_status="approved")
        session.exec = AsyncMock(side_effect=[
            _exec_result([policy]),   # policies query
            _exec_result([reg]),      # registry query
        ])

        records = await GovernanceEngine.check_compliance(
            session, agent_id=AGENT_ID, policy_id=POLICY_ID
        )

        assert len(records) == 1
        assert records[0].status == "compliant"
        assert records[0].details["policy"] == "Test Policy"
        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_non_compliant_approval_status(self) -> None:
        """Agent with wrong approval status is non_compliant."""
        session = _mock_session()
        policy = _policy(rules={"required_approval_status": "approved"})
        reg = _registry_entry(approval_status="draft")
        session.exec = AsyncMock(side_effect=[
            _exec_result([policy]),
            _exec_result([reg]),
        ])

        records = await GovernanceEngine.check_compliance(
            session, agent_id=AGENT_ID, policy_id=POLICY_ID
        )

        assert len(records) == 1
        assert records[0].status == "non_compliant"
        assert "violations" in records[0].details

    @pytest.mark.asyncio
    async def test_non_compliant_risk_level(self) -> None:
        """Agent with risk level exceeding max is non_compliant."""
        session = _mock_session()
        policy = _policy(rules={"max_risk_level": "low"})
        reg = _registry_entry(risk_level="high")
        session.exec = AsyncMock(side_effect=[
            _exec_result([policy]),
            _exec_result([reg]),
        ])

        records = await GovernanceEngine.check_compliance(
            session, agent_id=AGENT_ID, policy_id=POLICY_ID
        )

        assert records[0].status == "non_compliant"
        violations = records[0].details["violations"]
        assert any("Risk level" in v for v in violations)

    @pytest.mark.asyncio
    async def test_non_compliant_forbidden_data(self) -> None:
        """Agent accessing forbidden data types is non_compliant."""
        session = _mock_session()
        policy = _policy(rules={"forbidden_data_types": ["PII", "PHI"]})
        reg = _registry_entry(data_accessed=["PII", "logs"])
        session.exec = AsyncMock(side_effect=[
            _exec_result([policy]),
            _exec_result([reg]),
        ])

        records = await GovernanceEngine.check_compliance(
            session, agent_id=AGENT_ID, policy_id=POLICY_ID
        )

        assert records[0].status == "non_compliant"
        violations = records[0].details["violations"]
        assert any("PII" in v for v in violations)

    @pytest.mark.asyncio
    async def test_unregistered_agent_is_non_compliant(self) -> None:
        """Agent not in registry is non_compliant."""
        session = _mock_session()
        policy = _policy()
        session.exec = AsyncMock(side_effect=[
            _exec_result([policy]),
            _exec_result([]),         # no registry entry
        ])

        records = await GovernanceEngine.check_compliance(
            session, agent_id=AGENT_ID, policy_id=POLICY_ID
        )

        assert records[0].status == "non_compliant"
        assert "not found" in records[0].details["reason"]

    @pytest.mark.asyncio
    async def test_check_all_active_policies(self) -> None:
        """When no policy_id given, checks all active policies."""
        session = _mock_session()
        p1 = _policy(pid=POLICY_ID, name="P1", status="active")
        p2 = _policy(pid=POLICY_ID_2, name="P2", status="active")
        reg = _registry_entry()
        session.exec = AsyncMock(side_effect=[
            _exec_result([p1, p2]),
            _exec_result([reg]),
        ])

        records = await GovernanceEngine.check_compliance(
            session, agent_id=AGENT_ID
        )

        assert len(records) == 2

    @pytest.mark.asyncio
    async def test_no_active_policies_returns_empty(self) -> None:
        """No matching policies yields empty records list, no commit."""
        session = _mock_session()
        session.exec = AsyncMock(side_effect=[
            _exec_result([]),       # no policies
            _exec_result([]),       # registry lookup still happens
        ])

        records = await GovernanceEngine.check_compliance(
            session, agent_id=AGENT_ID
        )

        assert records == []
        session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_multiple_violations_combined(self) -> None:
        """Multiple rule violations are all reported."""
        session = _mock_session()
        policy = _policy(rules={
            "required_approval_status": "approved",
            "max_risk_level": "low",
            "forbidden_data_types": ["PII"],
        })
        reg = _registry_entry(
            approval_status="draft",
            risk_level="critical",
            data_accessed=["PII"],
        )
        session.exec = AsyncMock(side_effect=[
            _exec_result([policy]),
            _exec_result([reg]),
        ])

        records = await GovernanceEngine.check_compliance(
            session, agent_id=AGENT_ID, policy_id=POLICY_ID
        )

        violations = records[0].details["violations"]
        assert len(violations) == 3


# ═══════════════════════════════════════════════════════════════════
# _evaluate_policy (pure function, no DB)
# ═══════════════════════════════════════════════════════════════════


class TestEvaluatePolicy:
    """Tests for GovernanceEngine._evaluate_policy (synchronous helper)."""

    def test_compliant_no_rules(self) -> None:
        """Empty rules means compliant."""
        policy = _policy(rules={})
        reg = _registry_entry()
        status, details = GovernanceEngine._evaluate_policy(policy, reg)
        assert status == "compliant"

    def test_none_registry_entry(self) -> None:
        """None registry entry yields non_compliant."""
        policy = _policy()
        status, details = GovernanceEngine._evaluate_policy(policy, None)
        assert status == "non_compliant"
        assert "not found" in details["reason"]

    def test_risk_level_equal_to_max_is_compliant(self) -> None:
        """Risk level equal to max is still compliant."""
        policy = _policy(rules={"max_risk_level": "medium"})
        reg = _registry_entry(risk_level="medium")
        status, _ = GovernanceEngine._evaluate_policy(policy, reg)
        assert status == "compliant"

    def test_risk_level_below_max_is_compliant(self) -> None:
        """Risk level below max is compliant."""
        policy = _policy(rules={"max_risk_level": "high"})
        reg = _registry_entry(risk_level="low")
        status, _ = GovernanceEngine._evaluate_policy(policy, reg)
        assert status == "compliant"

    def test_forbidden_data_no_overlap(self) -> None:
        """Agent accessing no forbidden data is compliant."""
        policy = _policy(rules={"forbidden_data_types": ["PII"]})
        reg = _registry_entry(data_accessed=["logs", "metrics"])
        status, _ = GovernanceEngine._evaluate_policy(policy, reg)
        assert status == "compliant"

    def test_details_include_framework(self) -> None:
        """Details dict includes framework info."""
        policy = _policy(framework="GDPR")
        reg = _registry_entry()
        _, details = GovernanceEngine._evaluate_policy(policy, reg)
        assert details["framework"] == "GDPR"


# ═══════════════════════════════════════════════════════════════════
# Audit Logging
# ═══════════════════════════════════════════════════════════════════


class TestLogAuditEvent:
    """Tests for GovernanceEngine.log_audit_event."""

    @pytest.mark.asyncio
    async def test_log_audit_event_creates_entry(self) -> None:
        """log_audit_event should add, commit, and refresh an AuditEntry."""
        session = _mock_session()
        # First exec: query for previous entry (none)
        session.exec = AsyncMock(return_value=_exec_result([]))

        entry = await GovernanceEngine.log_audit_event(
            session,
            action="policy.create",
            resource_type="policy",
            resource_id=POLICY_ID,
            actor_id=USER_ID,
            outcome="success",
            details={"name": "Test"},
        )

        session.add.assert_called_once()
        session.commit.assert_awaited_once()
        session.refresh.assert_awaited_once()
        assert entry.action == "policy.create"
        assert entry.outcome == "success"
        assert entry.previous_hash is None

    @pytest.mark.asyncio
    async def test_log_audit_event_chains_hash(self) -> None:
        """When a previous entry exists, previous_hash is set."""
        session = _mock_session()
        prev = _audit_entry(entry_hash="prev_hash_value")
        session.exec = AsyncMock(return_value=_exec_result([prev]))

        entry = await GovernanceEngine.log_audit_event(
            session,
            action="agent.deploy",
            resource_type="agent",
        )

        assert entry.previous_hash == "prev_hash_value"
        assert entry.entry_hash is not None
        assert entry.entry_hash != "prev_hash_value"

    @pytest.mark.asyncio
    async def test_log_audit_event_computes_valid_hash(self) -> None:
        """entry_hash should match compute_entry_hash for the same data."""
        session = _mock_session()
        session.exec = AsyncMock(return_value=_exec_result([]))

        entry = await GovernanceEngine.log_audit_event(
            session,
            action="test.action",
            resource_type="test",
            outcome="failure",
        )

        # Hash should be a 64-char hex SHA-256
        assert len(entry.entry_hash) == 64
        assert all(c in "0123456789abcdef" for c in entry.entry_hash)

    @pytest.mark.asyncio
    async def test_log_audit_event_with_agent_id(self) -> None:
        """agent_id is stored on the entry."""
        session = _mock_session()
        session.exec = AsyncMock(return_value=_exec_result([]))

        entry = await GovernanceEngine.log_audit_event(
            session,
            action="agent.start",
            resource_type="agent",
            agent_id=AGENT_ID,
        )

        assert entry.agent_id == AGENT_ID


class TestGetAuditTrail:
    """Tests for GovernanceEngine.get_audit_trail."""

    @pytest.mark.asyncio
    async def test_get_audit_trail_returns_items_and_count(self) -> None:
        """get_audit_trail returns (list, total) tuple."""
        session = _mock_session()
        entries = [_audit_entry(), _audit_entry(action="policy.update")]
        session.exec = AsyncMock(side_effect=[
            _exec_result(entries),
            _exec_result(entries),
        ])

        items, total = await GovernanceEngine.get_audit_trail(session)

        assert total == 2
        assert len(items) == 2

    @pytest.mark.asyncio
    async def test_get_audit_trail_filters_by_agent_id(self) -> None:
        """Filter by agent_id returns only matching entries."""
        session = _mock_session()
        e = _audit_entry(agent_id=AGENT_ID)
        session.exec = AsyncMock(side_effect=[
            _exec_result([e]),
            _exec_result([e]),
        ])

        items, total = await GovernanceEngine.get_audit_trail(
            session, agent_id=AGENT_ID
        )

        assert total == 1

    @pytest.mark.asyncio
    async def test_get_audit_trail_filters_by_action(self) -> None:
        """Filter by action returns only matching entries."""
        session = _mock_session()
        e = _audit_entry(action="policy.create")
        session.exec = AsyncMock(side_effect=[
            _exec_result([e]),
            _exec_result([e]),
        ])

        items, total = await GovernanceEngine.get_audit_trail(
            session, action="policy.create"
        )

        assert total == 1
        assert items[0].action == "policy.create"

    @pytest.mark.asyncio
    async def test_get_audit_trail_filters_by_resource_type(self) -> None:
        """Filter by resource_type returns only matching entries."""
        session = _mock_session()
        e = _audit_entry(resource_type="policy")
        session.exec = AsyncMock(side_effect=[
            _exec_result([e]),
            _exec_result([e]),
        ])

        items, total = await GovernanceEngine.get_audit_trail(
            session, resource_type="policy"
        )

        assert total == 1

    @pytest.mark.asyncio
    async def test_get_audit_trail_filters_by_outcome(self) -> None:
        """Filter by outcome returns only matching entries."""
        session = _mock_session()
        e = _audit_entry(outcome="failure")
        session.exec = AsyncMock(side_effect=[
            _exec_result([e]),
            _exec_result([e]),
        ])

        items, total = await GovernanceEngine.get_audit_trail(
            session, outcome="failure"
        )

        assert total == 1

    @pytest.mark.asyncio
    async def test_get_audit_trail_empty(self) -> None:
        """Empty audit trail returns empty list and zero count."""
        session = _mock_session()
        session.exec = AsyncMock(side_effect=[
            _exec_result([]),
            _exec_result([]),
        ])

        items, total = await GovernanceEngine.get_audit_trail(session)

        assert items == []
        assert total == 0

    @pytest.mark.asyncio
    async def test_get_audit_trail_date_filters(self) -> None:
        """since/until filters are accepted without error."""
        session = _mock_session()
        session.exec = AsyncMock(side_effect=[
            _exec_result([]),
            _exec_result([]),
        ])

        items, total = await GovernanceEngine.get_audit_trail(
            session,
            since=NOW - timedelta(days=7),
            until=NOW,
        )

        assert total == 0

    @pytest.mark.asyncio
    async def test_get_audit_trail_pagination(self) -> None:
        """Pagination parameters are respected."""
        session = _mock_session()
        all_entries = [_audit_entry() for _ in range(10)]
        page = all_entries[4:6]
        session.exec = AsyncMock(side_effect=[
            _exec_result(all_entries),
            _exec_result(page),
        ])

        items, total = await GovernanceEngine.get_audit_trail(
            session, limit=2, offset=4
        )

        assert total == 10
        assert len(items) == 2


# ═══════════════════════════════════════════════════════════════════
# Agent Registry
# ═══════════════════════════════════════════════════════════════════


class TestRegisterAgent:
    """Tests for GovernanceEngine.register_agent."""

    @pytest.mark.asyncio
    async def test_register_agent_adds_and_commits(self) -> None:
        """register_agent should add, commit, and refresh the entry."""
        session = _mock_session()
        entry = _registry_entry()

        result = await GovernanceEngine.register_agent(session, entry)

        session.add.assert_called_once_with(entry)
        session.commit.assert_awaited_once()
        session.refresh.assert_awaited_once_with(entry)
        assert result is entry

    @pytest.mark.asyncio
    async def test_register_agent_preserves_fields(self) -> None:
        """All registry fields should be preserved after registration."""
        session = _mock_session()
        entry = _registry_entry(
            owner="team-beta",
            department="security",
            approval_status="review",
            risk_level="high",
            models_used=["claude-3-5-sonnet"],
            data_accessed=["logs"],
        )

        result = await GovernanceEngine.register_agent(session, entry)

        assert result.owner == "team-beta"
        assert result.department == "security"
        assert result.approval_status == "review"
        assert result.risk_level == "high"
        assert result.models_used == ["claude-3-5-sonnet"]
        assert result.data_accessed == ["logs"]


# ═══════════════════════════════════════════════════════════════════
# compute_entry_hash (pure function)
# ═══════════════════════════════════════════════════════════════════


class TestComputeEntryHash:
    """Tests for compute_entry_hash helper."""

    def test_deterministic(self) -> None:
        """Same inputs produce the same hash."""
        h1 = compute_entry_hash("data", "prev")
        h2 = compute_entry_hash("data", "prev")
        assert h1 == h2

    def test_different_data_different_hash(self) -> None:
        """Different data produces different hashes."""
        h1 = compute_entry_hash("data_a", None)
        h2 = compute_entry_hash("data_b", None)
        assert h1 != h2

    def test_previous_hash_affects_result(self) -> None:
        """Including a previous hash changes the output."""
        h1 = compute_entry_hash("data", None)
        h2 = compute_entry_hash("data", "some_prev_hash")
        assert h1 != h2

    def test_returns_hex_sha256(self) -> None:
        """Output is a 64-char lowercase hex string (SHA-256)."""
        h = compute_entry_hash("test", None)
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)
