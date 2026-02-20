"""Workflow DAG execution service backed by LangGraph agents."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable
from uuid import uuid4

from app.langgraph.engine import execute_agent

logger = logging.getLogger(__name__)

StepEventCallback = Callable[[dict[str, Any]], Awaitable[None]]


class WorkflowEngineError(Exception):
    """Base error for workflow execution issues."""


class WorkflowValidationError(WorkflowEngineError):
    """Raised when a workflow definition is invalid."""


async def execute_workflow_dag(
    workflow: dict[str, Any],
    *,
    tenant_id: str | None = None,
    on_step_event: StepEventCallback | None = None,
) -> dict[str, Any]:
    """Execute workflow steps respecting dependency DAG semantics."""
    steps_data = workflow.get("steps") or []
    normalized, order, name_lookup = _normalize_steps(steps_data)
    if not normalized:
        return {"status": "completed", "steps": [], "duration_ms": 0}

    dependencies, adjacency = _build_dependency_maps(normalized, name_lookup)
    order_index = {step_id: idx for idx, step_id in enumerate(order)}
    remaining_deps = {sid: set(deps) for sid, deps in dependencies.items()}
    completed: set[str] = set()
    step_results: dict[str, dict[str, Any]] = {}
    ordered_results: list[dict[str, Any]] = []
    failed = False

    start_time = time.perf_counter()

    while len(completed) < len(normalized):
        ready = [
            step_id
            for step_id, deps in remaining_deps.items()
            if not deps and step_id not in completed
        ]
        if not ready:
            raise WorkflowValidationError("Workflow contains circular dependencies")

        ready.sort(key=lambda sid: order_index[sid])
        batch_coroutines = [
            _run_step(
                workflow,
                normalized[step_id],
                _build_upstream_context(step_id, dependencies, step_results),
                tenant_id=tenant_id,
                on_step_event=on_step_event,
            )
            for step_id in ready
        ]
        batch_results = await asyncio.gather(*batch_coroutines)

        for step_id, step_result in zip(ready, batch_results):
            step_results[step_id] = step_result
            ordered_results.append(step_result)
            completed.add(step_id)
            for child in adjacency.get(step_id, ()):
                remaining_deps[child].discard(step_id)
            if step_result["status"] == "failed":
                failed = True

        if failed:
            break

    if failed:
        skipped = [
            _create_skipped_step(normalized[step_id], "Upstream dependency failed")
            for step_id in normalized
            if step_id not in completed
        ]
        ordered_results.extend(skipped)

    duration_ms = max(0, int((time.perf_counter() - start_time) * 1000))
    status = "failed" if failed else "completed"
    return {
        "status": status,
        "steps": ordered_results,
        "duration_ms": duration_ms,
    }


def _normalize_steps(
    raw_steps: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], list[str], dict[str, str]]:
    if not isinstance(raw_steps, list):
        raise WorkflowValidationError("Workflow steps must be provided as a list")

    normalized: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    for raw in raw_steps:
        if not isinstance(raw, dict):
            raise WorkflowValidationError("Each workflow step must be an object")

        step_id = str(raw.get("step_id") or raw.get("id") or uuid4())
        name = raw.get("name") or step_id
        agent_id = raw.get("agent_id")
        if not agent_id:
            raise WorkflowValidationError(f"Step '{name}' is missing an agent_id")

        config = raw.get("config") or {}
        if not isinstance(config, dict):
            raise WorkflowValidationError(f"Step '{name}' config must be an object")

        depends_raw = raw.get("depends_on") or []
        if not isinstance(depends_raw, list):
            raise WorkflowValidationError(
                f"Step '{name}' depends_on must be a list of step IDs"
            )
        depends_on = [str(dep) for dep in depends_raw if str(dep)]

        normalized_step = {
            **raw,
            "step_id": step_id,
            "name": name,
            "agent_id": str(agent_id),
            "config": dict(config),
            "depends_on": depends_on,
        }
        normalized[step_id] = normalized_step
        order.append(step_id)

    name_lookup: dict[str, str] = {}
    for step_id, step in normalized.items():
        step_name = step.get("name")
        if step_name and step_name not in name_lookup:
            name_lookup[step_name] = step_id

    return normalized, order, name_lookup


def _build_dependency_maps(
    steps: dict[str, dict[str, Any]],
    name_lookup: dict[str, str],
) -> tuple[dict[str, list[str]], dict[str, set[str]]]:
    dependencies: dict[str, list[str]] = {}
    adjacency: dict[str, set[str]] = {step_id: set() for step_id in steps}

    for step_id, step in steps.items():
        resolved: list[str] = []
        for dep in step.get("depends_on", []):
            dep_id = _resolve_dependency(dep, steps, name_lookup)
            if dep_id is None:
                raise WorkflowValidationError(
                    f"Step '{step.get('name')}' depends on unknown step '{dep}'"
                )
            if dep_id == step_id:
                raise WorkflowValidationError(
                    f"Step '{step.get('name')}' cannot depend on itself"
                )
            if dep_id not in resolved:
                resolved.append(dep_id)
                adjacency.setdefault(dep_id, set()).add(step_id)
        dependencies[step_id] = resolved

    return dependencies, adjacency


def _resolve_dependency(
    dep: str,
    steps: dict[str, dict[str, Any]],
    name_lookup: dict[str, str],
) -> str | None:
    if dep in steps:
        return dep
    return name_lookup.get(dep)


def _build_upstream_context(
    step_id: str,
    dependencies: dict[str, list[str]],
    prior_results: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    context: dict[str, Any] = {}
    for dep_id in dependencies.get(step_id, []):
        step_result = prior_results.get(dep_id)
        if not step_result:
            continue
        context[dep_id] = {
            "name": step_result.get("name"),
            "status": step_result.get("status"),
            "output": step_result.get("output_data"),
        }
    return context


async def _run_step(
    workflow: dict[str, Any],
    step: dict[str, Any],
    upstream_context: dict[str, Any],
    *,
    tenant_id: str | None,
    on_step_event: StepEventCallback | None,
) -> dict[str, Any]:
    started_at = _now_iso()
    timer_start = time.perf_counter()
    input_payload = _build_step_input(workflow, step, upstream_context)
    definition = _select_agent_definition(workflow, step)

    await _emit_event(
        on_step_event,
        {
            "type": "step_started",
            "workflow_id": workflow.get("id"),
            "workflow_name": workflow.get("name"),
            "step_id": step["step_id"],
            "name": step.get("name"),
        },
    )

    try:
        response = await execute_agent(
            step["agent_id"],
            definition,
            input_payload,
            tenant_id=tenant_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "workflow.step.execution_error",
            exc_info=True,
            extra={"workflow_id": workflow.get("id"), "step_id": step["step_id"]},
        )
        response = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}

    duration_ms = max(0, int((time.perf_counter() - timer_start) * 1000))
    completed_at = _now_iso()
    status = "completed" if response.get("status") == "completed" else "failed"

    step_result = {
        "step_id": step["step_id"],
        "name": step.get("name", step["step_id"]),
        "status": status,
        "started_at": started_at,
        "completed_at": completed_at,
        "duration_ms": duration_ms,
        "input_data": input_payload,
        "output_data": response.get("output"),
        "agent_execution_id": (
            response.get("execution_id") or response.get("id") or None
        ),
        "error": response.get("error"),
    }

    await _emit_event(
        on_step_event,
        {
            "type": "step_completed" if status == "completed" else "step_failed",
            "workflow_id": workflow.get("id"),
            "workflow_name": workflow.get("name"),
            "step_id": step["step_id"],
            "name": step.get("name"),
            "status": status,
        },
    )

    return step_result


def _build_step_input(
    workflow: dict[str, Any],
    step: dict[str, Any],
    upstream_context: dict[str, Any],
) -> dict[str, Any]:
    config = step.get("config") or {}
    base_input = (
        config.get("input_data")
        or config.get("input")
        or config.get("payload")
        or {}
    )

    if isinstance(base_input, dict):
        input_payload = dict(base_input)
    else:
        input_payload = {"message": str(base_input)}

    if "message" not in input_payload:
        input_payload["message"] = (
            config.get("prompt")
            or step.get("name")
            or workflow.get("name")
            or "Workflow step execution"
        )

    input_payload["config"] = config
    input_payload["upstream_outputs"] = upstream_context

    metadata = input_payload.get("metadata")
    metadata_block = metadata if isinstance(metadata, dict) else {}
    metadata_block.setdefault("workflow_id", workflow.get("id"))
    metadata_block.setdefault("workflow_name", workflow.get("name"))
    metadata_block.setdefault("step_id", step.get("step_id"))
    input_payload["metadata"] = metadata_block

    return input_payload


def _select_agent_definition(
    workflow: dict[str, Any],
    step: dict[str, Any],
) -> dict[str, Any]:
    config = step.get("config") or {}
    candidate = (
        config.get("agent_definition")
        or config.get("graph_definition")
        or config.get("definition")
        or workflow.get("graph_definition")
        or {}
    )
    return candidate if isinstance(candidate, dict) else {}


def _create_skipped_step(step: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "step_id": step["step_id"],
        "name": step.get("name", step["step_id"]),
        "status": "skipped",
        "started_at": None,
        "completed_at": None,
        "duration_ms": 0,
        "input_data": {"skipped": True, "reason": reason},
        "output_data": None,
        "agent_execution_id": None,
        "error": reason,
    }


async def _emit_event(
    callback: StepEventCallback | None,
    payload: dict[str, Any],
) -> None:
    if callback is None:
        return
    try:
        await callback(payload)
    except Exception:  # noqa: BLE001
        logger.debug("workflow.step.event_callback_failed", exc_info=True)


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()
