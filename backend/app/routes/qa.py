"""QA Workflow Trigger endpoints.

Provides manual triggering, status polling, and a Logic Apps callback webhook.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field as PField
from sqlmodel.ext.asyncio.session import AsyncSession

from app.database import get_session
from app.logging_config import get_logger
from app.services.qa_trigger_service import QATriggerService

router = APIRouter(prefix="/qa", tags=["qa"])
logger = get_logger(__name__)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _meta(**extra: Any) -> dict[str, Any]:
    return {
        "request_id": str(uuid4()),
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        **extra,
    }


def _request_to_dict(req: Any) -> dict[str, Any]:
    return {
        "id": req.id,
        "workflow_id": req.workflow_id,
        "workflow_run_id": req.workflow_run_id,
        "trigger_source": req.trigger_source,
        "status": req.status,
        "logic_apps_run_id": req.logic_apps_run_id,
        "request_payload": req.request_payload,
        "response_payload": req.response_payload,
        "callback_received": req.callback_received,
        "tenant_id": req.tenant_id,
        "created_at": req.created_at.isoformat() if req.created_at else None,
        "updated_at": req.updated_at.isoformat() if req.updated_at else None,
        "completed_at": req.completed_at.isoformat() if req.completed_at else None,
        "error_message": req.error_message,
    }


# ── Request schemas ───────────────────────────────────────────────────────────


class QATriggerRequest(BaseModel):
    workflow_id: str | None = None
    workflow_run_id: str | None = None
    trigger_source: str = "manual"
    tenant_id: str | None = None
    payload: dict[str, Any] = PField(default_factory=dict)


class QACallbackPayload(BaseModel):
    """Payload sent by Logic Apps on completion."""

    status: str = "completed"
    error_message: str | None = None
    result: dict[str, Any] = PField(default_factory=dict)


# ── Routes ────────────────────────────────────────────────────────────────────


@router.post("/trigger", status_code=201)
async def trigger_qa(
    body: QATriggerRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Manually trigger a QA workflow via Azure Logic Apps.

    Creates a QAWorkflowRequest record and POSTs to the configured Logic Apps endpoint.
    Gracefully degrades if the endpoint is not configured.
    """
    request = await QATriggerService.trigger_qa(
        session,
        workflow_id=body.workflow_id,
        workflow_run_id=body.workflow_run_id,
        payload=body.payload,
        trigger_source=body.trigger_source,
        tenant_id=body.tenant_id,
    )
    return {"data": _request_to_dict(request), "meta": _meta()}


@router.get("/requests")
async def list_requests(
    tenant_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List QA workflow requests with optional filtering."""
    items, total = await QATriggerService.list_requests(
        session,
        tenant_id=tenant_id,
        status_filter=status,
        limit=limit,
        offset=offset,
    )
    return {
        "data": [_request_to_dict(r) for r in items],
        "meta": _meta(pagination={"total": total, "limit": limit, "offset": offset}),
    }


@router.get("/requests/{request_id}")
async def get_request(
    request_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get a single QA request by ID."""
    request = await QATriggerService.get_request(session, request_id)
    if request is None:
        raise HTTPException(status_code=404, detail="QA request not found")
    return {"data": _request_to_dict(request), "meta": _meta()}


@router.post("/webhook")
async def logic_apps_callback(
    body: dict[str, Any],
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Receive a callback from Azure Logic Apps after QA completes.

    This endpoint is intentionally unauthenticated so Logic Apps can reach it.
    Correlation is done via ``logic_apps_run_id`` in the request body.
    """
    logic_apps_run_id = body.get("run_id") or body.get("logic_apps_run_id")
    if not logic_apps_run_id:
        raise HTTPException(
            status_code=400,
            detail="Missing 'run_id' or 'logic_apps_run_id' in payload",
        )

    request = await QATriggerService.handle_callback(
        session,
        logic_apps_run_id=logic_apps_run_id,
        result=body,
    )
    if request is None:
        # Accept gracefully — Logic Apps may send duplicate callbacks
        logger.warning("qa_webhook_no_match", logic_apps_run_id=logic_apps_run_id)
        return {"status": "accepted", "matched": False, "meta": _meta()}

    return {
        "status": "accepted",
        "matched": True,
        "data": _request_to_dict(request),
        "meta": _meta(),
    }


@router.get("/status/{request_id}")
async def get_status(
    request_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Lightweight status check for a QA request."""
    request = await QATriggerService.get_request(session, request_id)
    if request is None:
        raise HTTPException(status_code=404, detail="QA request not found")
    return {
        "data": {
            "id": request.id,
            "status": request.status,
            "logic_apps_run_id": request.logic_apps_run_id,
            "callback_received": request.callback_received,
            "completed_at": request.completed_at.isoformat()
            if request.completed_at
            else None,
            "error_message": request.error_message,
        },
        "meta": _meta(),
    }
