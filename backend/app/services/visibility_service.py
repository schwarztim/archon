"""Visibility service — search and index maintenance for WorkflowRun (W13).

Provides:
  - search_runs()            — filtered search over VisibilityIndex
  - update_visibility_index()— upsert the denormalised row after run state changes
  - get_run_timeline()       — paginated event stream with cursor
  - get_run_graph()          — step dependency graph for operator visualization
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.visibility import VisibilityIndex
from app.models.workflow import WorkflowRun, WorkflowRunEvent, WorkflowRunStep

log = logging.getLogger(__name__)


async def search_runs(
    session: AsyncSession,
    *,
    tenant_id: UUID | None = None,
    filters: dict[str, Any] | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Search WorkflowRuns via the denormalised VisibilityIndex.

    Supported filters:
        status            str              — exact match
        workflow_id       str (UUID)       — exact match
        queue_name        str              — exact match
        worker_id         str              — exact match
        tags              dict             — subset-match (all key-value pairs must be present)
        cost_min          float            — cost_total_usd >= value
        cost_max          float            — cost_total_usd <= value
        duration_min_ms   int              — duration_ms >= value
        duration_max_ms   int              — duration_ms <= value
        external_provider str              — exact match
        failure_code      str              — exact match
        created_after     str (ISO-8601)   — started_at >= value
        created_before    str (ISO-8601)   — started_at <= value
    """
    filters = filters or {}
    stmt = select(VisibilityIndex)

    if tenant_id is not None:
        stmt = stmt.where(VisibilityIndex.tenant_id == tenant_id)

    if status := filters.get("status"):
        stmt = stmt.where(VisibilityIndex.status == status)

    if workflow_id := filters.get("workflow_id"):
        stmt = stmt.where(VisibilityIndex.workflow_id == UUID(str(workflow_id)))

    if queue_name := filters.get("queue_name"):
        stmt = stmt.where(VisibilityIndex.queue_name == queue_name)

    if worker_id := filters.get("worker_id"):
        stmt = stmt.where(VisibilityIndex.worker_id == worker_id)

    if external_provider := filters.get("external_provider"):
        stmt = stmt.where(VisibilityIndex.external_provider == external_provider)

    if failure_code := filters.get("failure_code"):
        stmt = stmt.where(VisibilityIndex.failure_code == failure_code)

    if cost_min := filters.get("cost_min"):
        stmt = stmt.where(VisibilityIndex.cost_total_usd >= float(cost_min))

    if cost_max := filters.get("cost_max"):
        stmt = stmt.where(VisibilityIndex.cost_total_usd <= float(cost_max))

    if duration_min := filters.get("duration_min_ms"):
        stmt = stmt.where(VisibilityIndex.duration_ms >= int(duration_min))

    if duration_max := filters.get("duration_max_ms"):
        stmt = stmt.where(VisibilityIndex.duration_ms <= int(duration_max))

    if created_after := filters.get("created_after"):
        dt = _parse_dt(created_after)
        if dt is not None:
            stmt = stmt.where(VisibilityIndex.started_at >= dt)

    if created_before := filters.get("created_before"):
        dt = _parse_dt(created_before)
        if dt is not None:
            stmt = stmt.where(VisibilityIndex.started_at <= dt)

    stmt = stmt.order_by(VisibilityIndex.started_at.desc()).offset(offset).limit(limit)

    result = await session.execute(stmt)
    rows = list(result.scalars().all())

    # Post-filter tags (JSON subset check — not efficiently indexable in SQL)
    if tags := filters.get("tags"):
        if isinstance(tags, dict):
            rows = [r for r in rows if _tags_match(r.tags_json, tags)]

    return [_vis_to_dict(r) for r in rows]


async def update_visibility_index(
    session: AsyncSession,
    *,
    run_id: UUID,
) -> None:
    """Upsert the VisibilityIndex row for the given run.

    Called by the dispatcher after every terminal transition:
    run.created, run.claimed, run.completed, run.failed, run.cancelled.
    Also called by pipeline_service after PipelineCorrelation insert.

    Reads fresh from WorkflowRun + WorkflowRunStep to build the aggregate.
    """
    run: WorkflowRun | None = await session.get(WorkflowRun, run_id)
    if run is None:
        log.warning("update_visibility_index: run %s not found", run_id)
        return

    # Aggregate step-level cost and count
    steps_stmt = select(WorkflowRunStep).where(WorkflowRunStep.run_id == run_id)
    steps_result = await session.execute(steps_stmt)
    steps = list(steps_result.scalars().all())
    cost_total = sum((s.cost_usd or 0.0) for s in steps)
    step_count = len(steps)
    worker_id = steps[-1].worker_id if steps else None

    # Try to find an existing VisibilityIndex row for this run
    existing_stmt = select(VisibilityIndex).where(
        VisibilityIndex.workflow_run_id == run_id
    )
    existing_result = await session.execute(existing_stmt)
    vis = existing_result.scalars().first()

    now = datetime.utcnow()

    if vis is None:
        vis = VisibilityIndex(
            workflow_run_id=run_id,
            tenant_id=run.tenant_id,
            status=run.status,
            workflow_id=run.workflow_id,
            agent_id=run.agent_id,
            queue_name=None,
            worker_id=worker_id,
            tags_json={},
            cost_total_usd=cost_total,
            duration_ms=run.duration_ms,
            step_count=step_count,
            failure_code=run.error_code,
            started_at=run.started_at,
            completed_at=run.completed_at,
            updated_at=now,
        )
        session.add(vis)
    else:
        vis.status = run.status
        vis.tenant_id = run.tenant_id
        vis.workflow_id = run.workflow_id
        vis.agent_id = run.agent_id
        vis.worker_id = worker_id or vis.worker_id
        vis.cost_total_usd = cost_total
        vis.duration_ms = run.duration_ms
        vis.step_count = step_count
        vis.failure_code = run.error_code
        vis.started_at = run.started_at
        vis.completed_at = run.completed_at
        vis.updated_at = now

    await session.commit()
    log.debug("visibility_index updated for run %s status=%s", run_id, run.status)


async def get_run_timeline(
    session: AsyncSession,
    *,
    run_id: UUID,
    cursor: int = 0,
    limit: int = 50,
) -> dict[str, Any]:
    """Return paginated event stream for a run.

    Uses event sequence as cursor (integer offset). Returns a dict with:
      - events: list of event dicts
      - next_cursor: int — pass as ``cursor`` to get the next page (None when done)
    """
    stmt = (
        select(WorkflowRunEvent)
        .where(WorkflowRunEvent.run_id == run_id)
        .where(WorkflowRunEvent.sequence >= cursor)
        .order_by(WorkflowRunEvent.sequence)
        .limit(limit + 1)  # fetch one extra to detect whether there is a next page
    )
    result = await session.execute(stmt)
    events = list(result.scalars().all())

    has_more = len(events) > limit
    page = events[:limit]

    next_cursor: int | None = None
    if has_more:
        next_cursor = page[-1].sequence + 1

    return {
        "events": [_event_to_dict(e) for e in page],
        "next_cursor": next_cursor,
        "run_id": str(run_id),
    }


async def get_run_graph(
    session: AsyncSession,
    *,
    run_id: UUID,
) -> dict[str, Any]:
    """Return step dependency graph for a run.

    Graph is derived from the run's definition_snapshot.graph_definition
    combined with live step status from WorkflowRunStep rows.
    """
    run: WorkflowRun | None = await session.get(WorkflowRun, run_id)
    if run is None:
        return {"run_id": str(run_id), "nodes": [], "edges": []}

    steps_stmt = select(WorkflowRunStep).where(WorkflowRunStep.run_id == run_id)
    steps_result = await session.execute(steps_stmt)
    steps = list(steps_result.scalars().all())

    step_status: dict[str, dict[str, Any]] = {
        s.step_id: {
            "step_id": s.step_id,
            "name": s.name,
            "status": s.status,
            "duration_ms": s.duration_ms,
            "cost_usd": s.cost_usd,
            "worker_id": s.worker_id,
            "attempt": s.attempt,
            "error": s.error,
        }
        for s in steps
    }

    # Extract graph edges from definition snapshot if available
    graph_def = None
    if run.definition_snapshot:
        graph_def = run.definition_snapshot.get("graph_definition")
        if not graph_def and "graph_definition" in run.definition_snapshot:
            graph_def = run.definition_snapshot["graph_definition"]

    edges: list[dict[str, Any]] = []
    nodes = list(step_status.values())

    if graph_def and isinstance(graph_def, dict):
        raw_edges = graph_def.get("edges", [])
        for edge in raw_edges:
            if isinstance(edge, dict):
                edges.append(
                    {
                        "from": edge.get("from") or edge.get("source"),
                        "to": edge.get("to") or edge.get("target"),
                        "condition": edge.get("condition"),
                    }
                )

    return {
        "run_id": str(run_id),
        "status": run.status,
        "nodes": nodes,
        "edges": edges,
    }


# ── Private helpers ───────────────────────────────────────────────────


def _parse_dt(value: str) -> datetime | None:
    """Parse ISO-8601 datetime string to naive UTC datetime."""
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        # Strip tzinfo to match TIMESTAMP WITHOUT TIME ZONE storage
        return dt.replace(tzinfo=None)
    except (ValueError, AttributeError):
        return None


def _tags_match(row_tags: dict, filter_tags: dict) -> bool:
    """Return True if all filter_tags key-value pairs exist in row_tags."""
    for k, v in filter_tags.items():
        if row_tags.get(k) != v:
            return False
    return True


def _vis_to_dict(vis: VisibilityIndex) -> dict[str, Any]:
    return {
        "id": str(vis.id),
        "workflow_run_id": str(vis.workflow_run_id),
        "tenant_id": str(vis.tenant_id) if vis.tenant_id else None,
        "status": vis.status,
        "workflow_id": str(vis.workflow_id) if vis.workflow_id else None,
        "agent_id": str(vis.agent_id) if vis.agent_id else None,
        "chain_id": str(vis.chain_id) if vis.chain_id else None,
        "queue_name": vis.queue_name,
        "worker_id": vis.worker_id,
        "definition_version_id": (
            str(vis.definition_version_id) if vis.definition_version_id else None
        ),
        "tags_json": vis.tags_json,
        "cost_total_usd": vis.cost_total_usd,
        "duration_ms": vis.duration_ms,
        "step_count": vis.step_count,
        "failure_code": vis.failure_code,
        "external_provider": vis.external_provider,
        "external_run_id": vis.external_run_id,
        "external_branch": vis.external_branch,
        "external_environment": vis.external_environment,
        "started_at": vis.started_at.isoformat() if vis.started_at else None,
        "completed_at": vis.completed_at.isoformat() if vis.completed_at else None,
        "updated_at": vis.updated_at.isoformat() if vis.updated_at else None,
    }


def _event_to_dict(event: WorkflowRunEvent) -> dict[str, Any]:
    return {
        "id": str(event.id),
        "run_id": str(event.run_id),
        "sequence": event.sequence,
        "event_type": event.event_type,
        "payload": event.payload,
        "step_id": event.step_id,
        "span_id": event.span_id,
        "correlation_id": event.correlation_id,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }
