"""Tests for SentinelScan Agent-14 enhancements — discovery engine, service inventory,
posture score, risk breakdown, remediation, bulk remediation, and scan history.

All tests use the in-memory stores provided by the service layer.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from app.services.sentinelscan_service import (
    SentinelScanService,
    _findings_store,
    _scan_history_store,
    _remediation_audit,
)

TENANT = "tenant-sentinel-14"
USER = "user-admin-14"


@pytest.fixture(autouse=True)
def _clear_stores() -> None:
    """Reset in-memory stores before each test."""
    _findings_store.clear()
    _scan_history_store.clear()
    _remediation_audit.clear()


# ── Discovery Scan ──────────────────────────────────────────────────


class TestRunDiscoveryScan:
    """Tests for run_discovery_scan."""

    @pytest.mark.asyncio
    async def test_scan_returns_findings(self) -> None:
        """Scan returns findings with correct structure."""
        result = await SentinelScanService.run_discovery_scan(
            tenant_id=TENANT, user_id=USER,
        )
        assert result["status"] == "completed"
        assert len(result["findings"]) > 0
        assert "summary" in result
        assert result["summary"]["total_findings"] == len(result["findings"])

    @pytest.mark.asyncio
    async def test_scan_with_custom_sources(self) -> None:
        """Scan respects custom source configuration."""
        result = await SentinelScanService.run_discovery_scan(
            tenant_id=TENANT, user_id=USER, sources=["sso", "dns"],
        )
        assert result["sources"] == ["sso", "dns"]
        for finding in result["findings"]:
            assert finding["detection_source"] in ["sso", "dns"]

    @pytest.mark.asyncio
    async def test_scan_depth_controls_count(self) -> None:
        """Deeper scan finds more services."""
        quick = await SentinelScanService.run_discovery_scan(
            tenant_id=TENANT, user_id=USER, scan_depth="quick",
        )
        _findings_store.clear()
        _scan_history_store.clear()
        deep = await SentinelScanService.run_discovery_scan(
            tenant_id=TENANT, user_id=USER, scan_depth="deep",
        )
        assert len(deep["findings"]) > len(quick["findings"])

    @pytest.mark.asyncio
    async def test_scan_creates_history(self) -> None:
        """Scan is recorded in scan history store."""
        await SentinelScanService.run_discovery_scan(
            tenant_id=TENANT, user_id=USER,
        )
        assert len(_scan_history_store.get(TENANT, [])) == 1
        entry = _scan_history_store[TENANT][0]
        assert entry["status"] == "completed"
        assert entry["tenant_id"] == TENANT

    @pytest.mark.asyncio
    async def test_scan_populates_findings_store(self) -> None:
        """Scan findings are stored for later inventory retrieval."""
        result = await SentinelScanService.run_discovery_scan(
            tenant_id=TENANT, user_id=USER,
        )
        stored = _findings_store.get(TENANT, [])
        assert len(stored) == len(result["findings"])

    @pytest.mark.asyncio
    async def test_finding_has_required_fields(self) -> None:
        """Each finding has all required fields."""
        result = await SentinelScanService.run_discovery_scan(
            tenant_id=TENANT, user_id=USER,
        )
        for f in result["findings"]:
            assert "id" in f
            assert "service_name" in f
            assert "service_type" in f
            assert f["service_type"] in ("LLM", "Embedding", "Image", "Voice", "Code")
            assert "risk_level" in f
            assert "user_count" in f
            assert "data_exposure" in f
            assert "first_seen" in f
            assert "last_seen" in f
            assert "status" in f
            assert f["status"] in ("Approved", "Unapproved", "Blocked")

    @pytest.mark.asyncio
    async def test_scan_summary_risk_counts(self) -> None:
        """Summary risk counts are consistent with findings."""
        result = await SentinelScanService.run_discovery_scan(
            tenant_id=TENANT, user_id=USER,
        )
        summary = result["summary"]
        findings = result["findings"]
        assert summary["critical"] == sum(1 for f in findings if f["risk_level"] == "critical")
        assert summary["high"] == sum(1 for f in findings if f["risk_level"] == "high")
        assert summary["medium"] == sum(1 for f in findings if f["risk_level"] == "medium")
        assert summary["low"] == sum(1 for f in findings if f["risk_level"] == "low")


# ── Service Inventory ───────────────────────────────────────────────


class TestServiceInventory:
    """Tests for get_service_inventory."""

    @pytest.mark.asyncio
    async def test_empty_inventory(self) -> None:
        """Returns empty inventory when no scans have been run."""
        result = await SentinelScanService.get_service_inventory(tenant_id=TENANT)
        assert result["services"] == []
        assert result["total"] == 0

    @pytest.mark.asyncio
    async def test_inventory_after_scan(self) -> None:
        """Inventory populated after scan."""
        await SentinelScanService.run_discovery_scan(
            tenant_id=TENANT, user_id=USER,
        )
        result = await SentinelScanService.get_service_inventory(tenant_id=TENANT)
        assert result["total"] > 0
        assert len(result["services"]) > 0

    @pytest.mark.asyncio
    async def test_inventory_filter_by_risk(self) -> None:
        """Filter inventory by risk level."""
        await SentinelScanService.run_discovery_scan(
            tenant_id=TENANT, user_id=USER,
        )
        result = await SentinelScanService.get_service_inventory(
            tenant_id=TENANT, risk_level="high",
        )
        for svc in result["services"]:
            assert svc["risk_level"] == "high"

    @pytest.mark.asyncio
    async def test_inventory_filter_by_status(self) -> None:
        """Filter inventory by approval status."""
        await SentinelScanService.run_discovery_scan(
            tenant_id=TENANT, user_id=USER,
        )
        result = await SentinelScanService.get_service_inventory(
            tenant_id=TENANT, status="Approved",
        )
        for svc in result["services"]:
            assert svc["status"] == "Approved"

    @pytest.mark.asyncio
    async def test_inventory_pagination(self) -> None:
        """Pagination limits results correctly."""
        await SentinelScanService.run_discovery_scan(
            tenant_id=TENANT, user_id=USER,
        )
        result = await SentinelScanService.get_service_inventory(
            tenant_id=TENANT, limit=3, offset=0,
        )
        assert len(result["services"]) <= 3
        assert result["limit"] == 3
        assert result["offset"] == 0

    @pytest.mark.asyncio
    async def test_inventory_deduplicates(self) -> None:
        """Multiple scans don't create duplicate services."""
        await SentinelScanService.run_discovery_scan(
            tenant_id=TENANT, user_id=USER, scan_depth="quick",
        )
        first_count = (await SentinelScanService.get_service_inventory(
            tenant_id=TENANT,
        ))["total"]
        await SentinelScanService.run_discovery_scan(
            tenant_id=TENANT, user_id=USER, scan_depth="quick",
        )
        second_count = (await SentinelScanService.get_service_inventory(
            tenant_id=TENANT,
        ))["total"]
        # Deduplication means same services aren't counted twice
        assert second_count == first_count

    @pytest.mark.asyncio
    async def test_inventory_tenant_isolated(self) -> None:
        """Tenant A's inventory is separate from Tenant B."""
        await SentinelScanService.run_discovery_scan(
            tenant_id=TENANT, user_id=USER,
        )
        result_b = await SentinelScanService.get_service_inventory(
            tenant_id="tenant-other-b",
        )
        assert result_b["total"] == 0


# ── Posture Score ───────────────────────────────────────────────────


class TestPostureScore:
    """Tests for compute_weighted_posture."""

    @pytest.mark.asyncio
    async def test_perfect_score_no_findings(self) -> None:
        """No findings produces perfect score."""
        result = await SentinelScanService.compute_weighted_posture(tenant_id=TENANT)
        assert result["score"] == 100
        assert result["grade"] == "Good"
        assert result["color"] == "green"

    @pytest.mark.asyncio
    async def test_score_decreases_with_findings(self) -> None:
        """Score decreases when risky findings exist."""
        await SentinelScanService.run_discovery_scan(
            tenant_id=TENANT, user_id=USER,
        )
        result = await SentinelScanService.compute_weighted_posture(tenant_id=TENANT)
        assert result["score"] < 100
        assert "breakdown" in result
        assert "penalty" in result

    @pytest.mark.asyncio
    async def test_score_never_below_zero(self) -> None:
        """Score is clamped to minimum of 0."""
        # Run many scans to accumulate lots of findings
        for _ in range(5):
            await SentinelScanService.run_discovery_scan(
                tenant_id=TENANT, user_id=USER, scan_depth="deep",
            )
        result = await SentinelScanService.compute_weighted_posture(tenant_id=TENANT)
        assert result["score"] >= 0

    @pytest.mark.asyncio
    async def test_score_breakdown_fields(self) -> None:
        """Breakdown contains all expected penalty categories."""
        await SentinelScanService.run_discovery_scan(
            tenant_id=TENANT, user_id=USER,
        )
        result = await SentinelScanService.compute_weighted_posture(tenant_id=TENANT)
        breakdown = result["breakdown"]
        assert "unauthorized" in breakdown
        assert "critical" in breakdown
        assert "data_exposure" in breakdown
        assert "policy_violations" in breakdown

    @pytest.mark.asyncio
    async def test_grade_green_80_plus(self) -> None:
        """Score >= 80 gives green grade."""
        result = await SentinelScanService.compute_weighted_posture(tenant_id=TENANT)
        if result["score"] >= 80:
            assert result["color"] == "green"
            assert result["grade"] == "Good"

    @pytest.mark.asyncio
    async def test_penalty_formula(self) -> None:
        """Penalty is computed from weighted formula."""
        await SentinelScanService.run_discovery_scan(
            tenant_id=TENANT, user_id=USER,
        )
        result = await SentinelScanService.compute_weighted_posture(tenant_id=TENANT)
        b = result["breakdown"]
        expected_penalty = (b["unauthorized"] * 10) + (b["critical"] * 20) + (b["data_exposure"] * 15) + (b["policy_violations"] * 5)
        assert result["penalty"] == expected_penalty
        assert result["score"] == max(0, 100 - expected_penalty)


# ── Risk Breakdown ──────────────────────────────────────────────────


class TestRiskBreakdown:
    """Tests for get_risk_breakdown."""

    @pytest.mark.asyncio
    async def test_empty_breakdown(self) -> None:
        """Empty breakdown when no findings."""
        result = await SentinelScanService.get_risk_breakdown(tenant_id=TENANT)
        assert result["total_findings"] == 0
        for cat in result["categories"].values():
            assert cat["count"] == 0

    @pytest.mark.asyncio
    async def test_breakdown_after_scan(self) -> None:
        """Risk breakdown has real counts after scan."""
        await SentinelScanService.run_discovery_scan(
            tenant_id=TENANT, user_id=USER,
        )
        result = await SentinelScanService.get_risk_breakdown(tenant_id=TENANT)
        assert result["total_findings"] > 0
        assert "Data Exposure" in result["categories"]
        assert "Unauthorized Access" in result["categories"]
        assert "Credential Risk" in result["categories"]
        assert "Policy Violation" in result["categories"]

    @pytest.mark.asyncio
    async def test_breakdown_categories_have_items(self) -> None:
        """Categories with non-zero counts have item details."""
        await SentinelScanService.run_discovery_scan(
            tenant_id=TENANT, user_id=USER,
        )
        result = await SentinelScanService.get_risk_breakdown(tenant_id=TENANT)
        for cat_data in result["categories"].values():
            if cat_data["count"] > 0:
                assert len(cat_data["items"]) == cat_data["count"]
                for item in cat_data["items"]:
                    assert "id" in item
                    assert "service_name" in item

    @pytest.mark.asyncio
    async def test_breakdown_tenant_isolated(self) -> None:
        """Tenant A's breakdown is separate from Tenant B."""
        await SentinelScanService.run_discovery_scan(
            tenant_id=TENANT, user_id=USER,
        )
        result_b = await SentinelScanService.get_risk_breakdown(
            tenant_id="tenant-other-b",
        )
        assert result_b["total_findings"] == 0


# ── Remediation ─────────────────────────────────────────────────────


class TestRemediation:
    """Tests for apply_remediation."""

    @pytest.mark.asyncio
    async def test_remediate_block(self) -> None:
        """Block action updates finding status."""
        scan = await SentinelScanService.run_discovery_scan(
            tenant_id=TENANT, user_id=USER,
        )
        finding_id = scan["findings"][0]["id"]

        result = await SentinelScanService.apply_remediation(
            tenant_id=TENANT, user_id=USER,
            finding_id=finding_id, action="Block",
        )
        assert result["new_status"] == "Blocked"
        assert result["action"] == "Block"
        assert result["applied_by"] == USER

    @pytest.mark.asyncio
    async def test_remediate_approve(self) -> None:
        """Approve action updates finding status."""
        scan = await SentinelScanService.run_discovery_scan(
            tenant_id=TENANT, user_id=USER,
        )
        finding_id = scan["findings"][0]["id"]
        result = await SentinelScanService.apply_remediation(
            tenant_id=TENANT, user_id=USER,
            finding_id=finding_id, action="Approve",
        )
        assert result["new_status"] == "Approved"

    @pytest.mark.asyncio
    async def test_remediate_monitor(self) -> None:
        """Monitor action updates finding status."""
        scan = await SentinelScanService.run_discovery_scan(
            tenant_id=TENANT, user_id=USER,
        )
        finding_id = scan["findings"][0]["id"]
        result = await SentinelScanService.apply_remediation(
            tenant_id=TENANT, user_id=USER,
            finding_id=finding_id, action="Monitor",
        )
        assert result["new_status"] == "Monitoring"

    @pytest.mark.asyncio
    async def test_remediate_ignore(self) -> None:
        """Ignore action updates finding status."""
        scan = await SentinelScanService.run_discovery_scan(
            tenant_id=TENANT, user_id=USER,
        )
        finding_id = scan["findings"][0]["id"]
        result = await SentinelScanService.apply_remediation(
            tenant_id=TENANT, user_id=USER,
            finding_id=finding_id, action="Ignore",
        )
        assert result["new_status"] == "Ignored"

    @pytest.mark.asyncio
    async def test_remediate_not_found(self) -> None:
        """Non-existent finding returns error."""
        result = await SentinelScanService.apply_remediation(
            tenant_id=TENANT, user_id=USER,
            finding_id="nonexistent-id", action="Block",
        )
        assert "error" in result

    @pytest.mark.asyncio
    async def test_remediate_audit_logged(self) -> None:
        """Remediation creates audit log entry."""
        scan = await SentinelScanService.run_discovery_scan(
            tenant_id=TENANT, user_id=USER,
        )
        finding_id = scan["findings"][0]["id"]
        await SentinelScanService.apply_remediation(
            tenant_id=TENANT, user_id=USER,
            finding_id=finding_id, action="Block",
        )
        audit = _remediation_audit.get(TENANT, [])
        assert len(audit) == 1
        assert audit[0]["action"] == "Block"
        assert audit[0]["finding_id"] == finding_id
        assert audit[0]["user_id"] == USER

    @pytest.mark.asyncio
    async def test_remediate_updates_inventory(self) -> None:
        """Remediated finding shows new status in inventory."""
        scan = await SentinelScanService.run_discovery_scan(
            tenant_id=TENANT, user_id=USER,
        )
        finding_id = scan["findings"][0]["id"]
        service_name = scan["findings"][0]["service_name"]

        await SentinelScanService.apply_remediation(
            tenant_id=TENANT, user_id=USER,
            finding_id=finding_id, action="Approve",
        )
        inventory = await SentinelScanService.get_service_inventory(
            tenant_id=TENANT,
        )
        found = [s for s in inventory["services"] if s["service_name"] == service_name]
        assert len(found) == 1
        assert found[0]["status"] == "Approved"


# ── Bulk Remediation ────────────────────────────────────────────────


class TestBulkRemediation:
    """Tests for apply_bulk_remediation."""

    @pytest.mark.asyncio
    async def test_bulk_remediate_all_succeed(self) -> None:
        """Bulk remediation applies to all specified findings."""
        scan = await SentinelScanService.run_discovery_scan(
            tenant_id=TENANT, user_id=USER,
        )
        ids = [f["id"] for f in scan["findings"][:3]]

        result = await SentinelScanService.apply_bulk_remediation(
            tenant_id=TENANT, user_id=USER,
            finding_ids=ids, action="Monitor",
        )
        assert result["total"] == 3
        assert result["succeeded"] == 3
        assert result["failed"] == 0
        assert result["action"] == "Monitor"

    @pytest.mark.asyncio
    async def test_bulk_remediate_partial_failure(self) -> None:
        """Bulk remediation handles missing findings gracefully."""
        scan = await SentinelScanService.run_discovery_scan(
            tenant_id=TENANT, user_id=USER,
        )
        ids = [scan["findings"][0]["id"], "nonexistent-1", "nonexistent-2"]

        result = await SentinelScanService.apply_bulk_remediation(
            tenant_id=TENANT, user_id=USER,
            finding_ids=ids, action="Block",
        )
        assert result["total"] == 3
        assert result["succeeded"] == 1
        assert result["failed"] == 2

    @pytest.mark.asyncio
    async def test_bulk_remediate_audit_logged(self) -> None:
        """Bulk remediation creates audit entries for each finding."""
        scan = await SentinelScanService.run_discovery_scan(
            tenant_id=TENANT, user_id=USER,
        )
        ids = [f["id"] for f in scan["findings"][:2]]

        await SentinelScanService.apply_bulk_remediation(
            tenant_id=TENANT, user_id=USER,
            finding_ids=ids, action="Approve",
        )
        audit = _remediation_audit.get(TENANT, [])
        assert len(audit) == 2

    @pytest.mark.asyncio
    async def test_bulk_remediate_empty_list(self) -> None:
        """Empty finding list produces zero results."""
        result = await SentinelScanService.apply_bulk_remediation(
            tenant_id=TENANT, user_id=USER,
            finding_ids=[], action="Block",
        )
        assert result["total"] == 0
        assert result["succeeded"] == 0


# ── Scan History ────────────────────────────────────────────────────


class TestScanHistory:
    """Tests for get_scan_history."""

    @pytest.mark.asyncio
    async def test_empty_history(self) -> None:
        """No scans yields empty history."""
        result = await SentinelScanService.get_scan_history(tenant_id=TENANT)
        assert result["scans"] == []
        assert result["total"] == 0

    @pytest.mark.asyncio
    async def test_history_after_scans(self) -> None:
        """History records all scans."""
        await SentinelScanService.run_discovery_scan(
            tenant_id=TENANT, user_id=USER,
        )
        await SentinelScanService.run_discovery_scan(
            tenant_id=TENANT, user_id=USER,
        )
        result = await SentinelScanService.get_scan_history(tenant_id=TENANT)
        assert result["total"] == 2
        assert len(result["scans"]) == 2

    @pytest.mark.asyncio
    async def test_history_pagination(self) -> None:
        """History respects pagination limits."""
        for _ in range(5):
            await SentinelScanService.run_discovery_scan(
                tenant_id=TENANT, user_id=USER, scan_depth="quick",
            )
        result = await SentinelScanService.get_scan_history(
            tenant_id=TENANT, limit=2, offset=0,
        )
        assert len(result["scans"]) == 2
        assert result["total"] == 5

    @pytest.mark.asyncio
    async def test_history_tenant_isolated(self) -> None:
        """Tenant A's history is separate from Tenant B."""
        await SentinelScanService.run_discovery_scan(
            tenant_id=TENANT, user_id=USER,
        )
        result_b = await SentinelScanService.get_scan_history(
            tenant_id="tenant-other-b",
        )
        assert result_b["total"] == 0

    @pytest.mark.asyncio
    async def test_history_entry_structure(self) -> None:
        """History entries have all required fields."""
        await SentinelScanService.run_discovery_scan(
            tenant_id=TENANT, user_id=USER,
        )
        result = await SentinelScanService.get_scan_history(tenant_id=TENANT)
        entry = result["scans"][0]
        assert "id" in entry
        assert "tenant_id" in entry
        assert "initiated_by" in entry
        assert "sources" in entry
        assert "scan_depth" in entry
        assert "status" in entry
        assert "started_at" in entry
        assert "completed_at" in entry
        assert "findings_count" in entry

    @pytest.mark.asyncio
    async def test_history_most_recent_first(self) -> None:
        """History returns most recent scans first."""
        await SentinelScanService.run_discovery_scan(
            tenant_id=TENANT, user_id=USER, scan_depth="quick",
        )
        await SentinelScanService.run_discovery_scan(
            tenant_id=TENANT, user_id=USER, scan_depth="deep",
        )
        result = await SentinelScanService.get_scan_history(tenant_id=TENANT)
        scans = result["scans"]
        assert scans[0]["started_at"] >= scans[1]["started_at"]
