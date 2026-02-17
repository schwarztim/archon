"""Tests for RedTeamService — security scanning, JWT attacks, prompt injection,
tenant isolation, credential leak detection, and SARIF report generation."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.models.redteam import (
    AttackCategory,
    SecurityScanConfig,
    SecurityScanResult,
    Severity,
    VulnerabilityFinding,
)
from app.services.redteam_service import RedTeamService


# ── Fixtures ────────────────────────────────────────────────────────

TENANT_A = "tenant-redteam-a"
TENANT_B = "tenant-redteam-b"
USER_ID = str(uuid4())
AGENT_ID = uuid4()


@pytest.fixture()
def svc() -> RedTeamService:
    return RedTeamService()


# ── run_security_scan ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_security_scan_returns_result(svc: RedTeamService) -> None:
    """Full scan returns a SecurityScanResult with findings."""
    result = await svc.run_security_scan(TENANT_A, USER_ID, AGENT_ID)
    assert isinstance(result, SecurityScanResult)
    assert result.tenant_id == TENANT_A
    assert result.agent_id == AGENT_ID
    assert result.summary.total_findings > 0


@pytest.mark.asyncio
async def test_run_security_scan_pass_fail_logic(svc: RedTeamService) -> None:
    """Scan with critical/high findings should not pass."""
    result = await svc.run_security_scan(TENANT_A, USER_ID, AGENT_ID)
    assert result.passed is False
    assert result.summary.critical > 0 or result.summary.high > 0


@pytest.mark.asyncio
async def test_run_security_scan_severity_threshold(svc: RedTeamService) -> None:
    """Severity threshold filters out findings below threshold."""
    config = SecurityScanConfig(
        attack_categories=[AttackCategory.rate_limit_bypass],
        severity_threshold=Severity.medium,
    )
    result = await svc.run_security_scan(TENANT_A, USER_ID, AGENT_ID, scan_config=config)
    for f in result.findings:
        assert Severity[f.severity.value] <= Severity.medium


@pytest.mark.asyncio
async def test_run_security_scan_stores_result(svc: RedTeamService) -> None:
    """Scan result is persisted in the in-memory store and retrievable."""
    result = await svc.run_security_scan(TENANT_A, USER_ID, AGENT_ID)
    fetched = await svc.get_scan_result(TENANT_A, result.scan_id)
    assert fetched is not None
    assert fetched.scan_id == result.scan_id


# ── JWT attacks ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_jwt_attack_suite_findings_count(svc: RedTeamService) -> None:
    """JWT attack suite produces exactly 4 findings."""
    findings = await svc.run_jwt_attack_suite(TENANT_A, AGENT_ID)
    assert len(findings) == 4


@pytest.mark.asyncio
async def test_jwt_attack_suite_categories_and_severities(svc: RedTeamService) -> None:
    """JWT findings have correct categories and include critical + high."""
    findings = await svc.run_jwt_attack_suite(TENANT_A, AGENT_ID)
    assert all(f.category == AttackCategory.jwt_attacks for f in findings)
    severities = {f.severity for f in findings}
    assert Severity.critical in severities
    assert Severity.high in severities


@pytest.mark.asyncio
async def test_jwt_attack_evidence_contains_tenant(svc: RedTeamService) -> None:
    """Each JWT finding's evidence includes the tenant_id for traceability."""
    findings = await svc.run_jwt_attack_suite(TENANT_A, AGENT_ID)
    for f in findings:
        assert f.evidence["tenant_id"] == TENANT_A


# ── Prompt injection ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_prompt_injection_default_payloads(svc: RedTeamService) -> None:
    """Default prompt injection test produces one finding per payload."""
    findings = await svc.run_prompt_injection_tests(TENANT_A, AGENT_ID)
    assert len(findings) == 6  # default payloads count


@pytest.mark.asyncio
async def test_prompt_injection_custom_payloads(svc: RedTeamService) -> None:
    """Custom payloads produce the correct number of findings."""
    custom = ["payload-a", "payload-b"]
    findings = await svc.run_prompt_injection_tests(TENANT_A, AGENT_ID, payloads=custom)
    assert len(findings) == 2
    assert all(f.category == AttackCategory.prompt_injection for f in findings)


# ── Tenant isolation ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tenant_isolation_findings(svc: RedTeamService) -> None:
    """Tenant isolation suite returns findings including critical."""
    findings = await svc.run_tenant_isolation_tests(TENANT_A, AGENT_ID)
    assert len(findings) == 3
    assert any(f.severity == Severity.critical for f in findings)


@pytest.mark.asyncio
async def test_tenant_isolation_scan_store_scoped(svc: RedTeamService) -> None:
    """Scan results for tenant A are not visible to tenant B."""
    result = await svc.run_security_scan(TENANT_A, USER_ID, AGENT_ID)
    fetched_a = await svc.get_scan_result(TENANT_A, result.scan_id)
    fetched_b = await svc.get_scan_result(TENANT_B, result.scan_id)
    assert fetched_a is not None
    assert fetched_b is None


# ── Credential leak scan ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_credential_leak_scan_returns_findings(svc: RedTeamService) -> None:
    """Credential leak scan produces findings for all registered patterns."""
    findings = await svc.run_credential_leak_scan(TENANT_A, AGENT_ID)
    assert len(findings) == 6  # _CREDENTIAL_PATTERNS count
    categories = {f.category for f in findings}
    assert categories == {AttackCategory.credential_leak}


@pytest.mark.asyncio
async def test_credential_leak_severity_split(svc: RedTeamService) -> None:
    """Credential-type findings are critical; PII-type are high."""
    findings = await svc.run_credential_leak_scan(TENANT_A, AGENT_ID)
    for f in findings:
        if "PII" in f.title:
            assert f.severity == Severity.high
        else:
            assert f.severity == Severity.critical


# ── SARIF report ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sarif_report_valid_json(svc: RedTeamService) -> None:
    """generate_sarif_report returns valid JSON in SARIF 2.1.0 format."""
    result = await svc.run_security_scan(TENANT_A, USER_ID, AGENT_ID)
    sarif_str = svc.generate_sarif_report(result)
    sarif = json.loads(sarif_str)
    assert sarif["version"] == "2.1.0"
    assert len(sarif["runs"]) == 1
    run = sarif["runs"][0]
    assert run["tool"]["driver"]["name"] == "Archon RedTeam Engine"
    assert len(run["results"]) == result.summary.total_findings


@pytest.mark.asyncio
async def test_sarif_report_rule_deduplication(svc: RedTeamService) -> None:
    """SARIF rules are deduplicated — fewer rules than results."""
    config = SecurityScanConfig(
        attack_categories=[AttackCategory.jwt_attacks],
        severity_threshold=Severity.info,
    )
    result = await svc.run_security_scan(TENANT_A, USER_ID, AGENT_ID, scan_config=config)
    sarif = json.loads(svc.generate_sarif_report(result))
    run = sarif["runs"][0]
    assert len(run["tool"]["driver"]["rules"]) <= len(run["results"])


# ── Scan history ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scan_history_returns_agent_scoped(svc: RedTeamService) -> None:
    """get_scan_history returns only scans for the given agent in the tenant."""
    other_agent = uuid4()
    await svc.run_security_scan(TENANT_A, USER_ID, AGENT_ID)
    await svc.run_security_scan(TENANT_A, USER_ID, other_agent)
    history = await svc.get_scan_history(TENANT_A, AGENT_ID)
    assert all(h.agent_id == AGENT_ID for h in history)
    assert len(history) >= 1
