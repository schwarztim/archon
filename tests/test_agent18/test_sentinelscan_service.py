"""Tests for SentinelScanService — shadow AI discovery, SSO ingestion, posture, remediation."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.models.sentinelscan import (
    AIAsset,
    CredentialExposure,
    DiscoveryConfig,
    DiscoveryResult,
    IngestResult,
    KnownAIService,
    PostureReport,
    PostureScore,
    RemediationWorkflow,
)
from app.services.sentinelscan_service import SentinelScanService

# ── Fixtures ────────────────────────────────────────────────────────

TENANT_ID = uuid4()
USER_ID = uuid4()


# ── discover_shadow_ai ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_discover_shadow_ai_returns_discovery_result() -> None:
    """Discovery scan returns a DiscoveryResult with services."""
    config = DiscoveryConfig(sources=["sso"], scan_depth="standard")
    result = await SentinelScanService.discover_shadow_ai(TENANT_ID, USER_ID, config)

    assert isinstance(result, DiscoveryResult)
    assert result.tenant_id == TENANT_ID
    assert result.id is not None
    assert result.completed_at is not None


@pytest.mark.asyncio
async def test_discover_shadow_ai_counts_are_consistent() -> None:
    """Shadow + approved + blocked should equal total discovered services."""
    config = DiscoveryConfig(sources=["sso"], scan_depth="deep")
    result = await SentinelScanService.discover_shadow_ai(TENANT_ID, USER_ID, config)

    total = result.shadow_count + result.approved_count + result.blocked_count
    assert total == len(result.discovered_services)


@pytest.mark.asyncio
async def test_discover_shadow_ai_services_have_required_fields() -> None:
    """Each discovered service dict must carry name, domain, category, status, risk_level."""
    config = DiscoveryConfig(sources=["sso"])
    result = await SentinelScanService.discover_shadow_ai(TENANT_ID, USER_ID, config)

    for svc in result.discovered_services:
        assert "service_name" in svc
        assert "domain" in svc
        assert "category" in svc
        assert "status" in svc
        assert "risk_level" in svc


# ── ingest_sso_logs ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ingest_sso_logs_known_domain() -> None:
    """Ingesting a log entry with a known AI domain detects the service."""
    logs = [{"target_url": "https://chat.openai.com/session"}]
    result = await SentinelScanService.ingest_sso_logs(TENANT_ID, "okta", logs)

    assert isinstance(result, IngestResult)
    assert result.source == "okta"
    assert result.records_processed == 1
    assert result.services_detected >= 1


@pytest.mark.asyncio
async def test_ingest_sso_logs_unknown_domain() -> None:
    """An unknown domain should not increment services_detected."""
    logs = [{"target_url": "https://internal.corp.example.com/app"}]
    result = await SentinelScanService.ingest_sso_logs(TENANT_ID, "azure_ad", logs)

    assert result.records_processed == 1
    assert result.services_detected == 0


@pytest.mark.asyncio
async def test_ingest_sso_logs_empty_list() -> None:
    """Empty log list processes zero records with no errors."""
    result = await SentinelScanService.ingest_sso_logs(TENANT_ID, "ping", [])

    assert result.records_processed == 0
    assert result.services_detected == 0
    assert result.errors == 0


# ── inventory_ai_assets ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_inventory_ai_assets_returns_list() -> None:
    """Inventory returns a non-empty list of AIAsset."""
    assets = await SentinelScanService.inventory_ai_assets(TENANT_ID)

    assert isinstance(assets, list)
    assert len(assets) > 0
    assert all(isinstance(a, AIAsset) for a in assets)


@pytest.mark.asyncio
async def test_inventory_ai_assets_tenant_scoped() -> None:
    """Every returned asset must be scoped to the requesting tenant."""
    assets = await SentinelScanService.inventory_ai_assets(TENANT_ID)

    for asset in assets:
        assert asset.tenant_id == TENANT_ID


# ── credential_exposure ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scan_credential_exposure_returns_list() -> None:
    """Credential scan returns a list (possibly empty) of CredentialExposure."""
    exposures = await SentinelScanService.scan_credential_exposure(TENANT_ID)

    assert isinstance(exposures, list)
    assert all(isinstance(e, CredentialExposure) for e in exposures) or len(exposures) == 0


# ── posture_score ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_posture_score_range() -> None:
    """Posture score overall must be in [0, 100]."""
    score = await SentinelScanService.compute_posture_score(TENANT_ID)

    assert isinstance(score, PostureScore)
    assert 0 <= score.overall <= 100
    assert score.tenant_id == TENANT_ID


@pytest.mark.asyncio
async def test_posture_score_has_categories() -> None:
    """Posture score should include category breakdowns."""
    score = await SentinelScanService.compute_posture_score(TENANT_ID)

    assert len(score.categories) > 0
    for cat_name, cat_value in score.categories.items():
        assert isinstance(cat_name, str)
        assert 0 <= cat_value <= 100


# ── remediation ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_remediation_notify() -> None:
    """Creating a 'notify' remediation returns escalation_level 0."""
    asset_id = uuid4()
    wf = await SentinelScanService.create_remediation(TENANT_ID, USER_ID, asset_id, "notify")

    assert isinstance(wf, RemediationWorkflow)
    assert wf.action == "notify"
    assert wf.escalation_level == 0
    assert wf.status == "pending"
    assert wf.tenant_id == TENANT_ID


@pytest.mark.asyncio
async def test_create_remediation_block_highest_escalation() -> None:
    """'block' action maps to highest escalation level (3)."""
    asset_id = uuid4()
    wf = await SentinelScanService.create_remediation(TENANT_ID, USER_ID, asset_id, "block")

    assert wf.escalation_level == 3
    assert wf.action == "block"


@pytest.mark.asyncio
async def test_create_remediation_escalate_level() -> None:
    """'escalate' action maps to escalation level 2."""
    asset_id = uuid4()
    wf = await SentinelScanService.create_remediation(TENANT_ID, USER_ID, asset_id, "escalate")

    assert wf.escalation_level == 2


# ── known_services ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_known_services_returns_list() -> None:
    """Known AI services database should return 100+ entries."""
    services = await SentinelScanService.get_known_ai_services()

    assert isinstance(services, list)
    assert len(services) >= 100
    assert all(isinstance(s, KnownAIService) for s in services)


@pytest.mark.asyncio
async def test_known_services_contain_major_providers() -> None:
    """Major providers like OpenAI, Anthropic, Google must be present."""
    services = await SentinelScanService.get_known_ai_services()
    domains = {s.domain for s in services}

    assert "chat.openai.com" in domains
    assert "claude.ai" in domains
    assert "gemini.google.com" in domains


@pytest.mark.asyncio
async def test_posture_report_generation() -> None:
    """Posture report should contain findings and recommendations."""
    report = await SentinelScanService.generate_posture_report(TENANT_ID, USER_ID, "2026-02")

    assert isinstance(report, PostureReport)
    assert report.tenant_id == TENANT_ID
    assert report.period == "2026-02"
    assert len(report.findings) > 0
    assert len(report.recommendations) > 0
    assert report.current_score > 0
