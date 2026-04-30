"""API routes for the Archon SentinelScan engine."""

from __future__ import annotations

from datetime import datetime, timezone

from app.utils.time import utcnow
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field as PField
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.interfaces.models.enterprise import AuthenticatedUser
from app.middleware.rbac import require_permission
from app.models.audit import EnterpriseAuditEvent
from app.models.sentinelscan import (
    DiscoveredService,
    DiscoveryConfig,
    DiscoveryScan,
)
from app.secrets.manager import get_secrets_manager, VaultSecretsManager
from app.services.audit_log_service import AuditLogService
from app.services.sentinelscan import SentinelScanner
from app.services.sentinelscan_service import SentinelScanService

router = APIRouter(prefix="/sentinelscan", tags=["sentinelscan"])


# ── Request / response schemas ──────────────────────────────────────


class ScanCreate(BaseModel):
    """Payload for creating a discovery scan."""

    name: str
    scan_type: str  # sso | network | api_gateway | saas | browser | custom
    config: dict[str, Any] = PField(default_factory=dict)
    initiated_by: UUID | None = None


class ScanComplete(BaseModel):
    """Payload for marking a scan as completed or failed."""

    results_summary: dict[str, Any] | None = None
    error_message: str | None = None


class DiscoveredServiceCreate(BaseModel):
    """Payload for recording a discovered AI service."""

    scan_id: UUID
    service_name: str
    service_type: str  # llm | copilot | chatbot | image_gen | custom_model | saas_ai
    provider: str  # openai | anthropic | google | microsoft | cohere | custom
    detection_source: str
    department: str | None = None
    owner: str | None = None
    user_count: int = 0
    data_sensitivity: str = "unknown"
    is_sanctioned: bool = False
    extra_metadata: dict[str, Any] = PField(default_factory=dict)


class DiscoveredServiceUpdate(BaseModel):
    """Payload for partial-updating a discovered service."""

    service_name: str | None = None
    service_type: str | None = None
    department: str | None = None
    owner: str | None = None
    user_count: int | None = None
    data_sensitivity: str | None = None
    is_sanctioned: bool | None = None
    extra_metadata: dict[str, Any] | None = None


class ClassifyRiskRequest(BaseModel):
    """Payload for requesting risk classification."""

    service_id: UUID


# ── Helpers ──────────────────────────────────────────────────────────


def _meta(*, request_id: str | None = None, **extra: Any) -> dict[str, Any]:
    """Build standard envelope meta block."""
    return {
        "request_id": request_id or str(uuid4()),
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        **extra,
    }


# ── Discovery Scan CRUD ─────────────────────────────────────────────


@router.get("/discovery")
async def list_scans(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    scan_type: str | None = Query(default=None),
    status: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List discovery scans with pagination."""
    scans, total = await SentinelScanner.list_scans(
        session,
        scan_type=scan_type,
        status=status,
        limit=limit,
        offset=offset,
    )
    return {
        "data": [s.model_dump(mode="json") for s in scans],
        "meta": _meta(pagination={"total": total, "limit": limit, "offset": offset}),
    }


@router.post("/discovery", status_code=201)
async def create_scan(
    body: ScanCreate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Create a new discovery scan."""
    scan = DiscoveryScan(**body.model_dump())
    created = await SentinelScanner.create_scan(session, scan)
    return {"data": created.model_dump(mode="json"), "meta": _meta()}


@router.get("/discovery/{scan_id}")
async def get_scan(
    scan_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get a discovery scan by ID."""
    scan = await SentinelScanner.get_scan(session, scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="Scan not found")
    return {"data": scan.model_dump(mode="json"), "meta": _meta()}


@router.post("/discovery/{scan_id}/run")
async def run_scan(
    scan_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Start executing a discovery scan."""
    scan = await SentinelScanner.run_scan(session, scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="Scan not found")
    return {"data": scan.model_dump(mode="json"), "meta": _meta()}


@router.post("/discovery/{scan_id}/complete")
async def complete_scan(
    scan_id: UUID,
    body: ScanComplete,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Mark a discovery scan as completed or failed."""
    scan = await SentinelScanner.complete_scan(
        session,
        scan_id,
        results_summary=body.results_summary,
        error_message=body.error_message,
    )
    if scan is None:
        raise HTTPException(status_code=404, detail="Scan not found")
    return {"data": scan.model_dump(mode="json"), "meta": _meta()}


# ── Inventory (Discovered Services) ─────────────────────────────────


@router.get("/inventory")
async def list_discovered_services(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    scan_id: UUID | None = Query(default=None),
    service_type: str | None = Query(default=None),
    provider: str | None = Query(default=None),
    department: str | None = Query(default=None),
    is_sanctioned: bool | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List discovered AI services with pagination and filters."""
    services, total = await SentinelScanner.list_discovered_services(
        session,
        scan_id=scan_id,
        service_type=service_type,
        provider=provider,
        department=department,
        is_sanctioned=is_sanctioned,
        limit=limit,
        offset=offset,
    )
    return {
        "data": [s.model_dump(mode="json") for s in services],
        "meta": _meta(pagination={"total": total, "limit": limit, "offset": offset}),
    }


@router.post("/inventory", status_code=201)
async def add_discovered_service(
    body: DiscoveredServiceCreate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Record a newly discovered AI service."""
    service = DiscoveredService(**body.model_dump())
    created = await SentinelScanner.add_discovered_service(session, service)
    return {"data": created.model_dump(mode="json"), "meta": _meta()}


@router.get("/inventory/{service_id}")
async def get_discovered_service(
    service_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get a discovered service by ID."""
    service = await SentinelScanner.get_discovered_service(session, service_id)
    if service is None:
        raise HTTPException(status_code=404, detail="Discovered service not found")
    return {"data": service.model_dump(mode="json"), "meta": _meta()}


@router.put("/inventory/{service_id}")
async def update_discovered_service(
    service_id: UUID,
    body: DiscoveredServiceUpdate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Update a discovered service."""
    data = body.model_dump(exclude_unset=True)
    service = await SentinelScanner.update_discovered_service(session, service_id, data)
    if service is None:
        raise HTTPException(status_code=404, detail="Discovered service not found")
    return {"data": service.model_dump(mode="json"), "meta": _meta()}


# ── Risk Classification ─────────────────────────────────────────────


@router.post("/risk/classify")
async def classify_risk(
    body: ClassifyRiskRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Compute risk classification for a discovered service."""
    classification = await SentinelScanner.classify_risk(session, body.service_id)
    if classification is None:
        raise HTTPException(status_code=404, detail="Discovered service not found")
    return {"data": classification.model_dump(mode="json"), "meta": _meta()}


@router.get("/risk/{service_id}")
async def get_risk_classification(
    service_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get risk classification for a discovered service."""
    classification = await SentinelScanner.get_risk_classification(session, service_id)
    if classification is None:
        raise HTTPException(status_code=404, detail="Risk classification not found")
    return {"data": classification.model_dump(mode="json"), "meta": _meta()}


@router.get("/risk")
async def list_risk_classifications(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    risk_tier: str | None = Query(default=None),
    min_score: int | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List risk classifications with pagination and filters."""
    classifications, total = await SentinelScanner.list_risk_classifications(
        session,
        risk_tier=risk_tier,
        min_score=min_score,
        limit=limit,
        offset=offset,
    )
    return {
        "data": [c.model_dump(mode="json") for c in classifications],
        "meta": _meta(pagination={"total": total, "limit": limit, "offset": offset}),
    }


# ── Posture Report ──────────────────────────────────────────────────


@router.get("/posture/summary")
async def get_posture_report(
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Generate an AI security posture report."""
    report = await SentinelScanner.generate_posture_report(session)
    return {"data": report, "meta": _meta()}


# ── Enterprise SentinelScan Routes (v1) ─────────────────────────────

enterprise_router = APIRouter(
    prefix="/sentinel",
    tags=["sentinel-enterprise"],
)


# ── Request schemas ─────────────────────────────────────────────────


class DiscoverRequest(BaseModel):
    """Payload for shadow AI discovery scan."""

    sources: list[str] = PField(default_factory=lambda: ["sso"])
    scan_depth: str = "standard"
    include_network_logs: bool = False
    time_range_days: int = 30


class IngestRequest(BaseModel):
    """Payload for SSO log ingestion."""

    source: str  # okta | azure_ad | ping | onelogin | custom
    log_data: list[dict[str, Any]] = PField(default_factory=list)


class RemediateRequest(BaseModel):
    """Payload for creating a remediation workflow."""

    asset_id: UUID
    action: str  # notify | offer_alternative | escalate | block


class ReportRequest(BaseModel):
    """Payload for posture report generation."""

    period: str  # e.g. "2026-02"


# ── Audit helper ────────────────────────────────────────────────────


async def _audit(
    session: AsyncSession,
    user: AuthenticatedUser,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Record an enterprise audit event."""
    event = EnterpriseAuditEvent(
        id=uuid4(),
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details or {},
        created_at=utcnow(),
    )
    await AuditLogService.create(session, event)


# ── POST /api/v1/sentinel/discover ──────────────────────────────────


@enterprise_router.post("/discover", status_code=201)
async def run_discovery(
    body: DiscoverRequest,
    user: AuthenticatedUser = Depends(require_permission("sentinel", "discover")),
    session: AsyncSession = Depends(get_session),
    secrets: VaultSecretsManager = Depends(get_secrets_manager),
) -> dict[str, Any]:
    """Run a shadow AI discovery scan."""
    config = DiscoveryConfig(
        sources=body.sources,
        scan_depth=body.scan_depth,
        include_network_logs=body.include_network_logs,
        time_range_days=body.time_range_days,
    )
    result = await SentinelScanService.discover_shadow_ai(
        tenant_id=user.tenant_id,
        user_id=user.id,
        config=config,
    )
    await _audit(
        session,
        user,
        "sentinel.discovery.executed",
        "sentinel_scan",
        str(result.id),
        {"shadow_count": result.shadow_count},
    )
    return {"data": result.model_dump(mode="json"), "meta": _meta()}


# ── POST /api/v1/sentinel/ingest ────────────────────────────────────


@enterprise_router.post("/ingest", status_code=201)
async def ingest_logs(
    body: IngestRequest,
    user: AuthenticatedUser = Depends(require_permission("sentinel", "ingest")),
    session: AsyncSession = Depends(get_session),
    secrets: VaultSecretsManager = Depends(get_secrets_manager),
) -> dict[str, Any]:
    """Ingest SSO/audit logs from identity providers."""
    result = await SentinelScanService.ingest_sso_logs(
        tenant_id=user.tenant_id,
        source=body.source,
        log_data=body.log_data,
    )
    await _audit(
        session,
        user,
        "sentinel.ingest.completed",
        "sso_logs",
        details={"source": result.source, "records": result.records_processed},
    )
    return {"data": result.model_dump(mode="json"), "meta": _meta()}


# ── GET /api/v1/sentinel/inventory ──────────────────────────────────


@enterprise_router.get("/inventory")
async def get_inventory(
    user: AuthenticatedUser = Depends(require_permission("sentinel", "read")),
    session: AsyncSession = Depends(get_session),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """Get unified AI asset inventory for the tenant."""
    assets = await SentinelScanService.inventory_ai_assets(tenant_id=user.tenant_id)
    total = len(assets)
    page = assets[offset : offset + limit]
    return {
        "data": [a.model_dump(mode="json") for a in page],
        "meta": _meta(pagination={"total": total, "limit": limit, "offset": offset}),
    }


# ── POST /api/v1/sentinel/scan-credentials ─────────────────────────


@enterprise_router.post("/scan-credentials", status_code=201)
async def scan_credentials(
    user: AuthenticatedUser = Depends(require_permission("sentinel", "scan")),
    session: AsyncSession = Depends(get_session),
    secrets: VaultSecretsManager = Depends(get_secrets_manager),
) -> dict[str, Any]:
    """Scan for API key/token credential exposures."""
    exposures = await SentinelScanService.scan_credential_exposure(
        tenant_id=user.tenant_id,
    )
    await _audit(
        session,
        user,
        "sentinel.credential_scan.executed",
        "credential_scan",
        details={"exposures_found": len(exposures)},
    )
    return {
        "data": [e.model_dump(mode="json") for e in exposures],
        "meta": _meta(),
    }


# ── GET /api/v1/sentinel/posture ────────────────────────────────────


@enterprise_router.get("/posture")
async def get_posture_score(
    user: AuthenticatedUser = Depends(require_permission("sentinel", "read")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get organization-wide AI security posture score."""
    score = await SentinelScanService.compute_posture_score(
        tenant_id=user.tenant_id,
    )
    return {"data": score.model_dump(mode="json"), "meta": _meta()}


# ── POST /api/v1/sentinel/remediate ─────────────────────────────────


@enterprise_router.post("/remediate", status_code=201)
async def create_remediation(
    body: RemediateRequest,
    user: AuthenticatedUser = Depends(require_permission("sentinel", "remediate")),
    session: AsyncSession = Depends(get_session),
    secrets: VaultSecretsManager = Depends(get_secrets_manager),
) -> dict[str, Any]:
    """Create a remediation workflow for a shadow AI asset."""
    workflow = await SentinelScanService.create_remediation(
        tenant_id=user.tenant_id,
        user_id=user.id,
        asset_id=body.asset_id,
        action=body.action,
    )
    await _audit(
        session,
        user,
        "sentinel.remediation.created",
        "remediation_workflow",
        str(workflow.id),
        {"asset_id": str(body.asset_id), "action": body.action},
    )
    return {"data": workflow.model_dump(mode="json"), "meta": _meta()}


# ── POST /api/v1/sentinel/report ────────────────────────────────────


@enterprise_router.post("/report", status_code=201)
async def generate_report(
    body: ReportRequest,
    user: AuthenticatedUser = Depends(require_permission("sentinel", "report")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Generate monthly AI security posture report."""
    report = await SentinelScanService.generate_posture_report(
        tenant_id=user.tenant_id,
        user_id=user.id,
        period=body.period,
    )
    await _audit(
        session,
        user,
        "sentinel.report.generated",
        "posture_report",
        details={"period": body.period},
    )
    return {"data": report.model_dump(mode="json"), "meta": _meta()}


# ── GET /api/v1/sentinel/known-services ─────────────────────────────


@enterprise_router.get("/known-services")
async def list_known_services(
    user: AuthenticatedUser = Depends(require_permission("sentinel", "read")),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """Get the database of known AI services."""
    all_services = await SentinelScanService.get_known_ai_services()
    total = len(all_services)
    page = all_services[offset : offset + limit]
    return {
        "data": [s.model_dump(mode="json") for s in page],
        "meta": _meta(pagination={"total": total, "limit": limit, "offset": offset}),
    }


# ── Agent-14 Enhanced Endpoints (/api/v1/sentinelscan/*) ────────────

scan_router = APIRouter(
    prefix="/sentinelscan",
    tags=["sentinelscan-v1"],
)


class ScanRequest(BaseModel):
    """Payload for running a discovery scan."""

    sources: list[str] = PField(default_factory=lambda: ["sso", "api_gateway", "dns"])
    scan_depth: str = "standard"


class RemediateItemRequest(BaseModel):
    """Payload for single remediation."""

    action: str  # Block | Approve | Monitor | Ignore


class BulkRemediateRequest(BaseModel):
    """Payload for bulk remediation."""

    finding_ids: list[str]
    action: str  # Block | Approve | Monitor | Ignore


# ── POST /api/v1/sentinelscan/scan ──────────────────────────────────


@scan_router.post("/scan", status_code=201)
async def run_scan_v1(
    body: ScanRequest,
    user: AuthenticatedUser = Depends(require_permission("sentinel", "discover")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Run a multi-source discovery scan."""
    result = await SentinelScanService.run_discovery_scan(
        tenant_id=user.tenant_id,
        user_id=user.id,
        sources=body.sources,
        scan_depth=body.scan_depth,
    )
    await _audit(
        session,
        user,
        "sentinelscan.scan.executed",
        "sentinel_scan",
        result["id"],
        {"findings_count": len(result["findings"])},
    )
    return {"data": result, "meta": _meta()}


# ── GET /api/v1/sentinelscan/services ───────────────────────────────


@scan_router.get("/services")
async def list_services_v1(
    user: AuthenticatedUser = Depends(require_permission("sentinel", "read")),
    session: AsyncSession = Depends(get_session),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    risk_level: str | None = Query(default=None),
    status: str | None = Query(default=None),
    service_type: str | None = Query(default=None),
) -> dict[str, Any]:
    """Get service inventory with optional filters."""
    result = await SentinelScanService.get_service_inventory(
        tenant_id=user.tenant_id,
        limit=limit,
        offset=offset,
        risk_level=risk_level,
        status=status,
        service_type=service_type,
    )
    return {
        "data": result["services"],
        "meta": _meta(
            pagination={
                "total": result["total"],
                "limit": result["limit"],
                "offset": result["offset"],
            }
        ),
    }


# ── GET /api/v1/sentinelscan/posture ────────────────────────────────


@scan_router.get("/posture/weighted")
async def get_posture_v1(
    user: AuthenticatedUser = Depends(require_permission("sentinel", "read")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get weighted posture score."""
    result = await SentinelScanService.compute_weighted_posture(
        tenant_id=user.tenant_id,
    )
    return {"data": result, "meta": _meta()}


# ── GET /api/v1/sentinelscan/risks ──────────────────────────────────


@scan_router.get("/risks")
async def get_risks_v1(
    user: AuthenticatedUser = Depends(require_permission("sentinel", "read")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get risk breakdown by category."""
    result = await SentinelScanService.get_risk_breakdown(
        tenant_id=user.tenant_id,
    )
    return {"data": result, "meta": _meta()}


# ── POST /api/v1/sentinelscan/remediate/{id} ────────────────────────


@scan_router.post("/remediate/{finding_id}", status_code=200)
async def remediate_finding_v1(
    finding_id: str,
    body: RemediateItemRequest,
    user: AuthenticatedUser = Depends(require_permission("sentinel", "remediate")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Apply remediation action to a single finding."""
    result = await SentinelScanService.apply_remediation(
        tenant_id=user.tenant_id,
        user_id=user.id,
        finding_id=finding_id,
        action=body.action,
    )
    await _audit(
        session,
        user,
        "sentinelscan.remediate.applied",
        "sentinel_finding",
        finding_id,
        {"action": body.action},
    )
    return {"data": result, "meta": _meta()}


# ── POST /api/v1/sentinelscan/remediate/bulk ────────────────────────


@scan_router.post("/remediate/bulk", status_code=200)
async def bulk_remediate_v1(
    body: BulkRemediateRequest,
    user: AuthenticatedUser = Depends(require_permission("sentinel", "remediate")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Apply remediation action to multiple findings."""
    result = await SentinelScanService.apply_bulk_remediation(
        tenant_id=user.tenant_id,
        user_id=user.id,
        finding_ids=body.finding_ids,
        action=body.action,
    )
    await _audit(
        session,
        user,
        "sentinelscan.remediate.bulk",
        "sentinel_findings",
        details={"action": body.action, "count": len(body.finding_ids)},
    )
    return {"data": result, "meta": _meta()}


# ── GET /api/v1/sentinelscan/history ────────────────────────────────


@scan_router.get("/history")
async def scan_history_v1(
    user: AuthenticatedUser = Depends(require_permission("sentinel", "read")),
    session: AsyncSession = Depends(get_session),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """Get scan history with pagination."""
    result = await SentinelScanService.get_scan_history(
        tenant_id=user.tenant_id,
        limit=limit,
        offset=offset,
    )
    return {
        "data": result["scans"],
        "meta": _meta(
            pagination={
                "total": result["total"],
                "limit": result["limit"],
                "offset": result["offset"],
            }
        ),
    }
