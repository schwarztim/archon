"""Unit tests for SentinelScanner — discovery scans, service tracking,
risk classification, and posture report generation.

All tests mock the async database session so no live DB is required.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from app.models.sentinelscan import (
    DiscoveredService,
    DiscoveryScan,
    RiskClassification,
)
from app.services.sentinelscan import SentinelScanner

# ── Fixed UUIDs (valid hex only) ────────────────────────────────────

SCAN_ID = UUID("aa000001-0001-0001-0001-000000000001")
SCAN_ID_2 = UUID("aa000002-0002-0002-0002-000000000002")
SERVICE_ID = UUID("bb000001-0001-0001-0001-000000000001")
SERVICE_ID_2 = UUID("bb000002-0002-0002-0002-000000000002")
SERVICE_ID_3 = UUID("bb000003-0003-0003-0003-000000000003")
CLASSIFICATION_ID = UUID("cc000001-0001-0001-0001-000000000001")
USER_ID = UUID("dd000001-0001-0001-0001-000000000001")

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


def _scan(
    *,
    scan_id: UUID = SCAN_ID,
    name: str = "Test Scan",
    scan_type: str = "network",
    status: str = "pending",
    services_found: int = 0,
) -> DiscoveryScan:
    """Build a DiscoveryScan with controllable fields."""
    return DiscoveryScan(
        id=scan_id,
        name=name,
        scan_type=scan_type,
        status=status,
        config={},
        results_summary={},
        services_found=services_found,
        started_at=None,
        completed_at=None,
        error_message=None,
        initiated_by=USER_ID,
        created_at=NOW,
        updated_at=NOW,
    )


def _service(
    *,
    service_id: UUID = SERVICE_ID,
    scan_id: UUID = SCAN_ID,
    service_name: str = "ChatGPT Enterprise",
    service_type: str = "llm",
    provider: str = "openai",
    detection_source: str = "sso_log",
    department: str | None = "engineering",
    owner: str | None = "alice@example.com",
    user_count: int = 10,
    data_sensitivity: str = "internal",
    is_sanctioned: bool = False,
) -> DiscoveredService:
    """Build a DiscoveredService with controllable fields."""
    return DiscoveredService(
        id=service_id,
        scan_id=scan_id,
        service_name=service_name,
        service_type=service_type,
        provider=provider,
        detection_source=detection_source,
        department=department,
        owner=owner,
        user_count=user_count,
        data_sensitivity=data_sensitivity,
        is_sanctioned=is_sanctioned,
        first_seen=NOW,
        last_seen=NOW,
        extra_metadata={},
        created_at=NOW,
        updated_at=NOW,
    )


def _classification(
    *,
    classification_id: UUID = CLASSIFICATION_ID,
    service_id: UUID = SERVICE_ID,
    risk_tier: str = "medium",
    risk_score: int = 55,
    policy_violations: list[str] | None = None,
) -> RiskClassification:
    """Build a RiskClassification with controllable fields."""
    return RiskClassification(
        id=classification_id,
        service_id=service_id,
        risk_tier=risk_tier,
        risk_score=risk_score,
        factors={},
        data_sensitivity_score=15,
        blast_radius_score=10,
        compliance_score=15,
        model_capability_score=15,
        policy_violations=policy_violations if policy_violations is not None else [],
        recommended_actions=[],
        classified_at=NOW,
        updated_at=NOW,
    )


# ═══════════════════════════════════════════════════════════════════
# Discovery Scan Management
# ═══════════════════════════════════════════════════════════════════


class TestCreateScan:
    """Tests for SentinelScanner.create_scan."""

    @pytest.mark.asyncio
    async def test_create_scan_adds_and_commits(self) -> None:
        """create_scan should add the scan, commit, and refresh."""
        session = _mock_session()
        scan = _scan()

        result = await SentinelScanner.create_scan(session, scan)

        session.add.assert_called_once_with(scan)
        session.commit.assert_awaited_once()
        session.refresh.assert_awaited_once_with(scan)
        assert result is scan

    @pytest.mark.asyncio
    async def test_create_scan_preserves_fields(self) -> None:
        """All scan fields should be preserved after creation."""
        session = _mock_session()
        scan = _scan(name="SSO Sweep", scan_type="sso", status="pending")

        result = await SentinelScanner.create_scan(session, scan)

        assert result.name == "SSO Sweep"
        assert result.scan_type == "sso"
        assert result.status == "pending"
        assert result.initiated_by == USER_ID


# ═══════════════════════════════════════════════════════════════════
# Run Scan
# ═══════════════════════════════════════════════════════════════════


class TestRunScan:
    """Tests for SentinelScanner.run_scan."""

    @pytest.mark.asyncio
    async def test_run_scan_sets_running_status(self) -> None:
        """run_scan should set status to 'running' and set started_at."""
        session = _mock_session()
        scan = _scan(status="pending")
        session.get = AsyncMock(return_value=scan)

        result = await SentinelScanner.run_scan(session, SCAN_ID)

        assert result is not None
        assert result.status == "running"
        assert result.started_at is not None
        assert result.updated_at is not None
        session.add.assert_called_once_with(scan)
        session.commit.assert_awaited_once()
        session.refresh.assert_awaited_once_with(scan)

    @pytest.mark.asyncio
    async def test_run_scan_not_found_returns_none(self) -> None:
        """run_scan returns None when scan_id does not exist."""
        session = _mock_session()
        session.get = AsyncMock(return_value=None)

        result = await SentinelScanner.run_scan(session, SCAN_ID)

        assert result is None
        session.commit.assert_not_awaited()


# ═══════════════════════════════════════════════════════════════════
# Complete Scan
# ═══════════════════════════════════════════════════════════════════


class TestCompleteScan:
    """Tests for SentinelScanner.complete_scan."""

    @pytest.mark.asyncio
    async def test_complete_scan_success(self) -> None:
        """complete_scan without error sets status to 'completed'."""
        session = _mock_session()
        scan = _scan(status="running")
        session.get = AsyncMock(return_value=scan)
        # exec for counting discovered services
        session.exec = AsyncMock(return_value=_exec_result([]))

        result = await SentinelScanner.complete_scan(
            session, SCAN_ID, results_summary={"total": 5}
        )

        assert result is not None
        assert result.status == "completed"
        assert result.completed_at is not None
        assert result.results_summary == {"total": 5}
        assert result.services_found == 0
        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_complete_scan_with_error(self) -> None:
        """complete_scan with error_message sets status to 'failed'."""
        session = _mock_session()
        scan = _scan(status="running")
        session.get = AsyncMock(return_value=scan)
        session.exec = AsyncMock(return_value=_exec_result([]))

        result = await SentinelScanner.complete_scan(
            session, SCAN_ID, error_message="Connection timeout"
        )

        assert result is not None
        assert result.status == "failed"
        assert result.error_message == "Connection timeout"

    @pytest.mark.asyncio
    async def test_complete_scan_counts_services(self) -> None:
        """complete_scan counts discovered services linked to the scan."""
        session = _mock_session()
        scan = _scan(status="running")
        services = [_service(), _service(service_id=SERVICE_ID_2)]
        session.get = AsyncMock(return_value=scan)
        session.exec = AsyncMock(return_value=_exec_result(services))

        result = await SentinelScanner.complete_scan(session, SCAN_ID)

        assert result is not None
        assert result.services_found == 2

    @pytest.mark.asyncio
    async def test_complete_scan_not_found_returns_none(self) -> None:
        """complete_scan returns None when scan_id does not exist."""
        session = _mock_session()
        session.get = AsyncMock(return_value=None)

        result = await SentinelScanner.complete_scan(session, SCAN_ID)

        assert result is None
        session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_complete_scan_no_results_summary(self) -> None:
        """complete_scan without results_summary keeps existing value."""
        session = _mock_session()
        scan = _scan(status="running")
        scan.results_summary = {"existing": True}
        session.get = AsyncMock(return_value=scan)
        session.exec = AsyncMock(return_value=_exec_result([]))

        result = await SentinelScanner.complete_scan(session, SCAN_ID)

        assert result is not None
        assert result.results_summary == {"existing": True}


# ═══════════════════════════════════════════════════════════════════
# Add Discovered Service
# ═══════════════════════════════════════════════════════════════════


class TestAddDiscoveredService:
    """Tests for SentinelScanner.add_discovered_service."""

    @pytest.mark.asyncio
    async def test_add_service_adds_and_commits(self) -> None:
        """add_discovered_service should add, commit, and refresh."""
        session = _mock_session()
        svc = _service()

        result = await SentinelScanner.add_discovered_service(session, svc)

        session.add.assert_called_once_with(svc)
        session.commit.assert_awaited_once()
        session.refresh.assert_awaited_once_with(svc)
        assert result is svc

    @pytest.mark.asyncio
    async def test_add_service_preserves_fields(self) -> None:
        """All service fields should be preserved after creation."""
        session = _mock_session()
        svc = _service(
            service_name="Claude Pro",
            provider="anthropic",
            department="legal",
            user_count=42,
            data_sensitivity="confidential",
            is_sanctioned=True,
        )

        result = await SentinelScanner.add_discovered_service(session, svc)

        assert result.service_name == "Claude Pro"
        assert result.provider == "anthropic"
        assert result.department == "legal"
        assert result.user_count == 42
        assert result.data_sensitivity == "confidential"
        assert result.is_sanctioned is True


# ═══════════════════════════════════════════════════════════════════
# Risk Classification
# ═══════════════════════════════════════════════════════════════════


class TestClassifyRisk:
    """Tests for SentinelScanner.classify_risk."""

    @pytest.mark.asyncio
    async def test_classify_risk_not_found_returns_none(self) -> None:
        """classify_risk returns None when service_id does not exist."""
        session = _mock_session()
        session.get = AsyncMock(return_value=None)

        result = await SentinelScanner.classify_risk(session, SERVICE_ID)

        assert result is None

    @pytest.mark.asyncio
    async def test_classify_risk_creates_new_classification(self) -> None:
        """classify_risk creates a RiskClassification when none exists."""
        session = _mock_session()
        svc = _service(
            provider="openai",
            data_sensitivity="internal",
            user_count=10,
            is_sanctioned=False,
            owner="alice@example.com",
        )
        session.get = AsyncMock(return_value=svc)
        # exec for existing classification check — none found
        session.exec = AsyncMock(return_value=_exec_result([]))

        result = await SentinelScanner.classify_risk(session, SERVICE_ID)

        assert result is not None
        assert result.risk_score > 0
        assert result.risk_tier in ("critical", "high", "medium", "low", "informational")
        assert result.service_id == SERVICE_ID
        session.add.assert_called_once()
        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_classify_risk_upserts_existing(self) -> None:
        """classify_risk updates an existing classification instead of creating."""
        session = _mock_session()
        svc = _service(provider="openai", data_sensitivity="internal", user_count=5, is_sanctioned=True)
        existing_cls = _classification(service_id=SERVICE_ID, risk_score=30)

        session.get = AsyncMock(return_value=svc)
        session.exec = AsyncMock(return_value=_exec_result([existing_cls]))

        result = await SentinelScanner.classify_risk(session, SERVICE_ID)

        assert result is existing_cls
        # Score recalculated — sanctioned openai + internal + 5 users
        # data=15, blast=5, compliance=0, capability=25 → 45
        assert result.risk_score == 45
        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_classify_risk_unsanctioned_violation(self) -> None:
        """Unsanctioned service should have a policy violation."""
        session = _mock_session()
        svc = _service(is_sanctioned=False)
        session.get = AsyncMock(return_value=svc)
        session.exec = AsyncMock(return_value=_exec_result([]))

        result = await SentinelScanner.classify_risk(session, SERVICE_ID)

        assert result is not None
        assert any("Unsanctioned" in v for v in result.policy_violations)
        assert any("Review" in a for a in result.recommended_actions)

    @pytest.mark.asyncio
    async def test_classify_risk_restricted_data_violation(self) -> None:
        """Service accessing restricted data should have data-related violation."""
        session = _mock_session()
        svc = _service(data_sensitivity="restricted", is_sanctioned=True)
        session.get = AsyncMock(return_value=svc)
        session.exec = AsyncMock(return_value=_exec_result([]))

        result = await SentinelScanner.classify_risk(session, SERVICE_ID)

        assert result is not None
        assert any("restricted" in v for v in result.policy_violations)
        assert any("data flow" in a.lower() for a in result.recommended_actions)

    @pytest.mark.asyncio
    async def test_classify_risk_high_blast_radius_violation(self) -> None:
        """Service with >50 users should flag high blast radius."""
        session = _mock_session()
        svc = _service(user_count=100, is_sanctioned=True, data_sensitivity="public")
        session.get = AsyncMock(return_value=svc)
        session.exec = AsyncMock(return_value=_exec_result([]))

        result = await SentinelScanner.classify_risk(session, SERVICE_ID)

        assert result is not None
        assert any("blast radius" in v.lower() for v in result.policy_violations)
        # blast_radius_score capped at 20
        assert result.blast_radius_score == 20

    @pytest.mark.asyncio
    async def test_classify_risk_no_owner_action(self) -> None:
        """Service without an owner should recommend assigning one."""
        session = _mock_session()
        svc = _service(owner=None)
        session.get = AsyncMock(return_value=svc)
        session.exec = AsyncMock(return_value=_exec_result([]))

        result = await SentinelScanner.classify_risk(session, SERVICE_ID)

        assert result is not None
        assert any("owner" in a.lower() for a in result.recommended_actions)

    @pytest.mark.asyncio
    async def test_classify_risk_score_capped_at_100(self) -> None:
        """Risk score should never exceed 100."""
        session = _mock_session()
        # Max everything: restricted(40) + 200 users capped(20) + unsanctioned(15) + openai(25) = 100
        svc = _service(
            data_sensitivity="restricted",
            user_count=200,
            is_sanctioned=False,
            provider="openai",
        )
        session.get = AsyncMock(return_value=svc)
        session.exec = AsyncMock(return_value=_exec_result([]))

        result = await SentinelScanner.classify_risk(session, SERVICE_ID)

        assert result is not None
        assert result.risk_score <= 100

    @pytest.mark.asyncio
    async def test_classify_risk_escalation_for_high_score(self) -> None:
        """Score >= 60 should recommend escalation to security team."""
        session = _mock_session()
        # restricted(40) + 20 users(20) + unsanctioned(15) + openai(25) = 100
        svc = _service(
            data_sensitivity="restricted",
            user_count=20,
            is_sanctioned=False,
            provider="openai",
            owner="bob@example.com",
        )
        session.get = AsyncMock(return_value=svc)
        session.exec = AsyncMock(return_value=_exec_result([]))

        result = await SentinelScanner.classify_risk(session, SERVICE_ID)

        assert result is not None
        assert result.risk_score >= 60
        assert any("Escalate" in a for a in result.recommended_actions)


# ═══════════════════════════════════════════════════════════════════
# Auto-Classify Risk (classify_risk scoring edge cases)
# ═══════════════════════════════════════════════════════════════════


class TestAutoClassifyRisk:
    """Edge-case scoring and tier-assignment tests for classify_risk."""

    @pytest.mark.asyncio
    async def test_critical_tier(self) -> None:
        """Score >= 80 should be classified as critical."""
        session = _mock_session()
        # restricted(40) + 20 users(20) + unsanctioned(15) + openai(25) = 100
        svc = _service(
            data_sensitivity="restricted",
            user_count=20,
            is_sanctioned=False,
            provider="openai",
        )
        session.get = AsyncMock(return_value=svc)
        session.exec = AsyncMock(return_value=_exec_result([]))

        result = await SentinelScanner.classify_risk(session, SERVICE_ID)

        assert result is not None
        assert result.risk_tier == "critical"
        assert result.risk_score >= 80

    @pytest.mark.asyncio
    async def test_high_tier(self) -> None:
        """Score in [60, 80) should be classified as high."""
        session = _mock_session()
        # confidential(30) + 15 users(15) + unsanctioned(15) + cohere(15) = 75
        svc = _service(
            data_sensitivity="confidential",
            user_count=15,
            is_sanctioned=False,
            provider="cohere",
        )
        session.get = AsyncMock(return_value=svc)
        session.exec = AsyncMock(return_value=_exec_result([]))

        result = await SentinelScanner.classify_risk(session, SERVICE_ID)

        assert result is not None
        assert result.risk_score == 75
        assert result.risk_tier == "high"

    @pytest.mark.asyncio
    async def test_medium_tier(self) -> None:
        """Score in [40, 60) should be classified as medium."""
        session = _mock_session()
        # internal(15) + 5 users(5) + sanctioned(0) + openai(25) = 45
        svc = _service(
            data_sensitivity="internal",
            user_count=5,
            is_sanctioned=True,
            provider="openai",
        )
        session.get = AsyncMock(return_value=svc)
        session.exec = AsyncMock(return_value=_exec_result([]))

        result = await SentinelScanner.classify_risk(session, SERVICE_ID)

        assert result is not None
        assert result.risk_score == 45
        assert result.risk_tier == "medium"

    @pytest.mark.asyncio
    async def test_low_tier(self) -> None:
        """Score in [20, 40) should be classified as low."""
        session = _mock_session()
        # public(5) + 5 users(5) + sanctioned(0) + custom(10) = 20
        svc = _service(
            data_sensitivity="public",
            user_count=5,
            is_sanctioned=True,
            provider="custom",
        )
        session.get = AsyncMock(return_value=svc)
        session.exec = AsyncMock(return_value=_exec_result([]))

        result = await SentinelScanner.classify_risk(session, SERVICE_ID)

        assert result is not None
        assert result.risk_score == 20
        assert result.risk_tier == "low"

    @pytest.mark.asyncio
    async def test_informational_tier(self) -> None:
        """Score < 20 should be classified as informational."""
        session = _mock_session()
        # public(5) + 0 users(0) + sanctioned(0) + custom(10) = 15
        svc = _service(
            data_sensitivity="public",
            user_count=0,
            is_sanctioned=True,
            provider="custom",
        )
        session.get = AsyncMock(return_value=svc)
        session.exec = AsyncMock(return_value=_exec_result([]))

        result = await SentinelScanner.classify_risk(session, SERVICE_ID)

        assert result is not None
        assert result.risk_score == 15
        assert result.risk_tier == "informational"

    @pytest.mark.asyncio
    async def test_unknown_provider_gets_default_score(self) -> None:
        """Unknown provider defaults to score of 10."""
        session = _mock_session()
        svc = _service(
            data_sensitivity="public",
            user_count=0,
            is_sanctioned=True,
            provider="some_unknown_vendor",
        )
        session.get = AsyncMock(return_value=svc)
        session.exec = AsyncMock(return_value=_exec_result([]))

        result = await SentinelScanner.classify_risk(session, SERVICE_ID)

        assert result is not None
        assert result.model_capability_score == 10

    @pytest.mark.asyncio
    async def test_unknown_sensitivity_gets_default_score(self) -> None:
        """Unknown data sensitivity defaults to score of 20."""
        session = _mock_session()
        svc = _service(
            data_sensitivity="unknown",
            user_count=0,
            is_sanctioned=True,
            provider="custom",
        )
        session.get = AsyncMock(return_value=svc)
        session.exec = AsyncMock(return_value=_exec_result([]))

        result = await SentinelScanner.classify_risk(session, SERVICE_ID)

        assert result is not None
        assert result.data_sensitivity_score == 20

    @pytest.mark.asyncio
    async def test_factors_dict_populated(self) -> None:
        """The factors dict should contain all four scoring components."""
        session = _mock_session()
        svc = _service()
        session.get = AsyncMock(return_value=svc)
        session.exec = AsyncMock(return_value=_exec_result([]))

        result = await SentinelScanner.classify_risk(session, SERVICE_ID)

        assert result is not None
        assert "data_sensitivity" in result.factors
        assert "blast_radius" in result.factors
        assert "compliance_gap" in result.factors
        assert "model_capability" in result.factors


# ═══════════════════════════════════════════════════════════════════
# Posture Report
# ═══════════════════════════════════════════════════════════════════


class TestGeneratePostureReport:
    """Tests for SentinelScanner.generate_posture_report."""

    @pytest.mark.asyncio
    async def test_empty_report(self) -> None:
        """Report with no services or classifications returns baseline values."""
        session = _mock_session()
        session.exec = AsyncMock(side_effect=[
            _exec_result([]),  # services
            _exec_result([]),  # classifications
        ])

        report = await SentinelScanner.generate_posture_report(session)

        assert report["total_services"] == 0
        assert report["sanctioned"] == 0
        assert report["unsanctioned"] == 0
        assert report["posture_score"] == 100  # no risk → perfect posture
        assert report["classifications_count"] == 0
        assert report["top_risks"] == []
        assert report["risk_tier_breakdown"]["critical"] == 0

    @pytest.mark.asyncio
    async def test_report_with_services_and_classifications(self) -> None:
        """Report correctly aggregates services and risk data."""
        session = _mock_session()
        svc1 = _service(service_id=SERVICE_ID, is_sanctioned=True, department="engineering")
        svc2 = _service(service_id=SERVICE_ID_2, is_sanctioned=False, department="legal")
        cls1 = _classification(service_id=SERVICE_ID, risk_tier="low", risk_score=25)
        cls2 = _classification(
            classification_id=UUID("cc000002-0002-0002-0002-000000000002"),
            service_id=SERVICE_ID_2,
            risk_tier="high",
            risk_score=70,
        )
        session.exec = AsyncMock(side_effect=[
            _exec_result([svc1, svc2]),
            _exec_result([cls1, cls2]),
        ])

        report = await SentinelScanner.generate_posture_report(session)

        assert report["total_services"] == 2
        assert report["sanctioned"] == 1
        assert report["unsanctioned"] == 1
        assert report["classifications_count"] == 2
        # avg risk = (25+70)/2 = 47.5, posture = 100-48 = 52
        assert report["posture_score"] == 52
        # Tier breakdown
        assert report["risk_tier_breakdown"]["high"] == 1
        assert report["risk_tier_breakdown"]["low"] == 1

    @pytest.mark.asyncio
    async def test_report_department_breakdown(self) -> None:
        """Department breakdown separates sanctioned vs unsanctioned."""
        session = _mock_session()
        svc1 = _service(service_id=SERVICE_ID, is_sanctioned=True, department="engineering")
        svc2 = _service(service_id=SERVICE_ID_2, is_sanctioned=False, department="engineering")
        svc3 = _service(service_id=SERVICE_ID_3, is_sanctioned=False, department=None)
        session.exec = AsyncMock(side_effect=[
            _exec_result([svc1, svc2, svc3]),
            _exec_result([]),
        ])

        report = await SentinelScanner.generate_posture_report(session)

        eng = report["department_breakdown"]["engineering"]
        assert eng["total"] == 2
        assert eng["sanctioned"] == 1
        assert eng["unsanctioned"] == 1
        unassigned = report["department_breakdown"]["unassigned"]
        assert unassigned["total"] == 1

    @pytest.mark.asyncio
    async def test_report_top_risks_limited_to_five(self) -> None:
        """Top risks list should include at most 5 entries, sorted by score desc."""
        session = _mock_session()
        services = []
        classifications = []
        for i in range(7):
            sid = UUID(f"bb00000{i+1}-000{i+1}-000{i+1}-000{i+1}-00000000000{i+1}")
            cid = UUID(f"cc00000{i+1}-000{i+1}-000{i+1}-000{i+1}-00000000000{i+1}")
            services.append(_service(service_id=sid, is_sanctioned=True))
            classifications.append(_classification(
                classification_id=cid,
                service_id=sid,
                risk_score=(i + 1) * 10,
                risk_tier="medium",
            ))
        session.exec = AsyncMock(side_effect=[
            _exec_result(services),
            _exec_result(classifications),
        ])

        report = await SentinelScanner.generate_posture_report(session)

        assert len(report["top_risks"]) == 5
        scores = [r["risk_score"] for r in report["top_risks"]]
        assert scores == sorted(scores, reverse=True)

    @pytest.mark.asyncio
    async def test_report_top_risks_structure(self) -> None:
        """Each top risk entry has required keys."""
        session = _mock_session()
        svc = _service(service_id=SERVICE_ID, is_sanctioned=True)
        cls = _classification(
            service_id=SERVICE_ID,
            risk_tier="high",
            risk_score=72,
            policy_violations=["Unsanctioned AI service detected"],
        )
        session.exec = AsyncMock(side_effect=[
            _exec_result([svc]),
            _exec_result([cls]),
        ])

        report = await SentinelScanner.generate_posture_report(session)

        assert len(report["top_risks"]) == 1
        risk = report["top_risks"][0]
        assert risk["service_id"] == str(SERVICE_ID)
        assert risk["risk_tier"] == "high"
        assert risk["risk_score"] == 72
        assert risk["policy_violations"] == ["Unsanctioned AI service detected"]

    @pytest.mark.asyncio
    async def test_posture_score_bounded(self) -> None:
        """Posture score should be between 0 and 100."""
        session = _mock_session()
        svc = _service(is_sanctioned=False)
        cls = _classification(service_id=SERVICE_ID, risk_score=100, risk_tier="critical")
        session.exec = AsyncMock(side_effect=[
            _exec_result([svc]),
            _exec_result([cls]),
        ])

        report = await SentinelScanner.generate_posture_report(session)

        assert 0 <= report["posture_score"] <= 100
