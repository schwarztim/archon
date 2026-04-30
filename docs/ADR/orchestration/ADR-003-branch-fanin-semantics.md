# ADR-003: Branch Selection and Fan-In Semantics Owned by the Engine

- **Status:** ACCEPTED
- **Namespace:** orchestration
- **Date:** 2026-04-29
- **Supersedes:** none
- **Superseded by:** none

## Context

The current code splits decision logic between node executors and the
engine in inconsistent ways:

- `parallelNode` — `backend/app/services/node_executors/parallel.py`
  lines 22–38. The executor returns a `_fanout_hint` with `execution_mode`
  and `n`, but the comment explicitly states it does NOT execute children
  and that the engine "applies the correct fan-in / fan-out semantics."
  In practice no engine consumer enforces this — the executor and the
  engine each contain partial logic.
- Branch nodes (condition / switch) currently mutate downstream state
  inside the executor by setting flags on the workflow context, which
  the engine then re-reads. This couples executor implementation to
  engine internals.
- `workflow_engine.execute_workflow_dag` is the natural authority for
  topology decisions because it owns the DAG traversal cursor.

Splitting decision logic across executors and engine has two failure
modes already observed:

1. **Two sources of truth.** Executors that disagree with the engine
   produce non-deterministic runnability (a branch is taken twice or
   not at all).
2. **Replay non-determinism.** The engine cannot replay a run from
   events alone because executor mutations are not deterministic
   without re-running the executors.

## Decision

Decision authority is consolidated in the engine.

- **Branch selection** (`condition`, `switch`, any future variant) and
  **fan-in readiness** (`parallelNode` `all`, `any`, `n_of_m`) are
  computed exclusively by `workflow_engine.execute_workflow_dag`.
- Node executors emit **hints** in their `NodeResult.output`. They MUST
  NOT decide which downstream node runs next, MUST NOT mutate engine
  state, and MUST NOT short-circuit successors.
- The engine reads the hints, decides downstream runnability, and
  schedules accordingly.

### Hint envelope (canonical)

Every hint is a JSON object placed at `NodeResult.output["_hint"]`.
The presence of the `_hint` key signals the engine to interpret it.

#### Branch hint (condition / switch)

```json
{
  "_hint": {
    "kind": "branch",
    "selected": "<branch_label>",
    "reason": "<short text, optional>",
    "alternatives": ["<branch_a>", "<branch_b>", "<branch_c>"]
  }
}
```

- `selected` is the label the executor evaluated as taken. It is a
  string and MUST appear in `alternatives`.
- The engine consumes `selected`. `reason` is for audit only. The engine
  does not re-evaluate the condition.

#### Fan-out hint (parallelNode)

```json
{
  "_hint": {
    "kind": "fanout",
    "execution_mode": "all|any|n_of_m",
    "n": <int>,
    "branches": ["<branch_id>", "<branch_id>", ...]
  }
}
```

- `execution_mode` MUST be one of `all`, `any`, `n_of_m`. Unknown values
  are rejected by the engine.
- `n` is required when `execution_mode = "n_of_m"`, ignored otherwise.
  When required and `n > len(branches)`, the engine raises
  `ConfigurationError`.
- `branches` is the list of branch identifiers the engine should fan out to.
  Order is significant only for audit purposes; engine schedules in parallel.

### Engine readiness rules (consumed by the engine, not executors)

Given a fan-out hint, the engine considers the join node downstream of the
fan-out runnable when:

- `execution_mode = "all"` — all `branches` reached terminal status
  (`completed`, `failed`, `cancelled`). If any branch is `failed`, the join
  inherits `failed` unless an explicit error-handler branch exists.
- `execution_mode = "any"` — at least one branch is `completed`. Other
  branches are cancelled by the engine (`step.cancelled` events emitted —
  see ADR-002).
- `execution_mode = "n_of_m"` — at least `n` branches are `completed`.
  Pending branches are cancelled by the engine.

For a branch hint, the engine schedules only the node identified by
`selected`. Other alternatives are NOT scheduled. The engine emits
`step.skipped` events for each alternative not selected.

## Consequences

### Positive

- One authority for topology means deterministic replay: the engine can
  reconstruct runnability from events alone (the hint is in the
  `step.completed` payload — see ADR-002 step payload shape).
- Executors are simpler — pure functions that return hints.
- New control-flow node types (race, retry-with-backoff) follow the same
  pattern: emit a hint, let the engine decide.

### Negative

- Existing condition/switch executors must be refactored to remove their
  state mutations and emit `branch` hints instead.
- The engine grows a hint interpreter. The interpreter must be tested
  against every executor that emits a hint.
- Misshapen hints from third-party executors will fail loudly at the
  engine instead of silently in the executor.

### Neutral

- The `_fanout_hint` flag in `parallel.py` line 36 is renamed to follow
  the canonical envelope (`_hint.kind = "fanout"`). The legacy key is
  accepted during the deprecation window (see Implementation notes).

## Implementation notes

### Engine consumer signature

In `backend/app/services/workflow_engine.py`, after a node completes,
the engine reads `result.output.get("_hint")` and dispatches by `kind`:

```python
hint = result.output.get("_hint") if result.output else None
if hint is None:
    # No hint — engine follows static graph edges
    next_nodes = static_successors(node, dag)
elif hint["kind"] == "branch":
    next_nodes = [hint["selected"]]
    skipped = [b for b in hint["alternatives"] if b != hint["selected"]]
    for s in skipped:
        emit_event(run_id, "step.skipped", {"step_id": s, "reason": "branch_not_selected"})
elif hint["kind"] == "fanout":
    next_nodes = list(hint["branches"])
    # Record fan-in policy for the join node downstream
    register_fanin(node, hint["execution_mode"], hint.get("n"), hint["branches"])
else:
    raise ConfigurationError(f"unknown hint kind: {hint['kind']}")
```

### Executor refactors

- `parallelNode` — already emits the data needed. Replace
  `output = {"execution_mode": ..., "n": ..., "_fanout_hint": True}` with:

  ```python
  output = {
      "_hint": {
          "kind": "fanout",
          "execution_mode": execution_mode,
          "n": n,
          "branches": ctx.config.get("branches", []),
      }
  }
  ```

  The executor must read `branches` from its config (currently the engine
  computes them from graph edges; the executor needs them in config so
  the hint is self-contained).

- `condition` / `switch` (when ported) — must return:

  ```python
  output = {
      "_hint": {
          "kind": "branch",
          "selected": evaluated_label,
          "reason": short_text,
          "alternatives": all_labels,
      }
  }
  ```

  Engine state mutation from inside these executors is forbidden.

### Validation

The engine validates the hint shape on receipt:

- `kind` must be in `{"branch", "fanout"}` (initially; new kinds require
  this ADR amendment).
- For `branch`: `selected` must be a string, must appear in `alternatives`.
- For `fanout`: `execution_mode` in `{"all", "any", "n_of_m"}`,
  `branches` non-empty list of strings, `n` integer ≥ 1 when
  `execution_mode = "n_of_m"` and ≤ `len(branches)`.

### Forbidden

- Executors writing to engine state (e.g. mutating `ctx.engine_state`).
- Executors calling other executors directly.
- Executors emitting events other than via `NodeResult` — events come from
  the engine after consuming the hint (see ADR-002).

## See also

- ADR-001 — `definition_snapshot` carries the static DAG that the engine
  traverses; hints supplement, not replace, the static topology
- ADR-002 — engine-emitted `step.skipped`, `step.started`, `step.completed`
  events are the authoritative trace; hints are part of the
  `step.completed` payload
- ADR-005 — pause/resume on a fan-in node uses the engine's recorded
  fan-in policy; checkpointer durability is required for cross-restart
  joins
