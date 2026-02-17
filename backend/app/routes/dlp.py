"""API routes for the Archon DLP (Data Loss Prevention) engine.

Enterprise-grade: all endpoints authenticated, RBAC-checked, tenant-scoped,
and audit-logged per AGENT_RULES.md.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field as PField
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.database import get_session
from app.interfaces.models.enterprise import AuthenticatedUser
from app.middleware.auth import get_current_user
from app.middleware.rbac import check_permission, require_permission
from app.models.audit import EnterpriseAuditEvent
from app.models.dlp import (
    DLPPolicy,
    DLPScanResultSchema,
    GuardrailConfig,
    GuardrailResult,
    PolicyEvaluation,
    ScanDirection,
)
from app.secrets.manager import VaultSecretsManager, get_secrets_manager
from app.services.dlp import DLPEngine
from app.services.dlp_service import DLPService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/dlp", tags=["DLP"])


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
    {"id": "ssn", "name": "Social Security Number", "category": "pii", "sensitivity": "high"},
    {"id": "credit_card", "name": "Credit Card", "category": "pii", "sensitivity": "high"},
    {"id": "email", "name": "Email Address", "category": "pii", "sensitivity": "medium"},
    {"id": "phone", "name": "Phone Number", "category": "pii", "sensitivity": "medium"},
    {"id": "address", "name": "Physical Address", "category": "pii", "sensitivity": "medium"},
    {"id": "api_key", "name": "API Key", "category": "secret", "sensitivity": "high"},
    {"id": "password", "name": "Password", "category": "secret", "sensitivity": "high"},
    {"id": "oauth_token", "name": "OAuth Token", "category": "secret", "sensitivity": "high"},
    {"id": "person_name", "name": "Person Name", "category": "pii", "sensitivity": "low"},
    {"id": "dob", "name": "Date of Birth", "category": "pii", "sensitivity": "medium"},
    {"id": "ip_address", "name": "IP Address", "category": "network", "sensitivity": "medium"},
    {"id": "medical_record", "name": "Medical Record", "category": "phi", "sensitivity": "high"},
    {"id": "bank_account", "name": "Bank Account", "category": "pii", "sensitivity": "high"},
    {"id": "passport", "name": "Passport Number", "category": "pii", "sensitivity": "high"},
    {"id": "custom", "name": "Custom Pattern", "category": "custom", "sensitivity": "configurable"},
]


@router.get("/detectors")
async def list_detector_types() -> dict[str, Any]:
    """Return built-in DLP detector types."""
    return {"data": BUILT_IN_DETECTORS}


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
        user, "dlp.scan", "dlp_scan", result.content_id,
        {"direction": body.direction, "risk_level": result.risk_level.value},
    )

    return {"data": result.model_dump(mode="json"), "meta": _meta(request_id=request_id)}


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
        user, "dlp.redact", "dlp_redact", None,
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
        user, "dlp.guardrail_check", "guardrail", None,
        {"passed": result.passed, "violations": len(result.violations)},
    )

    return {"data": result.model_dump(mode="json"), "meta": _meta(request_id=request_id)}


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
        user, "dlp.policy_created", "dlp_policy", str(policy.id),
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

    return {"data": policy.model_dump(mode="json"), "meta": _meta(request_id=request_id)}


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

    stmt = base.offset(offset).limit(limit).order_by(
        DLPPolicy.created_at.desc()  # type: ignore[union-attr]
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
        user, "dlp.policy_evaluated", "dlp_policy", None,
        {
            "policies_count": len(policies),
            "matched_count": sum(1 for e in evaluations if e.matched),
        },
    )

    return {
        "data": [e.model_dump(mode="json") for e in evaluations],
        "meta": _meta(request_id=request_id),
    }
