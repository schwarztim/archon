"""Workflow DAG execution service — branch-aware per ADR-003.

Each step in the workflow has an optional ``type`` (or ``node_type``) field.
When present, the step is dispatched to the appropriate NodeExecutor from the
registry.  When absent (or the type is not registered), the legacy
``execute_agent`` path is used for backward compatibility.

Per ADR-003 (Branch Selection and Fan-In Semantics), the engine — not the
executors — owns topology decisions:

  * **Branch hints** (``conditionNode`` / ``switchNode``): the engine
    schedules only the selected step_id and marks the unselected branches
    plus their transitive descendants as ``skipped`` with reason
    ``branch_not_selected``.
  * **Fan-out hints** (``parallelNode``): the engine registers the fan-in
    policy on every step_id that consumes the parallel branches and applies
    ``all`` / ``any`` / ``n_of_m`` join semantics on readiness.
  * **Loop hints** (``loopNode``): the engine executes the body sub-graph
    up to ``max_iterations`` (with a hard cap), evaluating
    ``condition_expr`` between iterations, and accumulates per-iteration
    outputs into the loop node's final output.

The engine validates every hint envelope on receipt; misshapen hints raise
``WorkflowValidationError`` so the failure is loud.
"""

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


# Hard ceiling for loop iterations — engine-side guard mirroring the
# loopNode executor's cap.  Prevents runaway body execution.
_LOOP_HARD_CAP = 1_000


class WorkflowEngineError(Exception):
    """Base error for workflow execution issues."""


class WorkflowValidationError(WorkflowEngineError):
    """Raised when a workflow definition (or hint shape) is invalid."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def execute_workflow_dag(
    workflow: dict[str, Any],
    *,
    tenant_id: str | None = None,
    on_step_event: StepEventCallback | None = None,
    db_session: Any | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Execute workflow steps respecting dependency DAG and ADR-003 hints."""
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
    _cancel = cancel_check or (lambda: False)

    # Topology overlays populated as the DAG runs.
    fanin_policies: dict[str, dict[str, Any]] = {}      # step_id → policy
    loop_managed: set[str] = set()                      # body step_ids owned by a loop
    skipped_by_branch: set[str] = set()                 # explicitly skipped via branch hint

    # Pre-pass: any loop steps already declared in config carry their
    # body_step_ids; we mark those bodies as loop-managed so the main DAG
    # traversal does not run them in isolation.  The hint emitted at run
    # time also adds to this set, which covers loops whose body list is
    # only known dynamically.
    for step_id, step in normalized.items():
        if (step.get("node_type") or step.get("type")) == "loopNode":
            body_ids = _extract_body_step_ids(step.get("config") or {}, normalized, name_lookup)
            for bid in body_ids:
                if bid in normalized:
                    loop_managed.add(bid)

    start_time = time.perf_counter()

    while len(completed) < len(normalized):
        if _cancel():
            break

        # Build the ready batch — a step is ready when all its remaining
        # static deps are clear AND its fan-in policy (if any) is satisfied.
        ready: list[str] = []
        for step_id in normalized:
            if step_id in completed:
                continue
            if step_id in loop_managed:
                # Body steps are run inside the loop iteration loop.
                continue
            if not _is_step_ready(
                step_id,
                remaining_deps=remaining_deps,
                fanin_policies=fanin_policies,
                step_results=step_results,
            ):
                continue
            ready.append(step_id)

        if not ready:
            # No progress possible — either circular deps or every
            # remaining step is loop-managed (already handled above).
            outstanding = [s for s in normalized if s not in completed and s not in loop_managed]
            if outstanding:
                raise WorkflowValidationError(
                    "Workflow contains circular dependencies"
                )
            break

        ready.sort(key=lambda sid: (order_index[sid], sid))

        batch_coroutines = [
            _run_step(
                workflow,
                normalized[step_id],
                _build_upstream_context(step_id, dependencies, step_results),
                tenant_id=tenant_id,
                on_step_event=on_step_event,
                db_session=db_session,
                cancel_check=_cancel,
            )
            for step_id in ready
        ]
        batch_results = await asyncio.gather(*batch_coroutines)

        # Process each completed step — apply ADR-003 hints, drive
        # downstream readiness, recurse into loops.
        for step_id, step_result in zip(ready, batch_results):
            step_node_type = normalized[step_id].get("node_type")

            # Loop nodes — if the executor emitted a loop hint, run the
            # body sub-graph and replace the step's recorded output with
            # the accumulated iteration result.
            if step_node_type == "loopNode" and step_result["status"] == "completed":
                loop_hint = _extract_hint(step_result.get("output_data"))
                if loop_hint is not None and loop_hint.get("kind") == "loop":
                    _validate_loop_hint(loop_hint, normalized)
                    accumulated = await _run_loop(
                        loop_step_id=step_id,
                        loop_hint=loop_hint,
                        workflow=workflow,
                        normalized=normalized,
                        upstream_context=_build_upstream_context(
                            step_id, dependencies, step_results,
                        ),
                        tenant_id=tenant_id,
                        on_step_event=on_step_event,
                        db_session=db_session,
                        cancel_check=_cancel,
                        ordered_results=ordered_results,
                        step_results=step_results,
                    )
                    # Mark body steps as loop-managed (idempotent if the
                    # pre-pass already added them).  This guards against
                    # bodies that the DAG might otherwise treat as
                    # independent.
                    for bid in loop_hint.get("body_step_ids", []):
                        if bid in normalized:
                            loop_managed.add(bid)
                    # Replace output with accumulated result.
                    step_result["output_data"] = {
                        **(step_result.get("output_data") or {}),
                        "iterations": accumulated["iterations"],
                        "completed_iterations": accumulated["completed_iterations"],
                        "result": accumulated["result"],
                    }
                    if accumulated.get("failed"):
                        step_result["status"] = "failed"
                        step_result["error"] = accumulated.get("error")

            step_results[step_id] = step_result
            ordered_results.append(step_result)
            completed.add(step_id)

            # Branch hint — skip unselected alternatives and their descendants.
            output_data = step_result.get("output_data") or {}
            hint = _extract_hint(output_data) if isinstance(output_data, dict) else None

            if (
                step_result["status"] == "completed"
                and hint is not None
                and hint.get("kind") == "branch"
            ):
                _validate_branch_hint(hint, normalized)
                selected = set(hint.get("selected_step_ids", []))
                alternatives = set(hint.get("alternatives", []))
                # Treat all configured alternatives as the candidate set;
                # any not selected (and any descendants of them that are
                # not also descendants of the selected branch) get marked
                # skipped.
                if not alternatives:
                    alternatives = selected
                unselected = alternatives - selected
                if unselected:
                    skipped_ids = _propagate_skip(
                        roots=unselected,
                        keep=selected,
                        adjacency=adjacency,
                        normalized=normalized,
                        skipped_by_branch=skipped_by_branch,
                    )
                    for skipped_id in skipped_ids:
                        if skipped_id in completed or skipped_id == step_id:
                            continue
                        skip_payload = _create_skipped_step(
                            normalized[skipped_id],
                            "branch_not_selected",
                        )
                        step_results[skipped_id] = skip_payload
                        ordered_results.append(skip_payload)
                        completed.add(skipped_id)
                        skipped_by_branch.add(skipped_id)
                        await _emit_event(
                            on_step_event,
                            {
                                "type": "step_skipped",
                                "workflow_id": workflow.get("id"),
                                "workflow_name": workflow.get("name"),
                                "step_id": skipped_id,
                                "name": normalized[skipped_id].get("name"),
                                "reason": "branch_not_selected",
                            },
                        )
                        # Tear remaining_deps so downstream nodes can observe
                        # the skip without waiting indefinitely.
                        for child in adjacency.get(skipped_id, ()):
                            remaining_deps.get(child, set()).discard(skipped_id)

            # Fan-out hint — register fan-in policy on every step that
            # depends on any of the listed branches.
            if (
                step_result["status"] == "completed"
                and hint is not None
                and hint.get("kind") == "fanout"
            ):
                _validate_fanout_hint(hint, normalized)
                _register_fanin_policy(
                    fanout_node=step_id,
                    hint=hint,
                    adjacency=adjacency,
                    fanin_policies=fanin_policies,
                )

            # Decrement remaining_deps for direct children regardless of
            # hint kind — even branch/fanout origins still feed their
            # successors.  (Skipped successors are handled above.)
            for child in adjacency.get(step_id, ()):
                remaining_deps.get(child, set()).discard(step_id)

            if step_result["status"] == "failed":
                failed = True
            if step_result["status"] == "paused":
                break

        if failed or any(r["status"] == "paused" for r in ordered_results):
            break

    if failed:
        skipped = [
            _create_skipped_step(
                normalized[step_id], "Upstream dependency failed"
            )
            for step_id in normalized
            if step_id not in completed and step_id not in loop_managed
        ]
        ordered_results.extend(skipped)

    duration_ms = max(0, int((time.perf_counter() - start_time) * 1000))

    # Determine overall status
    paused = any(r["status"] == "paused" for r in ordered_results)
    if paused:
        status = "paused"
    elif failed:
        status = "failed"
    else:
        status = "completed"

    return {
        "status": status,
        "steps": ordered_results,
        "duration_ms": duration_ms,
    }


# ---------------------------------------------------------------------------
# Hint extraction + validation (ADR-003)
# ---------------------------------------------------------------------------


def _extract_hint(output_data: Any) -> dict[str, Any] | None:
    """Return ``output_data["_hint"]`` if shaped as a dict, else None."""
    if not isinstance(output_data, dict):
        return None
    hint = output_data.get("_hint")
    if isinstance(hint, dict) and "kind" in hint:
        return hint
    return None


def _validate_branch_hint(
    hint: dict[str, Any],
    normalized: dict[str, dict[str, Any]],
) -> None:
    """Validate a branch hint.  Raises WorkflowValidationError on misshape."""
    selected = hint.get("selected_step_ids")
    if not isinstance(selected, list) or not selected:
        raise WorkflowValidationError(
            "branch hint missing non-empty selected_step_ids"
        )
    for sid in selected:
        if not isinstance(sid, str) or sid not in normalized:
            raise WorkflowValidationError(
                f"branch hint references unknown step_id {sid!r}"
            )
    alternatives = hint.get("alternatives", [])
    if not isinstance(alternatives, list):
        raise WorkflowValidationError("branch hint alternatives must be a list")
    for alt in alternatives:
        if not isinstance(alt, str) or alt not in normalized:
            raise WorkflowValidationError(
                f"branch hint references unknown alternative step_id {alt!r}"
            )


def _validate_fanout_hint(
    hint: dict[str, Any],
    normalized: dict[str, dict[str, Any]],
) -> None:
    """Validate a fan-out hint."""
    mode = hint.get("mode")
    if mode not in ("all", "any", "n_of_m"):
        raise WorkflowValidationError(
            f"fanout hint invalid mode {mode!r}; expected all|any|n_of_m"
        )
    branches = hint.get("step_ids", [])
    if not isinstance(branches, list) or not branches:
        raise WorkflowValidationError(
            "fanout hint requires non-empty step_ids list"
        )
    for bid in branches:
        if not isinstance(bid, str) or bid not in normalized:
            raise WorkflowValidationError(
                f"fanout hint references unknown step_id {bid!r}"
            )
    if mode == "n_of_m":
        n = hint.get("n")
        if not isinstance(n, int) or n < 1:
            raise WorkflowValidationError(
                "fanout n_of_m requires integer n >= 1"
            )
        if n > len(branches):
            raise WorkflowValidationError(
                f"fanout n_of_m: n={n} exceeds branch count {len(branches)}"
            )


def _validate_loop_hint(
    hint: dict[str, Any],
    normalized: dict[str, dict[str, Any]],
) -> None:
    """Validate a loop hint."""
    body = hint.get("body_step_ids", [])
    if not isinstance(body, list) or not body:
        raise WorkflowValidationError(
            "loop hint requires non-empty body_step_ids list"
        )
    for bid in body:
        if not isinstance(bid, str) or bid not in normalized:
            raise WorkflowValidationError(
                f"loop hint references unknown body step_id {bid!r}"
            )
    max_it = hint.get("max_iterations", 10)
    if not isinstance(max_it, int) or max_it < 1:
        raise WorkflowValidationError(
            "loop hint requires integer max_iterations >= 1"
        )
    accumulate = hint.get("accumulate_mode", "last")
    if accumulate not in ("last", "list", "reduce"):
        raise WorkflowValidationError(
            f"loop hint invalid accumulate_mode {accumulate!r}"
        )


def _extract_body_step_ids(
    config: dict[str, Any],
    normalized: dict[str, dict[str, Any]],
    name_lookup: dict[str, str],
) -> list[str]:
    """Resolve body_step_ids from a loop config (supports name → id lookup)."""
    raw = (
        config.get("body_step_ids")
        or config.get("bodyStepIds")
        or []
    )
    if not isinstance(raw, list):
        return []
    resolved: list[str] = []
    for entry in raw:
        if not isinstance(entry, str):
            continue
        if entry in normalized:
            resolved.append(entry)
        elif entry in name_lookup:
            resolved.append(name_lookup[entry])
    return resolved


# ---------------------------------------------------------------------------
# Fan-in scheduling
# ---------------------------------------------------------------------------


def _register_fanin_policy(
    *,
    fanout_node: str,
    hint: dict[str, Any],
    adjacency: dict[str, set[str]],
    fanin_policies: dict[str, dict[str, Any]],
) -> None:
    """Register a fan-in policy on every step that joins the fan-out branches.

    A "join" is any step that depends on at least one of the fan-out
    branches.  We walk the adjacency map for each branch and union the
    direct children — any of those children sees a fan-in policy.
    """
    branches = list(hint.get("step_ids", []))
    branch_set = set(branches)
    mode = hint.get("mode", "all")
    n = int(hint.get("n") or 1)

    join_candidates: set[str] = set()
    for branch in branches:
        for child in adjacency.get(branch, ()):
            join_candidates.add(child)

    for join in join_candidates:
        existing = fanin_policies.get(join)
        if existing is None:
            fanin_policies[join] = {
                "mode": mode,
                "n": n,
                "branches": set(branch_set),
                "fanout_node": fanout_node,
            }
        else:
            # If two fan-outs feed the same join, take the more permissive
            # policy: any > n_of_m > all.  This is intentionally simple —
            # production graphs rarely chain fan-outs into a single join.
            existing["branches"] |= branch_set
            if existing["mode"] == "all" and mode != "all":
                existing["mode"] = mode
                existing["n"] = n


def _is_step_ready(
    step_id: str,
    *,
    remaining_deps: dict[str, set[str]],
    fanin_policies: dict[str, dict[str, Any]],
    step_results: dict[str, dict[str, Any]],
) -> bool:
    """Return True when *step_id* is runnable.

    With a fan-in policy registered, readiness depends on the count of
    completed branches relative to the policy mode.  Without a policy,
    the static dependency map governs (existing behaviour).
    """
    policy = fanin_policies.get(step_id)
    if policy is None:
        return not remaining_deps.get(step_id)

    branches = policy["branches"]
    mode = policy["mode"]
    n = policy["n"]

    completed_branches = [
        bid for bid in branches
        if step_results.get(bid, {}).get("status") == "completed"
    ]
    terminal_branches = [
        bid for bid in branches
        if step_results.get(bid, {}).get("status") in ("completed", "failed", "skipped")
    ]

    if mode == "any":
        # Ready as soon as one branch completed AND all the step's other
        # static deps are clear (deps outside the branch set).
        if not completed_branches:
            # If no branch has completed but all branches are terminal,
            # the join cannot be satisfied — fall through, but in
            # practice the run will be marked failed by the upstream.
            if len(terminal_branches) == len(branches):
                return False
            return False
        non_branch_deps = remaining_deps.get(step_id, set()) - branches
        return not non_branch_deps

    if mode == "n_of_m":
        if len(completed_branches) < n:
            return False
        non_branch_deps = remaining_deps.get(step_id, set()) - branches
        return not non_branch_deps

    # mode == "all" — all branches must be terminal (any failure cascades
    # via the failed flag in the main loop, but readiness here only
    # requires every branch to have *finished*).
    if len(terminal_branches) != len(branches):
        return False
    non_branch_deps = remaining_deps.get(step_id, set()) - branches
    return not non_branch_deps


# ---------------------------------------------------------------------------
# Skip propagation (branch alternatives)
# ---------------------------------------------------------------------------


def _propagate_skip(
    *,
    roots: set[str],
    keep: set[str],
    adjacency: dict[str, set[str]],
    normalized: dict[str, dict[str, Any]],
    skipped_by_branch: set[str],
) -> list[str]:
    """Return the transitive closure of *roots* in adjacency that does not
    include any node reachable from *keep*.  Used to mark unselected
    branches plus their descendants as skipped, while preserving steps
    that are also reachable from the selected branch.
    """
    keep_reachable: set[str] = set()
    stack = list(keep)
    while stack:
        current = stack.pop()
        if current in keep_reachable:
            continue
        keep_reachable.add(current)
        stack.extend(adjacency.get(current, ()))

    skipped: list[str] = []
    stack = list(roots)
    while stack:
        current = stack.pop()
        if current in skipped_by_branch:
            continue
        if current in keep_reachable:
            # Reachable from selected branch too — leave alone.
            continue
        if current not in normalized:
            continue
        skipped.append(current)
        skipped_by_branch.add(current)
        for child in adjacency.get(current, ()):
            if child not in keep_reachable:
                stack.append(child)

    return skipped


# ---------------------------------------------------------------------------
# Loop execution
# ---------------------------------------------------------------------------


async def _run_loop(
    *,
    loop_step_id: str,
    loop_hint: dict[str, Any],
    workflow: dict[str, Any],
    normalized: dict[str, dict[str, Any]],
    upstream_context: dict[str, Any],
    tenant_id: str | None,
    on_step_event: StepEventCallback | None,
    db_session: Any | None,
    cancel_check: Callable[[], bool],
    ordered_results: list[dict[str, Any]],
    step_results: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Execute the loop body sub-graph up to ``max_iterations`` times.

    Returns a dict::

        {
          "iterations": [<per-iteration body outputs>],
          "completed_iterations": <int>,
          "result": <final value per accumulate_mode>,
          "failed": <bool>,
          "error": <str | None>,
        }

    Body steps are run via the regular dispatch path so retry policies and
    cancellation continue to apply.  The condition_expr (if present) is
    evaluated *after* each iteration; the loop terminates early when it
    evaluates to a falsy value.
    """
    body_step_ids: list[str] = list(loop_hint.get("body_step_ids", []))
    max_iterations = min(int(loop_hint.get("max_iterations", 10)), _LOOP_HARD_CAP)
    accumulate_mode: str = loop_hint.get("accumulate_mode", "last") or "last"
    condition_expr: str | None = loop_hint.get("condition_expr")
    iteration_var: str = loop_hint.get("iteration_var", "index")

    iterations_output: list[dict[str, Any]] = []
    completed_iterations = 0
    loop_failed = False
    loop_error: str | None = None

    # Keep a reference to the latest iteration's body outputs so the next
    # iteration receives them as its upstream context.  The first iteration
    # uses the loop node's own upstream context.
    iteration_inputs: dict[str, Any] = dict(upstream_context)

    for iteration_index in range(max_iterations):
        if cancel_check():
            break

        iteration_body_results: dict[str, dict[str, Any]] = {}
        iteration_failed = False

        # Run each body step sequentially.  Body steps may have their own
        # static depends_on inside the body; we honour them by sorting.
        body_order = _topological_order(body_step_ids, normalized)
        for body_step_id in body_order:
            body_step = normalized[body_step_id]
            # Build upstream context: the loop's external upstream PLUS
            # any earlier body step outputs from this iteration.  Inject
            # the iteration index under iteration_var so condition/
            # expression evaluation can reference it.
            ctx_inputs: dict[str, Any] = dict(iteration_inputs)
            ctx_inputs.update(iteration_body_results)
            ctx_inputs[iteration_var] = iteration_index

            body_result = await _run_step(
                workflow,
                body_step,
                ctx_inputs,
                tenant_id=tenant_id,
                on_step_event=on_step_event,
                db_session=db_session,
                cancel_check=cancel_check,
            )
            iteration_body_results[body_step_id] = {
                "name": body_result.get("name"),
                "status": body_result.get("status"),
                "output": body_result.get("output_data"),
            }
            ordered_results.append(body_result)

            if body_result.get("status") == "failed":
                iteration_failed = True
                loop_failed = True
                loop_error = body_result.get("error") or "loop body step failed"
                break

        completed_iterations = iteration_index + 1
        iterations_output.append({
            "iteration": iteration_index,
            "outputs": iteration_body_results,
        })

        if iteration_failed:
            break

        # Propagate this iteration's outputs to the next iteration.
        iteration_inputs = dict(upstream_context)
        iteration_inputs.update(iteration_body_results)

        # Evaluate condition_expr (if present) after each iteration.
        if condition_expr:
            try:
                if not _evaluate_loop_condition(
                    condition_expr, iteration_body_results, iteration_index, iteration_var,
                ):
                    break
            except Exception as exc:  # noqa: BLE001
                logger.warning("loopNode.condition_eval_error", exc_info=True)
                loop_failed = True
                loop_error = f"loop condition error: {exc}"
                break

    # Compute accumulated result.
    if accumulate_mode == "list":
        result: Any = [it["outputs"] for it in iterations_output]
    elif accumulate_mode == "reduce":
        # Best-effort reduce: dict-merge per-iteration outputs in order.
        merged: dict[str, Any] = {}
        for it in iterations_output:
            for body_id, body_out in it["outputs"].items():
                output = body_out.get("output")
                if isinstance(output, dict):
                    merged.update(output)
                else:
                    merged.setdefault(body_id, output)
        result = merged
    else:  # "last"
        result = (
            iterations_output[-1]["outputs"] if iterations_output else None
        )

    return {
        "iterations": iterations_output,
        "completed_iterations": completed_iterations,
        "result": result,
        "failed": loop_failed,
        "error": loop_error,
    }


def _topological_order(
    body_step_ids: list[str],
    normalized: dict[str, dict[str, Any]],
) -> list[str]:
    """Return *body_step_ids* in topological order honouring depends_on.

    Deps that fall outside the body set are ignored — they are satisfied
    by the loop's upstream context.
    """
    body_set = set(body_step_ids)
    in_degree: dict[str, int] = {sid: 0 for sid in body_step_ids}
    edges: dict[str, list[str]] = {sid: [] for sid in body_step_ids}

    for sid in body_step_ids:
        deps = normalized[sid].get("depends_on", []) or []
        for dep in deps:
            if dep in body_set:
                edges[dep].append(sid)
                in_degree[sid] += 1

    queue = [sid for sid, d in in_degree.items() if d == 0]
    queue.sort()  # deterministic
    ordered: list[str] = []
    while queue:
        current = queue.pop(0)
        ordered.append(current)
        for child in edges.get(current, []):
            in_degree[child] -= 1
            if in_degree[child] == 0:
                queue.append(child)
        queue.sort()

    if len(ordered) != len(body_step_ids):
        # Cycle inside the body — fall back to original order; the body
        # will likely fail downstream but we do not crash here.
        return list(body_step_ids)
    return ordered


def _evaluate_loop_condition(
    expression: str,
    iteration_outputs: dict[str, dict[str, Any]],
    iteration_index: int,
    iteration_var: str,
) -> bool:
    """Evaluate a loop condition expression against the iteration outputs."""
    names: dict[str, Any] = {iteration_var: iteration_index}
    for body_id, body_out in iteration_outputs.items():
        output = body_out.get("output")
        names[body_id] = output
        if isinstance(output, dict):
            for k, v in output.items():
                names[f"{body_id}.{k}"] = v
                names.setdefault(k, v)

    try:
        from simpleeval import EvalWithCompoundTypes  # noqa: PLC0415

        return bool(EvalWithCompoundTypes(names=names).eval(expression))
    except ImportError:
        try:
            return bool(eval(expression, {"__builtins__": {}}, names))  # noqa: S307
        except Exception:  # noqa: BLE001
            return False


# ---------------------------------------------------------------------------
# Normalisation + dependency map (unchanged, with minor tightening)
# ---------------------------------------------------------------------------


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

        config_raw = raw.get("config") or {}
        if not isinstance(config_raw, dict):
            raise WorkflowValidationError(f"Step '{name}' config must be an object")

        # node_type takes precedence: top-level → config.* → legacy "type"
        # The REST WorkflowStepCreate schema persists node_type under
        # step["config"]["node_type"], so we must fall back into the config
        # dict for REST-created workflows.
        node_type: str | None = (
            raw.get("node_type")
            or raw.get("type")
            or raw.get("nodeType")
            or config_raw.get("node_type")
            or config_raw.get("type")
            or config_raw.get("nodeType")
        )
        agent_id = raw.get("agent_id")

        # Require either a node_type (new path) or agent_id (legacy path)
        if not node_type and not agent_id:
            raise WorkflowValidationError(
                f"Step '{name}' must have either a node_type or agent_id"
            )

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
            "node_type": node_type,
            "agent_id": str(agent_id) if agent_id else None,
            "config": dict(config_raw),
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


# ---------------------------------------------------------------------------
# Step execution helpers (unchanged)
# ---------------------------------------------------------------------------


async def _run_step(
    workflow: dict[str, Any],
    step: dict[str, Any],
    upstream_context: dict[str, Any],
    *,
    tenant_id: str | None,
    on_step_event: StepEventCallback | None,
    db_session: Any | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    started_at = _now_iso()
    timer_start = time.perf_counter()
    _cancel = cancel_check or (lambda: False)

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

    node_type: str | None = step.get("node_type")
    agent_id: str | None = step.get("agent_id")

    try:
        node_result = await _dispatch_step(
            step=step,
            upstream_context=upstream_context,
            workflow=workflow,
            tenant_id=tenant_id,
            db_session=db_session,
            cancel_check=_cancel,
            node_type=node_type,
            agent_id=agent_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "workflow.step.execution_error",
            exc_info=True,
            extra={"workflow_id": workflow.get("id"), "step_id": step["step_id"]},
        )
        from app.services.node_executors import NodeResult  # noqa: PLC0415
        node_result = NodeResult(
            status="failed",
            error=f"{type(exc).__name__}: {exc}",
        )

    duration_ms = max(0, int((time.perf_counter() - timer_start) * 1000))
    completed_at = _now_iso()
    status = node_result.status  # "completed" | "failed" | "paused" | "skipped"

    step_result = {
        "step_id": step["step_id"],
        "name": step.get("name", step["step_id"]),
        "node_type": node_type,
        "status": status,
        "started_at": started_at,
        "completed_at": completed_at,
        "duration_ms": duration_ms,
        "input_data": upstream_context,
        "output_data": node_result.output,
        "error": node_result.error,
        "paused_reason": node_result.paused_reason,
        "token_usage": node_result.token_usage,
        "cost_usd": node_result.cost_usd,
    }

    event_type = (
        "step_completed"
        if status == "completed"
        else ("step_paused" if status == "paused" else "step_failed")
    )
    await _emit_event(
        on_step_event,
        {
            "type": event_type,
            "workflow_id": workflow.get("id"),
            "workflow_name": workflow.get("name"),
            "step_id": step["step_id"],
            "name": step.get("name"),
            "status": status,
        },
    )

    return step_result


async def _dispatch_step(
    *,
    step: dict[str, Any],
    upstream_context: dict[str, Any],
    workflow: dict[str, Any],
    tenant_id: str | None,
    db_session: Any | None,
    cancel_check: Callable[[], bool],
    node_type: str | None,
    agent_id: str | None,
) -> Any:
    """Dispatch a step to the node executor registry or the legacy path."""
    # --- New path: node type registry ---
    if node_type:
        from app.services.node_executors import NODE_EXECUTORS, NodeContext, NodeResult  # noqa: PLC0415

        executor = NODE_EXECUTORS.get(node_type)
        if executor is not None:
            inputs: dict[str, Any] = {
                dep_id: info.get("output") if isinstance(info, dict) else info
                for dep_id, info in upstream_context.items()
            }

            ctx = NodeContext(
                step_id=step["step_id"],
                node_type=node_type,
                node_data=step,
                inputs=inputs,
                tenant_id=tenant_id,
                secrets=None,
                db_session=db_session,
                cancel_check=cancel_check,
            )

            retry_policy = (step.get("config") or {}).get("retryPolicy") or {}
            result = await _with_retry(executor.execute, ctx, retry_policy)
            return result
        else:
            logger.debug(
                "workflow.step.unknown_node_type",
                extra={"node_type": node_type, "step_id": step["step_id"]},
            )

    # --- Legacy path: agent_id dispatch ---
    if agent_id:
        input_payload = _build_step_input(workflow, step, upstream_context)
        definition = _select_agent_definition(workflow, step)
        response = await execute_agent(
            agent_id,
            definition,
            input_payload,
            tenant_id=tenant_id,
        )
        from app.services.node_executors import NodeResult  # noqa: PLC0415

        status = "completed" if response.get("status") == "completed" else "failed"
        return NodeResult(
            status=status,
            output={"output": response.get("output"), "steps": response.get("steps")},
            error=response.get("error"),
        )

    from app.services.node_executors import NodeResult  # noqa: PLC0415

    return NodeResult(
        status="failed",
        error="Step has neither node_type nor agent_id",
    )


async def _with_retry(execute_fn, ctx, retry_policy: dict) -> Any:
    """Wrap executor.execute with exponential-backoff retry from retryPolicy."""
    max_attempts: int = int(retry_policy.get("maxAttempts") or 1)
    backoff: str = retry_policy.get("backoff") or "none"
    base_delay: float = float(retry_policy.get("baseDelaySeconds") or 1.0)

    if max_attempts <= 1:
        return await execute_fn(ctx)

    last_result = None
    for attempt in range(max_attempts):
        if attempt > 0:
            if backoff == "exponential":
                wait = base_delay * (2 ** (attempt - 1))
            elif backoff == "linear":
                wait = base_delay * attempt
            else:
                wait = base_delay
            logger.debug(
                "workflow.step.retry",
                extra={"step_id": ctx.step_id, "attempt": attempt, "wait_s": wait},
            )
            await asyncio.sleep(wait)

        last_result = await execute_fn(ctx)
        if last_result.status != "failed":
            return last_result

    return last_result


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
        "node_type": step.get("node_type"),
        "status": "skipped",
        "started_at": None,
        "completed_at": None,
        "duration_ms": 0,
        "input_data": {"skipped": True, "reason": reason},
        "output_data": None,
        "error": reason,
        "paused_reason": None,
        "token_usage": None,
        "cost_usd": None,
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
