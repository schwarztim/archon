"""AuditLog read-only endpoints (append-only resource)."""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.middleware.auth import get_current_user
from app.interfaces.models.enterprise import AuthenticatedUser
from app.services import AuditLogService
from app.services.audit_service import AuditService

router = APIRouter(prefix="/audit-logs", tags=["audit-logs"])


# ── Helpers ──────────────────────────────────────────────────────────


def _meta(*, request_id: str | None = None, **extra: Any) -> dict[str, Any]:
    """Build standard envelope meta block."""
    return {
        "request_id": request_id or str(uuid4()),
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        **extra,
    }


async def _fetch_entries(
    session: AsyncSession,
    *,
    resource_type: str | None,
    resource_id: UUID | None,
    actor_id: UUID | None,
    action: str | None = None,
    search: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int,
    offset: int,
) -> tuple[list[Any], int]:
    """Shared query logic for list and export endpoints."""
    try:
        return await AuditLogService.list_filtered(
            session,
            resource_type=resource_type,
            resource_id=resource_id,
            actor_id=actor_id,
            action=action,
            search=search,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            offset=offset,
        )
    except Exception:
        # Empty DB or table-not-found → return empty list, never 500
        return [], 0


# ── Routes ───────────────────────────────────────────────────────────


@router.get("/export")
async def export_audit_logs(
    format: str = Query(default="json", pattern="^(json|csv)$"),
    resource_type: str | None = Query(default=None),
    resource_id: UUID | None = Query(default=None),
    actor_id: UUID | None = Query(default=None),
    action: str | None = Query(default=None),
    search: str | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=10000),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
    _user: AuthenticatedUser = Depends(get_current_user),
) -> Any:
    """Export audit log entries as JSON or CSV."""
    entries, total = await _fetch_entries(
        session,
        resource_type=resource_type,
        resource_id=resource_id,
        actor_id=actor_id,
        action=action,
        search=search,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )
    rows = [e.model_dump(mode="json") for e in entries] if entries else []

    if format == "csv":
        buf = io.StringIO()
        fieldnames = [
            "id",
            "tenant_id",
            "correlation_id",
            "actor_id",
            "action",
            "resource_type",
            "resource_id",
            "status_code",
            "ip_address",
            "details",
            "hash",
            "prev_hash",
            "created_at",
        ]
        writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        buf.seek(0)
        return StreamingResponse(
            buf,
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=audit_logs.csv"},
        )

    return {
        "data": rows,
        "meta": _meta(pagination={"total": total, "limit": limit, "offset": offset}),
    }


@router.get("/verify-chain")
async def verify_audit_chain(
    tenant_id: str = Query(
        ..., description="Tenant ID whose hash chain should be verified"
    ),
    session: AsyncSession = Depends(get_session),
    _user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Verify the tamper-evident hash chain for a tenant's audit logs.

    Walks every entry in chronological order and checks that each
    entry's ``prev_hash`` matches the previous entry's ``hash``, and
    that the stored ``hash`` matches the recomputed value.

    Returns a summary with ``valid`` (bool), ``entries`` (int), and
    a list of ``errors`` (empty when the chain is intact).
    """
    try:
        result = await AuditService.verify_chain(
            session=session,
            tenant_id=tenant_id,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Chain verification failed: {exc}",
        ) from exc

    return {
        "data": result,
        "meta": _meta(),
    }


@router.get("/")
async def list_audit_logs(
    resource_type: str | None = Query(default=None),
    resource_id: UUID | None = Query(default=None),
    actor_id: UUID | None = Query(default=None),
    action: str | None = Query(default=None),
    search: str | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
    _user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """List audit log entries with filters.

    Requires at least one of: resource_type, actor_id, action, search, or date range.
    Dispatches to resource or actor-scoped service methods when those filters are provided.
    """
    has_filter = any([resource_type, actor_id, action, search, date_from, date_to])
    if not has_filter:
        raise HTTPException(status_code=422, detail="At least one filter is required.")

    if resource_type is not None and resource_id is None:
        raise HTTPException(
            status_code=422,
            detail="resource_id is required when resource_type is provided.",
        )

    if resource_type is not None:
        entries, total = await AuditLogService.list_by_resource(
            session,
            resource_type=resource_type,
            resource_id=resource_id,
            limit=limit,
            offset=offset,
        )
    elif actor_id is not None:
        entries, total = await AuditLogService.list_by_actor(
            session,
            actor_id=actor_id,
            limit=limit,
            offset=offset,
        )
    else:
        entries, total = await _fetch_entries(
            session,
            resource_type=resource_type,
            resource_id=resource_id,
            actor_id=actor_id,
            action=action,
            search=search,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            offset=offset,
        )
    return {
        "data": [e.model_dump(mode="json") for e in entries] if entries else [],
        "meta": _meta(
            pagination={"total": total, "limit": limit, "offset": offset},
        ),
    }


# ── Immutability enforcement ─────────────────────────────────────────


@router.api_route(
    "/{path:path}",
    methods=["PUT", "DELETE"],
    include_in_schema=False,
)
async def block_mutations(
    _user: AuthenticatedUser = Depends(get_current_user),
) -> JSONResponse:
    """Audit logs are immutable — reject PUT/DELETE with 405."""
    return JSONResponse(
        status_code=405,
        content={
            "data": None,
            "meta": _meta(),
            "errors": [
                {"code": "METHOD_NOT_ALLOWED", "message": "Audit logs are immutable"}
            ],
        },
    )
