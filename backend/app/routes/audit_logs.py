"""AuditLog read-only endpoints (append-only resource)."""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.services import AuditLogService

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
    limit: int,
    offset: int,
) -> tuple[list[Any], int]:
    """Shared query logic for list and export endpoints."""
    if resource_type and resource_id:
        return await AuditLogService.list_by_resource(
            session,
            resource_type=resource_type,
            resource_id=resource_id,
            limit=limit,
            offset=offset,
        )
    elif actor_id:
        return await AuditLogService.list_by_actor(
            session,
            actor_id=actor_id,
            limit=limit,
            offset=offset,
        )
    else:
        return await AuditLogService.list_all(
            session, limit=limit, offset=offset,
        )


# ── Routes ───────────────────────────────────────────────────────────


@router.get("/export")
async def export_audit_logs(
    format: str = Query(default="json", pattern="^(json|csv)$"),
    resource_type: str | None = Query(default=None),
    resource_id: UUID | None = Query(default=None),
    actor_id: UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=10000),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> Any:
    """Export audit log entries as JSON or CSV."""
    entries, total = await _fetch_entries(
        session,
        resource_type=resource_type,
        resource_id=resource_id,
        actor_id=actor_id,
        limit=limit,
        offset=offset,
    )
    rows = [e.model_dump(mode="json") for e in entries]

    if format == "csv":
        buf = io.StringIO()
        fieldnames = ["id", "actor_id", "action", "resource_type", "resource_id", "details", "created_at"]
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


@router.get("/")
async def list_audit_logs(
    resource_type: str | None = Query(default=None),
    resource_id: UUID | None = Query(default=None),
    actor_id: UUID | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List audit log entries with filters.

    Either filter by resource (resource_type + resource_id) or by actor_id.
    """
    entries, total = await _fetch_entries(
        session,
        resource_type=resource_type,
        resource_id=resource_id,
        actor_id=actor_id,
        limit=limit,
        offset=offset,
    )
    return {
        "data": [e.model_dump(mode="json") for e in entries],
        "meta": _meta(
            pagination={"total": total, "limit": limit, "offset": offset},
        ),
    }
