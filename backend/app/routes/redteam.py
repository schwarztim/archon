"""API routes for the Red-Teaming & Adversarial Testing Engine."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field as PField

from app.interfaces.models.enterprise import AuthenticatedUser
from app.middleware.auth import get_current_user
from app.middleware.rbac import check_permission
from app.models.redteam import (
    AttackCategory,
    SecurityScanConfig,
    Severity,
)
from app.services.redteam_service import RedTeamService

router = APIRouter(prefix="/api/v1", tags=["security"])

# ── Module-level service instance ───────────────────────────────────

_redteam_service = RedTeamService()


# ── Request / response schemas ──────────────────────────────────────


class ScanRequest(BaseModel):
    """Payload for initiating a red-team security scan."""

    agent_id: UUID
    attack_categories: list[AttackCategory] = PField(
        default_factory=lambda: list(AttackCategory),
    )
    severity_threshold: Severity = Severity.low
    max_duration_seconds: int = PField(default=300, ge=10, le=3600)


class PromptInjectionRequest(BaseModel):
    """Payload for running prompt injection tests with custom payloads."""

    agent_id: UUID
    payloads: list[str] = PField(default_factory=list)


# ── Helpers ──────────────────────────────────────────────────────────


def _meta(*, request_id: str | None = None, **extra: Any) -> dict[str, Any]:
    """Build standard envelope meta block."""
    return {
        "request_id": request_id or str(uuid4()),
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        **extra,
    }


def _require_security_admin(user: AuthenticatedUser) -> None:
    """Raise HTTP 403 unless the user holds security_admin or admin role."""
    has_access = (
        check_permission(user, "security", "admin")
        or check_permission(user, "security", "execute")
        or "security_admin" in user.roles
        or "admin" in user.roles
    )
    if not has_access:
        raise HTTPException(
            status_code=403,
            detail="Permission denied: security_admin role required",
        )


# ── Routes ───────────────────────────────────────────────────────────


@router.post("/security/scan", status_code=201)
async def run_security_scan(
    body: ScanRequest,
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Run a full red-team security scan against an agent."""
    _require_security_admin(user)

    config = SecurityScanConfig(
        attack_categories=body.attack_categories,
        severity_threshold=body.severity_threshold,
        max_duration_seconds=body.max_duration_seconds,
    )

    result = await _redteam_service.run_security_scan(
        tenant_id=user.tenant_id,
        user_id=user.id,
        agent_id=body.agent_id,
        scan_config=config,
    )

    return {"data": result.model_dump(mode="json"), "meta": _meta()}


@router.get("/security/scan/{scan_id}")
async def get_scan_result(
    scan_id: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Retrieve a specific security scan result."""
    _require_security_admin(user)

    result = await _redteam_service.get_scan_result(
        tenant_id=user.tenant_id,
        scan_id=scan_id,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Scan not found")
    return {"data": result.model_dump(mode="json"), "meta": _meta()}


@router.get("/security/scan/{scan_id}/sarif")
async def get_sarif_report(
    scan_id: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Get SARIF JSON report for a scan (GitHub Security tab compatible)."""
    _require_security_admin(user)

    result = await _redteam_service.get_scan_result(
        tenant_id=user.tenant_id,
        scan_id=scan_id,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Scan not found")

    sarif_json = _redteam_service.generate_sarif_report(result)
    return {"data": {"sarif": sarif_json}, "meta": _meta()}


@router.get("/agents/{agent_id}/security/history")
async def get_scan_history(
    agent_id: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Get security scan history for an agent."""
    _require_security_admin(user)

    history = await _redteam_service.get_scan_history(
        tenant_id=user.tenant_id,
        agent_id=agent_id,
    )
    return {
        "data": [r.model_dump(mode="json") for r in history],
        "meta": _meta(pagination={"total": len(history)}),
    }


__all__ = ["router"]
