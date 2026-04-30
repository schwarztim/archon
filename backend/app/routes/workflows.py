"""Workflow orchestration endpoints.

DB-backed storage using SQLModel / AsyncSession.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone

from app.utils.time import utcnow
from typing import Any
from uuid import UUID, uuid4

import redis.asyncio as aioredis

from fastapi import (
    APIRouter,
    Body,
    Depends,
    Header,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
)
from pydantic import BaseModel, Field as PField
from sqlalchemy import select
from sqlmodel import delete as sql_delete
from sqlmodel.ext.asyncio.session import AsyncSession

from starlette.responses import Response
from app.database import get_session
from app.models.workflow import Workflow, WorkflowRun, WorkflowRunStep, WorkflowSchedule
from app.services.workflow_engine import (
    WorkflowEngineError,
    WorkflowValidationError,
    execute_workflow_dag,
)

router = APIRouter(prefix="/workflows", tags=["workflows"])
logger = logging.getLogger(__name__)

# ── Redis pub/sub helper ─────────────────────────────────────────────

_REDIS_URL = os.getenv("ARCHON_REDIS_URL", "redis://redis:6379/0")


async def _get_redis_client() -> aioredis.Redis:
    """Return an async Redis client from the configured URL."""
    return aioredis.from_url(_REDIS_URL, decode_responses=True)


# ── Default tenant for unauthenticated routes ────────────────────────
_DEFAULT_TENANT = UUID("00000000-0000-0000-0000-000000000000")


# ── Helpers ─────────────────────────────────────────────────────────


def _meta(*, request_id: str | None = None, **extra: Any) -> dict[str, Any]:
    return {
        "request_id": request_id or str(uuid4()),
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        **extra,
    }


def _workflow_to_dict(wf: Workflow) -> dict[str, Any]:
    return {
        "id": str(wf.id),
        "name": wf.name,
        "description": wf.description,
        "group_id": wf.group_id,
        "group_name": wf.group_name,
        "steps": wf.steps or [],
        "graph_definition": wf.graph_definition,
        "schedule": wf.schedule,
        "is_active": wf.is_active,
        "created_at": wf.created_at.isoformat() if wf.created_at else None,
        "updated_at": wf.updated_at.isoformat() if wf.updated_at else None,
        "created_by": wf.created_by,
    }


def _run_to_dict(
    run: WorkflowRun, steps: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    d: dict[str, Any] = {
        "id": str(run.id),
        "workflow_id": str(run.workflow_id),
        "status": run.status,
        "trigger_type": run.trigger_type,
        "triggered_by": run.triggered_by,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "duration_ms": run.duration_ms,
        "input_data": run.input_data,
        "steps": steps or [],
    }
    if run.error:
        d["error"] = run.error
    return d


def _step_to_dict(step: WorkflowRunStep) -> dict[str, Any]:
    d: dict[str, Any] = {
        "id": str(step.id),
        "run_id": str(step.run_id),
        "step_id": step.step_id,
        "name": step.name,
        "status": step.status,
        "started_at": step.started_at.isoformat() if step.started_at else None,
        "completed_at": step.completed_at.isoformat() if step.completed_at else None,
        "duration_ms": step.duration_ms,
        "input_data": step.input_data,
        "output_data": step.output_data,
        "agent_execution_id": step.agent_execution_id,
    }
    if step.error:
        d["error"] = step.error
    return d


def _compute_next_runs(
    cron: str, count: int = 5, timezone_str: str = "UTC"
) -> list[str]:
    """Compute next N approximate run times from a cron expression."""
    if not cron:
        return []
    parts = cron.split()
    if len(parts) != 5:
        return []
    min_str, hour_str, dom_str, _mon_str, dow_str = parts
    target_min = 0 if min_str == "*" else int(min_str)
    target_hour = None if hour_str == "*" else int(hour_str)
    now = utcnow()
    results: list[str] = []
    candidate = now.replace(second=0, microsecond=0)
    for _ in range(count * 400):
        candidate = candidate.replace(minute=target_min)
        if target_hour is not None:
            candidate = candidate.replace(hour=target_hour)
        if candidate > now and len(results) < count:
            # Check day-of-week filter
            if dow_str != "*":
                allowed_days = [int(d) for d in dow_str.split(",")]
                py_dow = (candidate.weekday() + 1) % 7  # 0=Sun
                if py_dow not in allowed_days:
                    candidate = candidate.replace(hour=0, minute=0)
                    from datetime import timedelta

                    candidate += timedelta(days=1)
                    continue
            # Check day-of-month filter
            if dom_str != "*":
                if candidate.day != int(dom_str):
                    from datetime import timedelta

                    candidate += timedelta(days=1)
                    continue
            results.append(candidate.isoformat())
            if len(results) >= count:
                break
        # Advance
        if target_hour is not None:
            from datetime import timedelta

            candidate += timedelta(days=1)
        else:
            from datetime import timedelta

            candidate += timedelta(hours=1)
    return results


# ── Request schemas ─────────────────────────────────────────────────


class WorkflowStepCreate(BaseModel):
    name: str
    agent_id: str
    config: dict[str, Any] = PField(default_factory=dict)
    depends_on: list[str] = PField(default_factory=list)
    # Optional top-level node_type / type so the REST surface can persist them
    # alongside config.node_type. _normalize_steps already falls back to
    # config.node_type, but lifting them at create time makes the persisted
    # JSON shape canonical and survives downstream re-loads.
    node_type: str | None = None
    type: str | None = None


def _lift_step_node_type(step: dict[str, Any]) -> dict[str, Any]:
    """Lift node_type / type from step.config to top-level on persisted steps.

    The REST `WorkflowStepCreate` schema accepts either a top-level node_type
    or one nested under `config`. After serializing for storage we copy the
    nested value to the top so workflow_engine sees node_type without needing
    to peek into config. Idempotent.
    """
    config = step.get("config") or {}
    if not isinstance(config, dict):
        return step
    nt = (
        step.get("node_type")
        or config.get("node_type")
        or config.get("type")
        or config.get("nodeType")
    )
    tp = (
        step.get("type")
        or config.get("type")
        or nt
    )
    if nt is not None:
        step["node_type"] = nt
    if tp is not None:
        step["type"] = tp
    return step


class WorkflowCreate(BaseModel):
    name: str
    description: str = ""
    group_id: str = ""
    group_name: str = ""
    steps: list[WorkflowStepCreate] = PField(default_factory=list)
    graph_definition: dict[str, Any] | None = None
    schedule: str | None = None
    is_active: bool = True
    created_by: str = ""


class WorkflowUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    group_id: str | None = None
    group_name: str | None = None
    steps: list[WorkflowStepCreate] | None = None
    graph_definition: dict[str, Any] | None = None
    schedule: str | None = None
    is_active: bool | None = None


class ScheduleSet(BaseModel):
    """Request body for setting a workflow schedule."""

    cron: str
    timezone: str = "UTC"


# ── Routes ──────────────────────────────────────────────────────────


@router.get("/")
async def list_workflows(
    search: str | None = Query(default=None),
    group_id: str | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List workflows with optional search, group, and status filters."""
    stmt = select(Workflow)
    if search:
        q = f"%{search.lower()}%"
        from sqlalchemy import or_, func

        stmt = stmt.where(
            or_(
                func.lower(Workflow.name).like(q),
                func.lower(Workflow.description).like(q),
            )
        )
    if group_id:
        stmt = stmt.where(Workflow.group_id == group_id)
    if is_active is not None:
        stmt = stmt.where(Workflow.is_active == is_active)

    result = await session.exec(stmt)
    all_wf = result.all()
    total = len(all_wf)
    page = all_wf[offset : offset + limit]
    return {
        "data": [_workflow_to_dict(w) for w in page],
        "meta": _meta(pagination={"total": total, "limit": limit, "offset": offset}),
    }


@router.post("/", status_code=201)
async def create_workflow(
    body: WorkflowCreate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Create a new workflow."""
    steps = [
        _lift_step_node_type(
            {
                "step_id": str(uuid4()),
                "name": s.name,
                "agent_id": s.agent_id,
                "config": s.config,
                "depends_on": s.depends_on,
                "node_type": s.node_type,
                "type": s.type,
            }
        )
        for s in body.steps
    ]
    wf = Workflow(
        tenant_id=_DEFAULT_TENANT,
        name=body.name,
        description=body.description,
        group_id=body.group_id,
        group_name=body.group_name,
        steps=steps,
        graph_definition=body.graph_definition,
        schedule=body.schedule,
        is_active=body.is_active,
        created_by=body.created_by,
    )
    session.add(wf)
    await session.commit()
    await session.refresh(wf)
    return {"data": _workflow_to_dict(wf), "meta": _meta()}


@router.get("/{workflow_id}")
async def get_workflow(
    workflow_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get a single workflow by ID."""
    wf = await session.get(Workflow, UUID(workflow_id))
    if wf is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return {"data": _workflow_to_dict(wf), "meta": _meta()}


@router.put("/{workflow_id}")
async def update_workflow(
    workflow_id: str,
    body: WorkflowUpdate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Update an existing workflow."""
    wf = await session.get(Workflow, UUID(workflow_id))
    if wf is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    updates = body.model_dump(exclude_unset=True)
    if "steps" in updates and updates["steps"] is not None:
        updates["steps"] = [
            _lift_step_node_type(
                {
                    "step_id": str(uuid4()),
                    "name": s.name,
                    "agent_id": s.agent_id,
                    "config": s.config,
                    "depends_on": s.depends_on,
                    "node_type": s.node_type,
                    "type": s.type,
                }
            )
            for s in body.steps  # type: ignore[union-attr]
        ]
    for key, value in updates.items():
        setattr(wf, key, value)
    wf.updated_at = datetime.utcnow()
    session.add(wf)
    await session.commit()
    await session.refresh(wf)
    return {"data": _workflow_to_dict(wf), "meta": _meta()}


@router.delete("/{workflow_id}", status_code=204, response_class=Response)
async def delete_workflow(
    workflow_id: str,
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Delete a workflow."""
    wf = await session.get(Workflow, UUID(workflow_id))
    if wf is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    # Delete child WorkflowRunStep records first
    run_ids_stmt = select(WorkflowRun.id).where(
        WorkflowRun.workflow_id == UUID(workflow_id)
    )
    await session.exec(
        sql_delete(WorkflowRunStep).where(WorkflowRunStep.run_id.in_(run_ids_stmt))
    )
    # Delete child WorkflowRun records
    await session.exec(
        sql_delete(WorkflowRun).where(WorkflowRun.workflow_id == UUID(workflow_id))
    )
    # Delete child WorkflowSchedule records
    await session.exec(
        sql_delete(WorkflowSchedule).where(
            WorkflowSchedule.workflow_id == UUID(workflow_id)
        )
    )
    # Now delete the workflow
    await session.delete(wf)
    await session.commit()
    return Response(status_code=204)


@router.post("/{workflow_id}/execute", status_code=201)
async def execute_workflow(
    workflow_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Execute a workflow using the LangGraph engine."""
    wf = await session.get(Workflow, UUID(workflow_id))
    if wf is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    wf_dict = _workflow_to_dict(wf)
    now = datetime.utcnow()
    run = WorkflowRun(
        workflow_id=wf.id,
        tenant_id=wf.tenant_id,
        status="running",
        trigger_type="manual",
        triggered_by=wf.created_by,
        started_at=now,
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)

    try:
        result = await execute_workflow_dag(wf_dict)
    except WorkflowValidationError as exc:
        run.status = "failed"
        run.error = str(exc)
        run.completed_at = datetime.utcnow()
        session.add(run)
        await session.commit()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except WorkflowEngineError as exc:
        logger.error(
            "workflow.execution.failed",
            exc_info=True,
            extra={"workflow_id": workflow_id},
        )
        run.status = "failed"
        run.error = str(exc)
        run.completed_at = datetime.utcnow()
        session.add(run)
        await session.commit()
        raise HTTPException(
            status_code=500, detail="Workflow execution failed"
        ) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "workflow.execution.unexpected_error",
            extra={"workflow_id": workflow_id},
        )
        run.status = "failed"
        run.error = str(exc)
        run.completed_at = datetime.utcnow()
        session.add(run)
        await session.commit()
        raise HTTPException(
            status_code=500, detail="Workflow execution failed"
        ) from exc

    step_dicts: list[dict[str, Any]] = []
    for step_result in result.get("steps", []):
        step = WorkflowRunStep(
            run_id=run.id,
            step_id=step_result.get("step_id", str(uuid4())),
            name=step_result.get("name", ""),
            status=step_result.get("status", "skipped"),
            started_at=_parse_dt(step_result.get("started_at")),
            completed_at=_parse_dt(step_result.get("completed_at")),
            duration_ms=step_result.get("duration_ms", 0) or 0,
            input_data=step_result.get("input_data", {}),
            output_data=step_result.get("output_data"),
            error=step_result.get("error"),
            agent_execution_id=step_result.get("agent_execution_id"),
        )
        session.add(step)
        await session.flush()
        step_dicts.append(_step_to_dict(step))

    completed_at = datetime.utcnow()
    run.status = result.get("status", "failed")
    run.completed_at = completed_at
    run.duration_ms = result.get("duration_ms", 0)
    session.add(run)
    await session.commit()
    await session.refresh(run)

    return {"data": {**_run_to_dict(run), "steps": step_dicts}, "meta": _meta()}


def _parse_dt(value: Any) -> datetime | None:
    """Parse a datetime string or return None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None


@router.get("/{workflow_id}/runs")
async def list_workflow_runs(
    workflow_id: str,
    status: str | None = Query(default=None),
    trigger_type: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List past runs for a workflow with optional status and trigger filters."""
    wf = await session.get(Workflow, UUID(workflow_id))
    if wf is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    stmt = select(WorkflowRun).where(WorkflowRun.workflow_id == UUID(workflow_id))
    if status:
        stmt = stmt.where(WorkflowRun.status == status)
    if trigger_type:
        stmt = stmt.where(WorkflowRun.trigger_type == trigger_type)

    result = await session.exec(stmt)
    all_runs = result.all()
    total = len(all_runs)
    page = all_runs[offset : offset + limit]
    return {
        "data": [_run_to_dict(r) for r in page],
        "meta": _meta(pagination={"total": total, "limit": limit, "offset": offset}),
    }


@router.get("/{workflow_id}/runs/{run_id}")
async def get_workflow_run(
    workflow_id: str,
    run_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get details of a specific workflow run including step data."""
    wf = await session.get(Workflow, UUID(workflow_id))
    if wf is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    run = await session.get(WorkflowRun, UUID(run_id))
    if run is None or run.workflow_id != UUID(workflow_id):
        raise HTTPException(status_code=404, detail="Run not found")

    stmt = select(WorkflowRunStep).where(WorkflowRunStep.run_id == UUID(run_id))
    result = await session.exec(stmt)
    steps = [_step_to_dict(s) for s in result.all()]
    return {"data": {**_run_to_dict(run), "steps": steps}, "meta": _meta()}


# ── Schedule endpoints ──────────────────────────────────────────────


@router.put("/{workflow_id}/schedule")
async def set_schedule(
    workflow_id: str,
    body: ScheduleSet,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Set or update the schedule for a workflow."""
    wf = await session.get(Workflow, UUID(workflow_id))
    if wf is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Upsert schedule record
    stmt = select(WorkflowSchedule).where(
        WorkflowSchedule.workflow_id == UUID(workflow_id)
    )
    result = await session.exec(stmt)
    sched = result.first()
    now = datetime.utcnow()
    if sched is None:
        sched = WorkflowSchedule(
            workflow_id=wf.id,
            tenant_id=wf.tenant_id,
            cron=body.cron,
            timezone=body.timezone,
        )
    else:
        sched.cron = body.cron
        sched.timezone = body.timezone
        sched.updated_at = now

    session.add(sched)
    wf.schedule = body.cron
    wf.updated_at = now
    session.add(wf)
    await session.commit()
    await session.refresh(sched)

    return {
        "data": {
            "workflow_id": workflow_id,
            "cron": sched.cron,
            "timezone": sched.timezone,
            "created_at": sched.created_at.isoformat() if sched.created_at else None,
        },
        "meta": _meta(),
    }


@router.delete("/{workflow_id}/schedule", status_code=204, response_class=Response)
async def remove_schedule(
    workflow_id: str,
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Remove the schedule from a workflow."""
    wf = await session.get(Workflow, UUID(workflow_id))
    if wf is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    stmt = select(WorkflowSchedule).where(
        WorkflowSchedule.workflow_id == UUID(workflow_id)
    )
    result = await session.exec(stmt)
    sched = result.first()
    if sched is not None:
        await session.delete(sched)

    wf.schedule = None
    wf.updated_at = datetime.utcnow()
    session.add(wf)
    await session.commit()
    return Response(status_code=204)


@router.get("/{workflow_id}/schedule/preview")
async def preview_schedule(
    workflow_id: str,
    count: int = Query(default=5, ge=1, le=20),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Preview next N run times for a workflow's schedule."""
    wf = await session.get(Workflow, UUID(workflow_id))
    if wf is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    stmt = select(WorkflowSchedule).where(
        WorkflowSchedule.workflow_id == UUID(workflow_id)
    )
    result = await session.exec(stmt)
    sched = result.first()

    cron = sched.cron if sched else wf.schedule
    tz_str = sched.timezone if sched else "UTC"

    if not cron:
        return {
            "data": {"next_runs": [], "cron": None, "timezone": tz_str},
            "meta": _meta(),
        }

    next_runs = _compute_next_runs(cron, count, tz_str)
    return {
        "data": {"next_runs": next_runs, "cron": cron, "timezone": tz_str},
        "meta": _meta(),
    }


# ── WebSocket for execution streaming ───────────────────────────────


@router.websocket("/{workflow_id}/executions/{exec_id}")
async def ws_execution_stream(
    websocket: WebSocket,
    workflow_id: str,
    exec_id: str,
) -> None:
    """Stream step execution events via WebSocket."""
    await websocket.accept()

    # Open a separate session for WebSocket — can't use Depends here
    from app.database import async_session_factory

    async with async_session_factory() as ws_session:
        try:
            run = await ws_session.get(WorkflowRun, UUID(exec_id))
            if run is None or run.workflow_id != UUID(workflow_id):
                await websocket.send_json({"error": "Run not found"})
                await websocket.close(code=4004)
                return

            stmt = select(WorkflowRunStep).where(
                WorkflowRunStep.run_id == UUID(exec_id)
            )
            result = await ws_session.exec(stmt)
            steps = result.all()

            for step in steps:
                event = {
                    "type": "step_update",
                    "step_id": step.step_id,
                    "name": step.name,
                    "status": step.status,
                    "duration_ms": step.duration_ms or 0,
                    "input_data": step.input_data,
                    "output_data": step.output_data,
                    "agent_execution_id": step.agent_execution_id,
                }
                await websocket.send_json(event)
                await asyncio.sleep(0.05)

            await websocket.send_json({"type": "run_complete", "status": run.status})
            await websocket.close()
        except WebSocketDisconnect:
            logger.debug(
                "workflow.ws.client_disconnected",
                extra={"workflow_id": workflow_id, "exec_id": exec_id},
            )


# ── Workflow Trigger Endpoints ──────────────────────────────────────


@router.post("/{workflow_id}/webhook", summary="Trigger workflow via webhook")
async def webhook_trigger(
    workflow_id: str,
    payload: dict = Body(...),
    x_api_key: str = Header(None, alias="X-API-Key"),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Accept webhook payload and trigger workflow execution."""
    # Verify workflow exists
    workflow = await session.get(Workflow, UUID(workflow_id))
    if not workflow:
        raise HTTPException(404, f"Workflow {workflow_id} not found")
    # Create a new run with the webhook payload as input
    run = WorkflowRun(
        id=uuid4(),
        workflow_id=workflow.id,
        status="pending",
        trigger_type="webhook",
        input_data=payload,
        tenant_id=workflow.tenant_id,
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)
    return {"run_id": str(run.id), "status": "pending", "trigger": "webhook"}


@router.post("/events", summary="Fire event to trigger matching workflows")
async def fire_event(
    event: dict = Body(...),  # {type, source, data}
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Match event to workflow trigger rules and fire matching workflows."""
    event_type = event.get("type", "")
    event_source = event.get("source")

    # Query all active workflows that have a trigger_config
    stmt = select(Workflow).where(Workflow.is_active)
    result = await session.exec(stmt)
    all_workflows = result.all()

    # Filter workflows whose trigger_config matches this event
    matched_workflow_ids: list[str] = []
    created_run_ids: list[str] = []

    for workflow in all_workflows:
        tc = workflow.trigger_config
        if not tc or tc.get("type") != "event":
            continue
        if tc.get("event_type") != event_type:
            continue
        # Optional source filter — only reject if config specifies a source that doesn't match
        if tc.get("source") and tc.get("source") != event_source:
            continue

        run = WorkflowRun(
            id=uuid4(),
            workflow_id=workflow.id,
            tenant_id=workflow.tenant_id,
            status="pending",
            trigger_type="event",
            input_data=event,
        )
        session.add(run)
        matched_workflow_ids.append(str(workflow.id))
        created_run_ids.append(str(run.id))

    if matched_workflow_ids:
        await session.commit()

    return {
        "status": "accepted",
        "event_type": event_type,
        "matched_workflows": matched_workflow_ids,
        "created_runs": created_run_ids,
    }


@router.post(
    "/{workflow_id}/runs/{run_id}/signal", summary="Send signal to running workflow"
)
async def send_signal(
    workflow_id: str,
    run_id: str,
    signal: dict = Body(...),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Send data signal to a running workflow run via Redis pub/sub."""
    run = await session.get(WorkflowRun, UUID(run_id))
    if not run or run.workflow_id != UUID(workflow_id):
        raise HTTPException(404, "Workflow run not found")

    channel = f"archon:workflow:{workflow_id}:signals"
    message = {
        "signal": signal,
        "run_id": run_id,
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
    }

    published = False
    try:
        r = await _get_redis_client()
        async with r:
            subscribers = await r.publish(channel, json.dumps(message))
        published = True
        logger.debug("Signal published to %s (%d subscriber(s))", channel, subscribers)
    except Exception as exc:  # noqa: BLE001
        # Redis unavailable — log and degrade gracefully; signal is still acknowledged
        logger.warning("Failed to publish signal to Redis channel %s: %s", channel, exc)

    return {
        "status": "signal_received",
        "run_id": run_id,
        "published": published,
        "channel": channel,
    }


@router.get(
    "/{workflow_id}/runs/{run_id}/query/{query_name}",
    summary="Query workflow run state",
)
async def query_run(
    workflow_id: str,
    run_id: str,
    query_name: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Query state of a running workflow without modifying it.

    Returns full run details including all steps with timing and results.
    ``query_name`` is accepted for future extensibility (e.g. named sub-queries).
    """
    run = await session.get(WorkflowRun, UUID(run_id))
    if not run or run.workflow_id != UUID(workflow_id):
        raise HTTPException(404, "Workflow run not found")

    stmt = select(WorkflowRunStep).where(WorkflowRunStep.run_id == UUID(run_id))
    result = await session.exec(stmt)
    steps = [_step_to_dict(s) for s in result.all()]

    return {
        "query": query_name,
        "data": {**_run_to_dict(run, steps=steps)},
        "meta": _meta(),
    }
