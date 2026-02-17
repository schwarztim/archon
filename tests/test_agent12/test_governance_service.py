"""Tests for GovernanceService — access reviews, privilege elevation, risk scoring,
compliance status, approval workflows, and OPA policy management."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.interfaces.models.enterprise import AuthenticatedUser
from app.models.governance import (
    AccessReview,
    AgentRegistryEntry,
    ApprovalWorkflow,
    CompliancePolicy,
    ComplianceRecord,
    ComplianceStatus,
    ElevationRequest,
    GovernanceReport,
    OPAPolicy,
    RiskAssessment,
)
from app.services.governance_service import GovernanceService


# ── Fixtures ────────────────────────────────────────────────────────

TENANT_ID = "tenant-gov-test"


def _admin_user(**overrides: Any) -> AuthenticatedUser:
    defaults = dict(
        id=str(uuid4()),
        email="admin@example.com",
        tenant_id=TENANT_ID,
        roles=["admin"],
        permissions=[],
    )
    defaults.update(overrides)
    return AuthenticatedUser(**defaults)


def _mock_session() -> AsyncMock:
    """Return a mock AsyncSession with typical exec/commit/refresh stubs."""
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    # Default: no previous audit entry (for _log_audit hash chain)
    # Use MagicMock (not AsyncMock) so .first()/.all() return plain values
    result_mock = MagicMock()
    result_mock.first.return_value = None
    result_mock.all.return_value = []
    session.exec = AsyncMock(return_value=result_mock)
    return session


# ── create_access_review ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_access_review_returns_review() -> None:
    """Creates an AccessReview with pending status."""
    session = _mock_session()
    user = _admin_user()
    review = await GovernanceService.create_access_review(
        TENANT_ID, user, {"review_cycle": "quarterly", "reviewee_id": "user-42"}, session,
    )
    assert isinstance(review, AccessReview)
    assert review.tenant_id == TENANT_ID
    assert review.status == "pending"
    assert review.review_cycle == "quarterly"


@pytest.mark.asyncio
async def test_create_access_review_defaults_reviewer_to_user() -> None:
    """If no reviewer_id in config, defaults to calling user."""
    session = _mock_session()
    user = _admin_user()
    review = await GovernanceService.create_access_review(TENANT_ID, user, {}, session)
    assert review.reviewer_id == user.id


@pytest.mark.asyncio
async def test_create_access_review_audit_logged() -> None:
    """Creating a review produces an audit entry via session.add + commit."""
    session = _mock_session()
    await GovernanceService.create_access_review(TENANT_ID, _admin_user(), {}, session)
    session.add.assert_called()
    session.commit.assert_awaited()


# ── process_review_decision ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_process_review_decision_marks_completed() -> None:
    """Processing decisions sets status to completed with decisions attached."""
    session = _mock_session()
    user = _admin_user()
    review_id = uuid4()
    decisions = [
        {"user_id": "u1", "resource": "agent-x", "decision": "approve"},
        {"user_id": "u2", "resource": "agent-y", "decision": "revoke", "notes": "expired"},
    ]
    review = await GovernanceService.process_review_decision(
        TENANT_ID, user, review_id, decisions, session,
    )
    assert review.status == "completed"
    assert len(review.decisions) == 2
    assert review.decisions[0].decision == "approve"
    assert review.completed_at is not None


# ── privilege_elevation (JIT) ───────────────────────────────────────


@pytest.mark.asyncio
async def test_privilege_elevation_basic() -> None:
    """Requesting elevation creates an ElevationRequest with pending status."""
    session = _mock_session()
    user = _admin_user()
    elevation = await GovernanceService.request_privilege_elevation(
        TENANT_ID, user, "admin", "Emergency incident response", 4, session,
    )
    assert isinstance(elevation, ElevationRequest)
    assert elevation.status == "pending"
    assert elevation.requested_role == "admin"
    assert elevation.duration_hours == 4
    assert elevation.expires_at is not None


@pytest.mark.asyncio
async def test_privilege_elevation_clamps_duration() -> None:
    """Duration is clamped to [1, 72] hours."""
    session = _mock_session()
    user = _admin_user()
    short = await GovernanceService.request_privilege_elevation(
        TENANT_ID, user, "admin", "reason", 0, session,
    )
    assert short.duration_hours == 1

    long = await GovernanceService.request_privilege_elevation(
        TENANT_ID, user, "admin", "reason", 999, session,
    )
    assert long.duration_hours == 72


# ── risk_score computation ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_risk_score_unregistered_agent() -> None:
    """Unregistered agent gets max registration risk factor (score 100)."""
    session = _mock_session()
    assessment = await GovernanceService.compute_risk_score(TENANT_ID, uuid4(), session)
    assert isinstance(assessment, RiskAssessment)
    assert assessment.overall_score > 0
    assert any(f.name == "registration" for f in assessment.factors)
    assert "Register agent" in assessment.recommendations[0]


@pytest.mark.asyncio
async def test_risk_score_registered_low_risk() -> None:
    """Registered agent with low risk attributes scores lower."""
    session = _mock_session()
    registry = AgentRegistryEntry(
        agent_id=uuid4(),
        owner="team",
        department="eng",
        approval_status="published",
        models_used=["gpt-4"],
        data_accessed=[],
        risk_level="low",
    )
    result_mock = MagicMock()
    result_mock.first.return_value = registry

    call_count = 0

    async def _exec_side_effect(stmt: Any) -> Any:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return result_mock
        audit_mock = MagicMock()
        audit_mock.first.return_value = None
        return audit_mock

    session.exec = AsyncMock(side_effect=_exec_side_effect)

    assessment = await GovernanceService.compute_risk_score(TENANT_ID, registry.agent_id, session)
    assert assessment.overall_score < 50
    assert assessment.risk_level in ("low", "medium")


@pytest.mark.asyncio
async def test_risk_score_high_sensitivity_data() -> None:
    """Agent accessing PII/PHI/PCI scores higher on data_sensitivity factor."""
    session = _mock_session()
    registry = AgentRegistryEntry(
        agent_id=uuid4(),
        owner="team",
        department="eng",
        approval_status="draft",
        models_used=["gpt-4", "claude-3", "gemini"],
        data_accessed=["pii", "phi", "pci", "financial"],
        risk_level="high",
    )
    result_mock = MagicMock()
    result_mock.first.return_value = registry
    call_count = 0

    async def _exec_side_effect(stmt: Any) -> Any:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return result_mock
        audit_mock = MagicMock()
        audit_mock.first.return_value = None
        return audit_mock

    session.exec = AsyncMock(side_effect=_exec_side_effect)

    assessment = await GovernanceService.compute_risk_score(TENANT_ID, registry.agent_id, session)
    assert assessment.overall_score >= 50
    assert assessment.risk_level in ("high", "critical")


# ── compliance_status ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_compliance_status_no_policies() -> None:
    """No policies for a framework yields 'unknown' overall status."""
    session = _mock_session()
    status = await GovernanceService.get_compliance_status(TENANT_ID, "SOC2", session)
    assert isinstance(status, ComplianceStatus)
    assert status.framework == "SOC2"
    assert status.overall_status == "unknown"


# ── approval_workflow ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_approval_workflow() -> None:
    """Creates a multi-stage approval workflow with default stages."""
    session = _mock_session()
    user = _admin_user()
    agent_id = uuid4()
    wf = await GovernanceService.create_approval_workflow(
        TENANT_ID, user, agent_id, "deployment", session,
    )
    assert isinstance(wf, ApprovalWorkflow)
    assert wf.status == "pending"
    assert wf.workflow_type == "deployment"
    assert len(wf.stages) == 2
    assert wf.stages[0].approver_role == "operator"
    assert wf.stages[1].approver_role == "admin"
    assert wf.current_stage == 1


@pytest.mark.asyncio
async def test_approval_workflow_audit() -> None:
    """Approval workflow creation is audit-logged."""
    session = _mock_session()
    await GovernanceService.create_approval_workflow(
        TENANT_ID, _admin_user(), uuid4(), "data_access", session,
    )
    session.add.assert_called()
    session.commit.assert_awaited()


# ── OPA policy management ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_manage_opa_policy_create() -> None:
    """Creating an OPA policy returns it with tenant scope."""
    session = _mock_session()
    user = _admin_user()
    policy = await GovernanceService.manage_opa_policy(
        TENANT_ID, user, "create",
        {"name": "deny-pii", "rego_content": "package deny\ndefault allow = false"},
        session,
    )
    assert isinstance(policy, OPAPolicy)
    assert policy.tenant_id == TENANT_ID
    assert policy.name == "deny-pii"
    assert policy.active is True


@pytest.mark.asyncio
async def test_manage_opa_policy_lint_fails_empty() -> None:
    """Empty rego content raises ValueError during lint."""
    session = _mock_session()
    user = _admin_user()
    with pytest.raises(ValueError, match="empty"):
        await GovernanceService.manage_opa_policy(
            TENANT_ID, user, "create",
            {"name": "bad", "rego_content": "   "},
            session,
        )


@pytest.mark.asyncio
async def test_manage_opa_policy_lint_fails_no_package() -> None:
    """Rego without 'package' declaration raises ValueError."""
    session = _mock_session()
    user = _admin_user()
    with pytest.raises(ValueError, match="package"):
        await GovernanceService.manage_opa_policy(
            TENANT_ID, user, "create",
            {"name": "bad", "rego_content": "default allow = false"},
            session,
        )


# ── Governance report ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_generate_governance_report() -> None:
    """Generates a report with correct metadata."""
    session = _mock_session()
    user = _admin_user()
    report = await GovernanceService.generate_governance_report(
        TENANT_ID, user, "compliance_summary", "Q1-2026", session,
    )
    assert isinstance(report, GovernanceReport)
    assert report.tenant_id == TENANT_ID
    assert report.report_type == "compliance_summary"
    assert report.period == "Q1-2026"
    assert "/download" in report.download_url
