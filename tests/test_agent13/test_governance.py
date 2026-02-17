"""Tests for Governance Engine — registry, compliance scan, approvals, audit."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.models.governance import (
    AgentRegistryEntry,
    ApprovalRequest,
    AuditEntry,
    CompliancePolicy,
    ComplianceRecord,
    compute_entry_hash,
)


# ── Unit tests for compute_entry_hash ────────────────────────────────


class TestComputeEntryHash:
    """Tests for the tamper-evident hash chain function."""

    def test_produces_hex_string(self) -> None:
        h = compute_entry_hash("test-data")
        assert isinstance(h, str)
        assert len(h) == 64  # SHA-256 hex

    def test_deterministic(self) -> None:
        h1 = compute_entry_hash("same-data", "prev")
        h2 = compute_entry_hash("same-data", "prev")
        assert h1 == h2

    def test_different_data_different_hash(self) -> None:
        h1 = compute_entry_hash("data-a", None)
        h2 = compute_entry_hash("data-b", None)
        assert h1 != h2

    def test_previous_hash_affects_result(self) -> None:
        h1 = compute_entry_hash("data", None)
        h2 = compute_entry_hash("data", "prev-hash")
        assert h1 != h2


# ── Model instantiation tests ───────────────────────────────────────


class TestGovernanceModels:
    """Tests for governance SQLModel / Pydantic models."""

    def test_compliance_policy_defaults(self) -> None:
        policy = CompliancePolicy(
            name="Test Policy",
            framework="SOC2",
        )
        assert policy.name == "Test Policy"
        assert policy.framework == "SOC2"
        assert policy.version == 1
        assert policy.status == "draft"
        assert policy.severity == "medium"
        assert policy.enforcement_action == "warn"
        assert isinstance(policy.rules, dict)
        assert isinstance(policy.id, UUID)

    def test_compliance_record_defaults(self) -> None:
        agent_id = uuid4()
        policy_id = uuid4()
        record = ComplianceRecord(
            agent_id=agent_id,
            policy_id=policy_id,
        )
        assert record.agent_id == agent_id
        assert record.policy_id == policy_id
        assert record.status == "pending"
        assert isinstance(record.details, dict)

    def test_audit_entry_defaults(self) -> None:
        entry = AuditEntry(
            action="test.action",
            resource_type="test_resource",
        )
        assert entry.action == "test.action"
        assert entry.resource_type == "test_resource"
        assert entry.outcome == "success"
        assert entry.previous_hash is None
        assert entry.entry_hash is None

    def test_agent_registry_entry_defaults(self) -> None:
        agent_id = uuid4()
        entry = AgentRegistryEntry(
            agent_id=agent_id,
            owner="alice",
            department="engineering",
        )
        assert entry.agent_id == agent_id
        assert entry.owner == "alice"
        assert entry.department == "engineering"
        assert entry.approval_status == "draft"
        assert entry.risk_level == "low"
        assert isinstance(entry.models_used, list)
        assert isinstance(entry.data_accessed, list)

    def test_approval_request_defaults(self) -> None:
        agent_id = uuid4()
        approval = ApprovalRequest(
            agent_id=agent_id,
            requester_name="bob@example.com",
            agent_name="My Agent",
        )
        assert approval.agent_id == agent_id
        assert approval.status == "pending"
        assert approval.approval_rule == "any_one"
        assert approval.action == "promote_to_production"
        assert isinstance(approval.reviewers, list)
        assert isinstance(approval.decisions, list)
        assert approval.requester_name == "bob@example.com"

    def test_approval_request_custom_rule(self) -> None:
        approval = ApprovalRequest(
            agent_id=uuid4(),
            approval_rule="all",
            reviewers=["reviewer-1", "reviewer-2"],
            comment="Please review for production",
        )
        assert approval.approval_rule == "all"
        assert len(approval.reviewers) == 2
        assert approval.comment == "Please review for production"


# ── GovernanceEngine static method tests ─────────────────────────────


class TestGovernanceEngineEvaluatePolicy:
    """Tests for GovernanceEngine._evaluate_policy static method."""

    def test_no_registry_entry_non_compliant(self) -> None:
        from app.services.governance import GovernanceEngine

        policy = CompliancePolicy(name="P1", framework="SOC2")
        status, details = GovernanceEngine._evaluate_policy(policy, None)
        assert status == "non_compliant"
        assert "not found" in details["reason"]

    def test_compliant_when_no_rules(self) -> None:
        from app.services.governance import GovernanceEngine

        policy = CompliancePolicy(name="P1", framework="SOC2", rules={})
        entry = AgentRegistryEntry(
            agent_id=uuid4(),
            owner="alice",
            department="eng",
        )
        status, details = GovernanceEngine._evaluate_policy(policy, entry)
        assert status == "compliant"

    def test_required_approval_status_violation(self) -> None:
        from app.services.governance import GovernanceEngine

        policy = CompliancePolicy(
            name="P1",
            framework="SOC2",
            rules={"required_approval_status": "published"},
        )
        entry = AgentRegistryEntry(
            agent_id=uuid4(),
            owner="alice",
            department="eng",
            approval_status="draft",
        )
        status, details = GovernanceEngine._evaluate_policy(policy, entry)
        assert status == "non_compliant"
        assert any("Approval status" in v for v in details["violations"])

    def test_max_risk_level_violation(self) -> None:
        from app.services.governance import GovernanceEngine

        policy = CompliancePolicy(
            name="P1",
            framework="SOC2",
            rules={"max_risk_level": "medium"},
        )
        entry = AgentRegistryEntry(
            agent_id=uuid4(),
            owner="alice",
            department="eng",
            risk_level="critical",
        )
        status, details = GovernanceEngine._evaluate_policy(policy, entry)
        assert status == "non_compliant"
        assert any("Risk level" in v for v in details["violations"])

    def test_forbidden_data_types_violation(self) -> None:
        from app.services.governance import GovernanceEngine

        policy = CompliancePolicy(
            name="P1",
            framework="HIPAA",
            rules={"forbidden_data_types": ["phi", "pii"]},
        )
        entry = AgentRegistryEntry(
            agent_id=uuid4(),
            owner="alice",
            department="eng",
            data_accessed=["phi", "logs"],
        )
        status, details = GovernanceEngine._evaluate_policy(policy, entry)
        assert status == "non_compliant"
        assert any("phi" in v for v in details["violations"])

    def test_max_risk_level_pass(self) -> None:
        from app.services.governance import GovernanceEngine

        policy = CompliancePolicy(
            name="P1",
            framework="SOC2",
            rules={"max_risk_level": "high"},
        )
        entry = AgentRegistryEntry(
            agent_id=uuid4(),
            owner="alice",
            department="eng",
            risk_level="medium",
        )
        status, _details = GovernanceEngine._evaluate_policy(policy, entry)
        assert status == "compliant"


# ── Route schema tests ───────────────────────────────────────────────


class TestRouteSchemas:
    """Tests for request/response Pydantic schemas used in governance routes."""

    def test_policy_create_schema(self) -> None:
        from app.routes.governance import PolicyCreate

        body = PolicyCreate(
            name="Test",
            framework="SOC2",
            rules={"key": "value"},
        )
        assert body.name == "Test"
        assert body.framework == "SOC2"
        assert body.severity == "medium"
        assert body.enforcement_action == "warn"

    def test_policy_update_schema(self) -> None:
        from app.routes.governance import PolicyUpdate

        body = PolicyUpdate(name="Updated Name")
        data = body.model_dump(exclude_unset=True)
        assert data == {"name": "Updated Name"}

    def test_approval_create_schema(self) -> None:
        from app.routes.governance import ApprovalCreate

        body = ApprovalCreate(
            agent_id=uuid4(),
            agent_name="My Agent",
            approval_rule="majority",
            reviewers=["alice", "bob"],
        )
        assert body.approval_rule == "majority"
        assert len(body.reviewers) == 2
        assert body.action == "promote_to_production"

    def test_approval_decision_schema(self) -> None:
        from app.routes.governance import ApprovalDecision

        body = ApprovalDecision(comment="Looks good")
        assert body.comment == "Looks good"

    def test_approval_decision_default(self) -> None:
        from app.routes.governance import ApprovalDecision

        body = ApprovalDecision()
        assert body.comment == ""

    def test_agent_registry_create_schema(self) -> None:
        from app.routes.governance import AgentRegistryCreate

        body = AgentRegistryCreate(
            agent_id=uuid4(),
            owner="alice",
            department="engineering",
        )
        assert body.risk_level == "low"
        assert body.approval_status == "draft"

    def test_compliance_check_request_schema(self) -> None:
        from app.routes.governance import ComplianceCheckRequest

        agent_id = uuid4()
        body = ComplianceCheckRequest(agent_id=agent_id)
        assert body.agent_id == agent_id
        assert body.policy_id is None


class TestMetaHelper:
    """Tests for the _meta envelope helper."""

    def test_meta_has_required_fields(self) -> None:
        from app.routes.governance import _meta

        m = _meta()
        assert "request_id" in m
        assert "timestamp" in m

    def test_meta_custom_request_id(self) -> None:
        from app.routes.governance import _meta

        m = _meta(request_id="custom-id")
        assert m["request_id"] == "custom-id"

    def test_meta_extra_fields(self) -> None:
        from app.routes.governance import _meta

        m = _meta(pagination={"total": 10})
        assert m["pagination"]["total"] == 10
