"""Workflow orchestration endpoints.

In-memory stub storage — full DB integration to follow.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field as PField

router = APIRouter(prefix="/workflows", tags=["workflows"])

# ── In-memory stores ────────────────────────────────────────────────

_workflows: list[dict[str, Any]] = []
_workflow_runs: list[dict[str, Any]] = []


# ── Helpers ─────────────────────────────────────────────────────────

def _meta(*, request_id: str | None = None, **extra: Any) -> dict[str, Any]:
    return {
        "request_id": request_id or str(uuid4()),
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        **extra,
    }


def _find_workflow(workflow_id: str) -> dict[str, Any] | None:
    return next((w for w in _workflows if w["id"] == workflow_id), None)


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
    schedule: str | None = None
    is_active: bool = True
    created_by: str = ""


class WorkflowUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    group_id: str | None = None
    group_name: str | None = None
    steps: list[WorkflowStepCreate] | None = None
    schedule: str | None = None
    is_active: bool | None = None


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


@router.delete("/{workflow_id}", status_code=204)
async def delete_workflow(workflow_id: str) -> None:
    """Delete a workflow."""
    global _workflows
    before = len(_workflows)
    _workflows = [w for w in _workflows if w["id"] != workflow_id]
    if len(_workflows) == before:
        raise HTTPException(status_code=404, detail="Workflow not found")


@router.post("/{workflow_id}/execute", status_code=201)
async def execute_workflow(workflow_id: str) -> dict[str, Any]:
    """Execute a workflow — creates a workflow run."""
    wf = _find_workflow(workflow_id)
    if wf is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    now = datetime.now(tz=timezone.utc).isoformat()
    run: dict[str, Any] = {
        "id": str(uuid4()),
        "workflow_id": workflow_id,
        "status": "pending",
        "started_at": now,
        "completed_at": None,
        "triggered_by": wf.get("created_by", ""),
    }
    _workflow_runs.append(run)
    return {"data": run, "meta": _meta()}


@router.get("/{workflow_id}/runs")
async def list_workflow_runs(
    workflow_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """List past runs for a workflow."""
    wf = _find_workflow(workflow_id)
    if wf is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    runs = [r for r in _workflow_runs if r["workflow_id"] == workflow_id]
    total = len(runs)
    page = runs[offset : offset + limit]
    return {
        "data": page,
        "meta": _meta(pagination={"total": total, "limit": limit, "offset": offset}),
    }
