"""API routes for the Archon DLP (Data Loss Prevention) engine.

Enterprise-grade: all endpoints authenticated, RBAC-checked, tenant-scoped,
and audit-logged per AGENT_RULES.md.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.utils.time import utcnow
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field as PField
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.database import get_session
from app.interfaces.models.enterprise import AuthenticatedUser
from app.middleware.rbac import require_permission
from app.models.audit import EnterpriseAuditEvent
from app.models.dlp import (
    DLPPolicy,
    GuardrailConfig,
)
from app.services.dlp import DLPEngine
from app.services.dlp_service import DLPService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dlp", tags=["DLP"])


# ── Request / response schemas ──────────────────────────────────────


class DLPPolicyCreate(BaseModel):
    """Payload for creating a DLP policy."""

    name: str
    description: str | None = None
    is_active: bool = True
    detector_types: list[str] = PField(default_factory=list)
    custom_patterns: dict[str, str] = PField(default_factory=dict)
    action: str = "redact"
    sensitivity: str = "high"
    agent_id: UUID | None = None
    department_id: UUID | None = None


class DLPPolicyUpdate(BaseModel):
    """Payload for partial-updating a DLP policy."""

    name: str | None = None
    description: str | None = None
    is_active: bool | None = None
    detector_types: list[str] | None = None
    custom_patterns: dict[str, str] | None = None
    action: str | None = None
    sensitivity: str | None = None
    agent_id: UUID | None = None
    department_id: UUID | None = None


class ScanRequest(BaseModel):
    """Payload for scanning content through the 4-layer DLP pipeline."""

    content: str
    direction: str = "input"
    context: dict[str, Any] | None = None
    policy_id: UUID | None = None


class ManualScanRequest(BaseModel):
    """Payload for manual policy test scan."""

    content: str
    policy_id: UUID | None = None
    detector_types: list[str] | None = None
    custom_patterns: dict[str, str] | None = None


class RedactRequest(BaseModel):
    """Payload for scanning and redacting sensitive data from text."""

    content: str


class GuardrailCheckRequest(BaseModel):
    """Payload for checking content against guardrails."""

    content: str
    config: GuardrailConfig = PField(default_factory=GuardrailConfig)


class NLPolicyCreateRequest(BaseModel):
    """Payload for creating a DLP policy from natural language."""

    policy_text: str


class PolicyEvaluateRequest(BaseModel):
    """Payload for evaluating content against tenant policies."""

    content: str
    policy_ids: list[UUID] | None = None


# ── Helpers ──────────────────────────────────────────────────────────


def _meta(*, request_id: str | None = None, **extra: Any) -> dict[str, Any]:
    """Build standard envelope meta block."""
    return {
        "request_id": request_id or str(uuid4()),
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        **extra,
    }


def _audit_event(
    user: AuthenticatedUser,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> EnterpriseAuditEvent:
    """Create an audit event record for a state-changing operation."""
    return EnterpriseAuditEvent(
        tenant_id=UUID(user.tenant_id),
        user_id=UUID(user.id),
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
        session_id=user.session_id,
    )


# ── Detector Types ──────────────────────────────────────────────────

BUILT_IN_DETECTORS: list[dict[str, str]] = [
    {
        "id": "ssn",
        "name": "Social Security Number",
        "category": "pii",
        "sensitivity": "high",
        "description": "US Social Security Numbers (XXX-XX-XXXX)",
        "icon": "shield",
    },
    {
        "id": "credit_card",
        "name": "Credit Card",
        "category": "pii",
        "sensitivity": "high",
        "description": "Visa, Mastercard, Amex with Luhn validation",
        "icon": "credit-card",
    },
    {
        "id": "email",
        "name": "Email Address",
        "category": "pii",
        "sensitivity": "medium",
        "description": "Email addresses in standard format",
        "icon": "mail",
    },
    {
        "id": "phone",
        "name": "Phone Number",
        "category": "pii",
        "sensitivity": "medium",
        "description": "US and international phone numbers",
        "icon": "phone",
    },
    {
        "id": "address",
        "name": "Street Address",
        "category": "pii",
        "sensitivity": "medium",
        "description": "Physical street addresses and postal codes",
        "icon": "map-pin",
    },
    {
        "id": "passport",
        "name": "Passport Number",
        "category": "pii",
        "sensitivity": "high",
        "description": "Passport numbers from various countries",
        "icon": "book-open",
    },
    {
        "id": "drivers_license",
        "name": "Driver's License",
        "category": "pii",
        "sensitivity": "high",
        "description": "Driver's license numbers (US formats)",
        "icon": "id-card",
    },
    {
        "id": "api_key",
        "name": "API Key",
        "category": "secret",
        "sensitivity": "high",
        "description": "API keys from major cloud providers (AWS, GCP, Azure)",
        "icon": "key",
    },
    {
        "id": "password",
        "name": "Password",
        "category": "secret",
        "sensitivity": "high",
        "description": "Passwords and credential strings in config/code",
        "icon": "lock",
    },
    {
        "id": "jwt_token",
        "name": "JWT Token",
        "category": "secret",
        "sensitivity": "high",
        "description": "JSON Web Tokens (Bearer tokens)",
        "icon": "key-round",
    },
    {
        "id": "aws_key",
        "name": "AWS Access Key",
        "category": "secret",
        "sensitivity": "critical",
        "description": "AWS access key IDs and secret keys",
        "icon": "cloud",
    },
    {
        "id": "private_key",
        "name": "Private Key",
        "category": "secret",
        "sensitivity": "critical",
        "description": "RSA, EC, DSA, PGP private key blocks",
        "icon": "file-lock",
    },
    {
        "id": "oauth_token",
        "name": "OAuth Token",
        "category": "secret",
        "sensitivity": "high",
        "description": "OAuth bearer and refresh tokens",
        "icon": "key-round",
    },
    {
        "id": "person_name",
        "name": "Person Name",
        "category": "pii",
        "sensitivity": "low",
        "description": "Person names and identifiers",
        "icon": "user",
    },
    {
        "id": "dob",
        "name": "Date of Birth",
        "category": "pii",
        "sensitivity": "medium",
        "description": "Dates of birth in common formats",
        "icon": "calendar",
    },
    {
        "id": "ip_address",
        "name": "IP Address",
        "category": "network",
        "sensitivity": "medium",
        "description": "IPv4 and IPv6 addresses",
        "icon": "globe",
    },
    {
        "id": "medical_record",
        "name": "Medical Record",
        "category": "phi",
        "sensitivity": "high",
        "description": "Medical record and health IDs (HIPAA)",
        "icon": "heart",
    },
    {
        "id": "bank_account",
        "name": "Bank Account",
        "category": "pii",
        "sensitivity": "high",
        "description": "Bank account and routing numbers",
        "icon": "landmark",
    },
    {
        "id": "custom",
        "name": "Custom Regex",
        "category": "custom",
        "sensitivity": "configurable",
        "description": "User-defined regex pattern with test preview",
        "icon": "settings",
    },
]


@router.get("/detectors")
async def list_detector_types(
    user: AuthenticatedUser = Depends(require_permission("dlp", "read")),
) -> dict[str, Any]:
    """Return built-in DLP detector types with descriptions and icons."""
    return {"data": BUILT_IN_DETECTORS, "meta": _meta()}


# ── Scan Endpoints ──────────────────────────────────────────────────


@router.post("/scan")
async def scan_content(
    body: ScanRequest,
    user: AuthenticatedUser = Depends(require_permission("dlp", "read")),
) -> dict[str, Any]:
    """Scan content through the full 4-layer DLP pipeline.

    Requires ``dlp:read`` permission. Tenant-scoped.
    """
    request_id = str(uuid4())
    result = DLPService.scan_content(
        tenant_id=user.tenant_id,
        content=body.content,
        direction=body.direction,
        context=body.context,
    )

    _audit_event(
        user,
        "dlp.scan",
        "dlp_scan",
        result.content_id,
        {"direction": body.direction, "risk_level": result.risk_level.value},
    )

    return {
        "data": result.model_dump(mode="json"),
        "meta": _meta(request_id=request_id),
    }


@router.post("/redact")
async def redact_content(
    body: RedactRequest,
    user: AuthenticatedUser = Depends(require_permission("dlp", "read")),
) -> dict[str, Any]:
    """Scan content and return a redacted version.

    Requires ``dlp:read`` permission. Tenant-scoped.
    """
    request_id = str(uuid4())

    secret_findings = DLPService.scan_for_secrets(body.content)
    pii_findings = DLPService.scan_for_pii(body.content)
    all_findings = [*secret_findings, *pii_findings]
    redacted = DLPService.redact_content(body.content, all_findings)

    _audit_event(
        user,
        "dlp.redact",
        "dlp_redact",
        None,
        {"findings_count": len(all_findings)},
    )

    return {
        "data": {
            "redacted_text": redacted,
            "findings_count": len(all_findings),
            "secrets_found": len(secret_findings),
            "pii_found": len(pii_findings),
        },
        "meta": _meta(request_id=request_id),
    }


# ── Guardrail Endpoints ────────────────────────────────────────────


@router.post("/guardrails")
async def check_guardrails(
    body: GuardrailCheckRequest,
    user: AuthenticatedUser = Depends(require_permission("dlp", "read")),
) -> dict[str, Any]:
    """Check content against input/output guardrails.

    Requires ``dlp:read`` permission. Tenant-scoped.
    """
    request_id = str(uuid4())

    result = DLPService.check_guardrails(
        tenant_id=user.tenant_id,
        content=body.content,
        guardrail_config=body.config,
    )

    _audit_event(
        user,
        "dlp.guardrail_check",
        "guardrail",
        None,
        {"passed": result.passed, "violations": len(result.violations)},
    )

    return {
        "data": result.model_dump(mode="json"),
        "meta": _meta(request_id=request_id),
    }


# ── Policy Endpoints ───────────────────────────────────────────────


@router.post("/policies", status_code=status.HTTP_201_CREATED)
async def create_nl_policy(
    body: NLPolicyCreateRequest,
    user: AuthenticatedUser = Depends(require_permission("dlp", "create")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Create a DLP policy from natural language description.

    Requires ``dlp:create`` permission. Tenant-scoped. Audit-logged.
    """
    request_id = str(uuid4())

    policy = DLPService.create_policy(
        tenant_id=user.tenant_id,
        user_id=user.id,
        policy_text_nl=body.policy_text,
    )
    session.add(policy)
    await session.commit()
    await session.refresh(policy)

    _audit_event(
        user,
        "dlp.policy_created",
        "dlp_policy",
        str(policy.id),
        {"name": policy.name, "rules_count": len(policy.rules)},
    )

    logger.info(
        "DLP policy created",
        extra={
            "request_id": request_id,
            "tenant_id": user.tenant_id,
            "policy_id": str(policy.id),
        },
    )

    return {
        "data": policy.model_dump(mode="json"),
        "meta": _meta(request_id=request_id),
    }


@router.get("/policies")
async def list_policies(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    is_active: bool | None = Query(default=None),
    user: AuthenticatedUser = Depends(require_permission("dlp", "read")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List DLP policies for the authenticated user's tenant.

    Requires ``dlp:read`` permission. Tenant-scoped, paginated.
    """
    base = select(DLPPolicy).where(DLPPolicy.tenant_id == user.tenant_id)
    if is_active is not None:
        base = base.where(DLPPolicy.is_active == is_active)

    count_result = await session.exec(base)
    total = len(count_result.all())

    stmt = (
        base.offset(offset)
        .limit(limit)
        .order_by(
            DLPPolicy.created_at.desc()  # type: ignore[union-attr]
        )
    )
    result = await session.exec(stmt)
    policies = list(result.all())

    return {
        "data": [p.model_dump(mode="json") for p in policies],
        "meta": _meta(
            pagination={"total": total, "limit": limit, "offset": offset},
        ),
    }


@router.post("/policies/evaluate")
async def evaluate_policies(
    body: PolicyEvaluateRequest,
    user: AuthenticatedUser = Depends(require_permission("dlp", "read")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Evaluate content against tenant DLP policies.

    Requires ``dlp:read`` permission. Tenant-scoped.
    """
    request_id = str(uuid4())

    # Load tenant policies
    stmt = select(DLPPolicy).where(
        DLPPolicy.tenant_id == user.tenant_id,
        DLPPolicy.is_active == True,  # noqa: E712
    )
    if body.policy_ids:
        stmt = stmt.where(DLPPolicy.id.in_(body.policy_ids))  # type: ignore[union-attr]
    result = await session.exec(stmt)
    policies = list(result.all())

    evaluations = DLPService.evaluate_policy(
        tenant_id=user.tenant_id,
        content=body.content,
        policies=policies,
    )

    _audit_event(
        user,
        "dlp.policy_evaluated",
        "dlp_policy",
        None,
        {
            "policies_count": len(policies),
            "matched_count": sum(1 for e in evaluations if e.matched),
        },
    )

    return {
        "data": [e.model_dump(mode="json") for e in evaluations],
        "meta": _meta(request_id=request_id),
    }


# ── Manual Scan (Policy Test) ──────────────────────────────────────


@router.post("/scan/test")
async def manual_scan(
    body: ManualScanRequest,
    user: AuthenticatedUser = Depends(require_permission("dlp", "read")),
) -> dict[str, Any]:
    """Manual scan for policy test feature.

    Scans provided content and returns highlighted detections with type
    labels and the action that would apply. Requires ``dlp:read``.
    """
    request_id = str(uuid4())
    import time

    start_ts = time.monotonic()

    # Run DLP scans
    secret_findings = DLPService.scan_for_secrets(body.content)
    pii_findings = DLPService.scan_for_pii(body.content)

    # Also run DLPEngine for custom patterns
    engine_hits = DLPEngine.scan_text(
        body.content,
        detector_types=body.detector_types,
        custom_patterns=body.custom_patterns or {},
    )

    detections: list[dict[str, Any]] = []
    for f in secret_findings:
        detections.append(
            {
                "type": f.pattern_name,
                "category": "secret",
                "preview": f.matched_text_preview,
                "position": list(f.position),
                "confidence": f.confidence,
                "severity": f.severity,
            }
        )
    for f in pii_findings:
        detections.append(
            {
                "type": f.pii_type,
                "category": "pii",
                "preview": f.matched_text_preview,
                "position": list(f.position),
                "confidence": f.confidence,
                "severity": "medium",
            }
        )
    for h in engine_hits:
        # Avoid duplicates from service layer
        pos = (h.start, h.end)
        if not any(d["position"] == list(pos) for d in detections):
            detections.append(
                {
                    "type": h.entity_type,
                    "category": "custom"
                    if h.entity_type
                    not in ("ssn", "credit_card", "email", "api_key", "password")
                    else "builtin",
                    "preview": h.matched_text[:8] + "..."
                    if len(h.matched_text) > 8
                    else h.matched_text,
                    "position": [h.start, h.end],
                    "confidence": h.confidence,
                    "severity": "medium",
                }
            )

    # Determine action
    full_result = DLPService.scan_content(
        tenant_id=user.tenant_id,
        content=body.content,
        direction="input",
    )
    elapsed_ms = (time.monotonic() - start_ts) * 1000.0

    # Generate redacted version
    all_findings = [*secret_findings, *pii_findings]
    redacted_text = DLPService.redact_content(body.content, all_findings)

    return {
        "data": {
            "detections": detections,
            "total_findings": len(detections),
            "risk_level": full_result.risk_level.value,
            "action": full_result.action.value,
            "redacted_text": redacted_text,
            "processing_time_ms": round(elapsed_ms, 2),
        },
        "meta": _meta(request_id=request_id),
    }


# ── Metrics ─────────────────────────────────────────────────────────


@router.get("/metrics")
async def get_metrics(
    user: AuthenticatedUser = Depends(require_permission("dlp", "read")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Return DLP metrics: scans, detections, blocked, redacted today.

    Queries scan results for the current tenant. Requires ``dlp:read``.
    """
    from datetime import timedelta
    from sqlalchemy import func
    from app.models.dlp import DLPScanResult as ScanResultModel

    request_id = str(uuid4())

    try:
        today_start = datetime.now(tz=timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

        # Total scans today
        stmt_scans = (
            select(func.count())
            .select_from(ScanResultModel)
            .where(
                ScanResultModel.tenant_id == user.tenant_id,
                ScanResultModel.created_at >= today_start,
            )
        )
        scans_result = await session.exec(stmt_scans)
        scans_today = scans_result.one_or_none() or 0

        # Total detections today (scans with findings)
        stmt_detections = (
            select(func.coalesce(func.sum(ScanResultModel.findings_count), 0))
            .select_from(ScanResultModel)
            .where(
                ScanResultModel.tenant_id == user.tenant_id,
                ScanResultModel.created_at >= today_start,
                ScanResultModel.has_findings == True,  # noqa: E712
            )
        )
        det_result = await session.exec(stmt_detections)
        detections = det_result.one_or_none() or 0

        # Blocked today
        stmt_blocked = (
            select(func.count())
            .select_from(ScanResultModel)
            .where(
                ScanResultModel.tenant_id == user.tenant_id,
                ScanResultModel.created_at >= today_start,
                ScanResultModel.action_taken == "block",
            )
        )
        blocked_result = await session.exec(stmt_blocked)
        blocked = blocked_result.one_or_none() or 0

        # Redacted today
        stmt_redacted = (
            select(func.count())
            .select_from(ScanResultModel)
            .where(
                ScanResultModel.tenant_id == user.tenant_id,
                ScanResultModel.created_at >= today_start,
                ScanResultModel.action_taken == "redact",
            )
        )
        redacted_result = await session.exec(stmt_redacted)
        redacted = redacted_result.one_or_none() or 0

        # Detection type breakdown
        stmt_types = select(ScanResultModel.entity_types_found).where(
            ScanResultModel.tenant_id == user.tenant_id,
            ScanResultModel.created_at >= today_start,
            ScanResultModel.has_findings == True,  # noqa: E712
        )
        types_result = await session.exec(stmt_types)
        type_counts: dict[str, int] = {}
        for row in types_result.all():
            if isinstance(row, list):
                for t in row:
                    type_counts[t] = type_counts.get(t, 0) + 1

        # Trend data (last 7 days)
        trend: list[dict[str, Any]] = []
        for i in range(6, -1, -1):
            day = today_start - timedelta(days=i)
            day_end = day + timedelta(days=1)
            stmt_day = (
                select(func.count())
                .select_from(ScanResultModel)
                .where(
                    ScanResultModel.tenant_id == user.tenant_id,
                    ScanResultModel.created_at >= day,
                    ScanResultModel.created_at < day_end,
                    ScanResultModel.has_findings == True,  # noqa: E712
                )
            )
            day_result = await session.exec(stmt_day)
            count = day_result.one_or_none() or 0
            trend.append(
                {
                    "date": day.strftime("%Y-%m-%d"),
                    "detections": count,
                }
            )
    except Exception:
        scans_today = 0
        detections = 0
        blocked = 0
        redacted = 0
        type_counts = {}
        today_start = datetime.now(tz=timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        trend = [
            {
                "date": (
                    today_start - __import__("datetime").timedelta(days=i)
                ).strftime("%Y-%m-%d"),
                "detections": 0,
            }
            for i in range(6, -1, -1)
        ]

    return {
        "data": {
            "scans_today": scans_today,
            "detections": detections,
            "blocked": blocked,
            "redacted": redacted,
            "type_breakdown": type_counts,
            "trend": trend,
        },
        "meta": _meta(request_id=request_id),
    }


# ── Recent Detections ──────────────────────────────────────────────


@router.get("/detections")
async def list_detections(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: AuthenticatedUser = Depends(require_permission("dlp", "read")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Return recent DLP detections for the tenant.

    Paginated list of scan results with findings. Requires ``dlp:read``.
    """
    from app.models.dlp import DLPScanResult as ScanResultModel

    request_id = str(uuid4())

    base = select(ScanResultModel).where(
        ScanResultModel.tenant_id == user.tenant_id,
        ScanResultModel.has_findings == True,  # noqa: E712
    )

    # Count
    count_result = await session.exec(base)
    total = len(count_result.all())

    # Paginated results
    stmt = (
        base.offset(offset)
        .limit(limit)
        .order_by(
            ScanResultModel.created_at.desc()  # type: ignore[union-attr]
        )
    )
    result = await session.exec(stmt)
    detections = list(result.all())

    return {
        "data": [
            {
                "id": str(d.id),
                "source": d.source,
                "entity_types": d.entity_types_found,
                "findings_count": d.findings_count,
                "action_taken": d.action_taken,
                "created_at": d.created_at.isoformat() if d.created_at else None,
                "text_hash": d.text_hash[:12] + "..." if d.text_hash else None,
            }
            for d in detections
        ],
        "meta": _meta(
            request_id=request_id,
            pagination={"total": total, "limit": limit, "offset": offset},
        ),
    }


# ── Enhanced Policy CRUD ───────────────────────────────────────────


@router.post("/policies/create", status_code=status.HTTP_201_CREATED)
async def create_structured_policy(
    body: DLPPolicyCreate,
    user: AuthenticatedUser = Depends(require_permission("dlp", "create")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Create a DLP policy from structured form data (detector card grid).

    Requires ``dlp:create`` permission. Tenant-scoped. Audit-logged.
    """
    request_id = str(uuid4())

    policy = DLPPolicy(
        tenant_id=user.tenant_id,
        name=body.name,
        description=body.description,
        is_active=body.is_active,
        detector_types=body.detector_types,
        custom_patterns=body.custom_patterns,
        action=body.action,
        sensitivity=body.sensitivity,
        agent_id=body.agent_id,
        department_id=body.department_id,
    )
    session.add(policy)
    await session.commit()
    await session.refresh(policy)

    _audit_event(
        user,
        "dlp.policy_created",
        "dlp_policy",
        str(policy.id),
        {"name": policy.name, "detectors": body.detector_types},
    )

    return {
        "data": policy.model_dump(mode="json"),
        "meta": _meta(request_id=request_id),
    }


@router.put("/policies/{policy_id}")
async def update_policy(
    policy_id: UUID,
    body: DLPPolicyUpdate,
    user: AuthenticatedUser = Depends(require_permission("dlp", "update")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Update an existing DLP policy with detector cards.

    Requires ``dlp:update`` permission. Tenant-scoped. Audit-logged.
    """
    request_id = str(uuid4())

    policy = await session.get(DLPPolicy, policy_id)
    if not policy or policy.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="Policy not found")

    update_data = body.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        if hasattr(policy, key):
            setattr(policy, key, value)

    policy.updated_at = utcnow()
    session.add(policy)
    await session.commit()
    await session.refresh(policy)

    _audit_event(
        user,
        "dlp.policy_updated",
        "dlp_policy",
        str(policy.id),
        {"updated_fields": list(update_data.keys())},
    )

    return {
        "data": policy.model_dump(mode="json"),
        "meta": _meta(request_id=request_id),
    }


@router.get("/policies/{policy_id}/stats")
async def get_policy_stats(
    policy_id: UUID,
    user: AuthenticatedUser = Depends(require_permission("dlp", "read")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Return detection statistics for a specific policy.

    Requires ``dlp:read`` permission. Tenant-scoped.
    """
    from sqlalchemy import func
    from app.models.dlp import DLPScanResult as ScanResultModel

    request_id = str(uuid4())

    # Verify policy exists and belongs to tenant
    policy = await session.get(DLPPolicy, policy_id)
    if not policy or policy.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="Policy not found")

    # Total scans using this policy
    stmt_total = (
        select(func.count())
        .select_from(ScanResultModel)
        .where(ScanResultModel.policy_id == policy_id)
    )
    total_result = await session.exec(stmt_total)
    total_scans = total_result.one_or_none() or 0

    # Total findings
    stmt_findings = (
        select(func.coalesce(func.sum(ScanResultModel.findings_count), 0))
        .select_from(ScanResultModel)
        .where(
            ScanResultModel.policy_id == policy_id,
            ScanResultModel.has_findings == True,  # noqa: E712
        )
    )
    findings_result = await session.exec(stmt_findings)
    total_findings = findings_result.one_or_none() or 0

    # Action breakdown
    action_breakdown: dict[str, int] = {}
    for action_val in ["block", "redact", "allow", "none"]:
        stmt_action = (
            select(func.count())
            .select_from(ScanResultModel)
            .where(
                ScanResultModel.policy_id == policy_id,
                ScanResultModel.action_taken == action_val,
            )
        )
        action_result = await session.exec(stmt_action)
        count = action_result.one_or_none() or 0
        if count > 0:
            action_breakdown[action_val] = count

    return {
        "data": {
            "policy_id": str(policy_id),
            "policy_name": policy.name,
            "total_scans": total_scans,
            "total_findings": total_findings,
            "action_breakdown": action_breakdown,
            "is_active": policy.is_active,
        },
        "meta": _meta(request_id=request_id),
    }
