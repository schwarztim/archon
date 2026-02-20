"""Workflow orchestration endpoints.

In-memory stub storage — full DB integration to follow.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field as PField

from starlette.responses import Response
from app.services.workflow_engine import (
    WorkflowEngineError,
    WorkflowValidationError,
    execute_workflow_dag,
)

router = APIRouter(prefix="/workflows", tags=["workflows"])
logger = logging.getLogger(__name__)

# ── In-memory stores ────────────────────────────────────────────────

_workflows: list[dict[str, Any]] = []
_workflow_runs: list[dict[str, Any]] = []
_workflow_run_steps: list[dict[str, Any]] = []
_workflow_schedules: dict[str, dict[str, Any]] = {}


# ── Helpers ─────────────────────────────────────────────────────────

def _meta(*, request_id: str | None = None, **extra: Any) -> dict[str, Any]:
    return {
        "request_id": request_id or str(uuid4()),
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        **extra,
    }


def _find_workflow(workflow_id: str) -> dict[str, Any] | None:
    return next((w for w in _workflows if w["id"] == workflow_id), None)


def _find_run(run_id: str) -> dict[str, Any] | None:
    return next((r for r in _workflow_runs if r["id"] == run_id), None)


def _compute_next_runs(cron: str, count: int = 5, timezone_str: str = "UTC") -> list[str]:
    """Compute next N approximate run times from a cron expression."""
    if not cron:
        return []
    parts = cron.split()
    if len(parts) != 5:
        return []
    min_str, hour_str, dom_str, _mon_str, dow_str = parts
    target_min = 0 if min_str == "*" else int(min_str)
    target_hour = None if hour_str == "*" else int(hour_str)
    now = datetime.now(tz=timezone.utc)
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
) -> dict[str, Any]:
    """List workflows with optional search, group, and status filters."""
    filtered = list(_workflows)
    if search:
        q = search.lower()
        filtered = [w for w in filtered if q in w["name"].lower() or q in w["description"].lower()]
    if group_id:
        filtered = [w for w in filtered if w["group_id"] == group_id]
    if is_active is not None:
        filtered = [w for w in filtered if w["is_active"] is is_active]

    total = len(filtered)
    page = filtered[offset : offset + limit]
    return {
        "data": page,
        "meta": _meta(pagination={"total": total, "limit": limit, "offset": offset}),
    }


@router.post("/", status_code=201)
async def create_workflow(body: WorkflowCreate) -> dict[str, Any]:
    """Create a new workflow."""
    now = datetime.now(tz=timezone.utc).isoformat()
    steps = [
        {
            "step_id": str(uuid4()),
            "name": s.name,
            "agent_id": s.agent_id,
            "config": s.config,
            "depends_on": s.depends_on,
        }
        for s in body.steps
    ]
    workflow: dict[str, Any] = {
        "id": str(uuid4()),
        "name": body.name,
        "description": body.description,
        "group_id": body.group_id,
        "group_name": body.group_name,
        "steps": steps,
        "graph_definition": body.graph_definition,
        "schedule": body.schedule,
        "is_active": body.is_active,
        "created_at": now,
        "updated_at": now,
        "created_by": body.created_by,
    }
    _workflows.append(workflow)
    return {"data": workflow, "meta": _meta()}


@router.get("/{workflow_id}")
async def get_workflow(workflow_id: str) -> dict[str, Any]:
    """Get a single workflow by ID."""
    wf = _find_workflow(workflow_id)
    if wf is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return {"data": wf, "meta": _meta()}


@router.put("/{workflow_id}")
async def update_workflow(workflow_id: str, body: WorkflowUpdate) -> dict[str, Any]:
    """Update an existing workflow."""
    wf = _find_workflow(workflow_id)
    if wf is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    updates = body.model_dump(exclude_unset=True)
    if "steps" in updates and updates["steps"] is not None:
        updates["steps"] = [
            {
                "step_id": str(uuid4()),
                "name": s.name,
                "agent_id": s.agent_id,
                "config": s.config,
                "depends_on": s.depends_on,
            }
            for s in body.steps  # type: ignore[union-attr]
        ]
    wf.update(updates)
    wf["updated_at"] = datetime.now(tz=timezone.utc).isoformat()
    return {"data": wf, "meta": _meta()}


@router.delete("/{workflow_id}", status_code=204, response_class=Response)
async def delete_workflow(workflow_id: str) -> Response:
    """Delete a workflow."""
    global _workflows
    before = len(_workflows)
    _workflows = [w for w in _workflows if w["id"] != workflow_id]
    if len(_workflows) == before:
        raise HTTPException(status_code=404, detail="Workflow not found")
        return Response(status_code=204)


@router.post("/{workflow_id}/execute", status_code=201)
async def execute_workflow(workflow_id: str) -> dict[str, Any]:
    """Execute a workflow using the LangGraph engine."""
    wf = _find_workflow(workflow_id)
    if wf is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    now = datetime.now(tz=timezone.utc).isoformat()
    run_id = str(uuid4())
    run: dict[str, Any] = {
        "id": run_id,
        "workflow_id": workflow_id,
        "status": "running",
        "trigger_type": "manual",
        "started_at": now,
        "completed_at": None,
        "triggered_by": wf.get("created_by", ""),
        "duration_ms": None,
        "steps": [],
    }

    try:
        result = await execute_workflow_dag(wf)
    except WorkflowValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except WorkflowEngineError as exc:
        logger.error(
            "workflow.execution.failed",
            exc_info=True,
            extra={"workflow_id": workflow_id},
        )
        raise HTTPException(status_code=500, detail="Workflow execution failed") from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "workflow.execution.unexpected_error",
            extra={"workflow_id": workflow_id},
        )
        raise HTTPException(status_code=500, detail="Workflow execution failed") from exc

    run_steps: list[dict[str, Any]] = []
    for step_result in result.get("steps", []):
        step_record: dict[str, Any] = {
            "id": str(uuid4()),
            "run_id": run_id,
            "step_id": step_result.get("step_id", str(uuid4())),
            "name": step_result.get("name", ""),
            "status": step_result.get("status", "skipped"),
            "started_at": step_result.get("started_at"),
            "completed_at": step_result.get("completed_at"),
            "duration_ms": step_result.get("duration_ms", 0) or 0,
            "input_data": step_result.get("input_data", {}),
            "output_data": step_result.get("output_data"),
            "agent_execution_id": step_result.get("agent_execution_id"),
        }
        if step_result.get("error"):
            step_record["error"] = step_result["error"]
        _workflow_run_steps.append(step_record)
        run_steps.append(step_record)

    completed_at = datetime.now(tz=timezone.utc).isoformat()
    run["status"] = result.get("status", "failed")
    run["completed_at"] = completed_at
    run["duration_ms"] = result.get("duration_ms", 0)
    run["steps"] = run_steps
    _workflow_runs.append(run)
    return {"data": run, "meta": _meta()}


@router.get("/{workflow_id}/runs")
async def list_workflow_runs(
    workflow_id: str,
    status: str | None = Query(default=None),
    trigger_type: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """List past runs for a workflow with optional status and trigger filters."""
    wf = _find_workflow(workflow_id)
    if wf is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    runs = [r for r in _workflow_runs if r["workflow_id"] == workflow_id]
    if status:
        runs = [r for r in runs if r.get("status") == status]
    if trigger_type:
        runs = [r for r in runs if r.get("trigger_type") == trigger_type]
    total = len(runs)
    page = runs[offset : offset + limit]
    return {
        "data": page,
        "meta": _meta(pagination={"total": total, "limit": limit, "offset": offset}),
    }


@router.get("/{workflow_id}/runs/{run_id}")
async def get_workflow_run(workflow_id: str, run_id: str) -> dict[str, Any]:
    """Get details of a specific workflow run including step data."""
    wf = _find_workflow(workflow_id)
    if wf is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    run = _find_run(run_id)
    if run is None or run.get("workflow_id") != workflow_id:
        raise HTTPException(status_code=404, detail="Run not found")

    # Attach step details
    steps = [s for s in _workflow_run_steps if s.get("run_id") == run_id]
    result = {**run, "steps": steps}
    return {"data": result, "meta": _meta()}


# ── Schedule endpoints ──────────────────────────────────────────────

@router.put("/{workflow_id}/schedule")
async def set_schedule(workflow_id: str, body: ScheduleSet) -> dict[str, Any]:
    """Set or update the schedule for a workflow."""
    wf = _find_workflow(workflow_id)
    if wf is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    schedule_record: dict[str, Any] = {
        "workflow_id": workflow_id,
        "cron": body.cron,
        "timezone": body.timezone,
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
    }
    _workflow_schedules[workflow_id] = schedule_record
    wf["schedule"] = body.cron
    wf["updated_at"] = datetime.now(tz=timezone.utc).isoformat()
    return {"data": schedule_record, "meta": _meta()}


@router.delete("/{workflow_id}/schedule", status_code=204, response_class=Response)
async def remove_schedule(workflow_id: str) -> Response:
    """Remove the schedule from a workflow."""
    wf = _find_workflow(workflow_id)
    if wf is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    _workflow_schedules.pop(workflow_id, None)
    wf["schedule"] = None
    wf["updated_at"] = datetime.now(tz=timezone.utc).isoformat()
    return Response(status_code=204)


@router.get("/{workflow_id}/schedule/preview")
async def preview_schedule(
    workflow_id: str,
    count: int = Query(default=5, ge=1, le=20),
) -> dict[str, Any]:
    """Preview next N run times for a workflow's schedule."""
    wf = _find_workflow(workflow_id)
    if wf is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    schedule = _workflow_schedules.get(workflow_id)
    cron = schedule["cron"] if schedule else wf.get("schedule")
    tz_str = schedule["timezone"] if schedule else "UTC"

    if not cron:
        return {"data": {"next_runs": [], "cron": None, "timezone": tz_str}, "meta": _meta()}

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
    try:
        run = _find_run(exec_id)
        if run is None or run.get("workflow_id") != workflow_id:
            await websocket.send_json({"error": "Run not found"})
            await websocket.close(code=4004)
            return

        steps = [s for s in _workflow_run_steps if s.get("run_id") == exec_id]
        for step in steps:
            event = {
                "type": "step_update",
                "step_id": step["step_id"],
                "name": step["name"],
                "status": step["status"],
                "duration_ms": step.get("duration_ms", 0),
                "input_data": step.get("input_data"),
                "output_data": step.get("output_data"),
                "agent_execution_id": step.get("agent_execution_id"),
            }
            await websocket.send_json(event)
            await asyncio.sleep(0.05)

        await websocket.send_json({"type": "run_complete", "status": run["status"]})
        await websocket.close()
    except WebSocketDisconnect:
        logger.debug(
            "workflow.ws.client_disconnected",
            extra={"workflow_id": workflow_id, "exec_id": exec_id},
        )
