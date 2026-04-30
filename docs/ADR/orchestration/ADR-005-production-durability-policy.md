# ADR-005: Production Durability Policy for the LangGraph Checkpointer

- **Status:** ACCEPTED
- **Namespace:** orchestration
- **Date:** 2026-04-29
- **Supersedes:** none
- **Superseded by:** none

## Context

The LangGraph checkpointer is the substrate for run pause/resume, retry,
and crash recovery. Its current behaviour is documented in
`backend/app/langgraph/checkpointer.py`:

- Default backend is `postgres` (line 99).
- On any failure to construct the Postgres saver (`ImportError` line 142,
  any `Exception` line 152), the function silently falls back to
  `MemorySaver` and returns it as if everything is healthy (lines 142–162).
- `worker.py` line 506 documents the env var but does not enforce
  production safety: "set LANGGRAPH_CHECKPOINTING=memory (default) for
  in-process state, or LANGGRAPH_CHECKPOINTING=postgres" — note the
  comment incorrectly claims `memory` is the default; the code default
  is `postgres`. (See "Inconsistencies discovered" in the index README.)

Failure mode: a production instance with a misconfigured `DATABASE_URL`
or missing `langgraph-checkpoint-postgres` package starts, logs a
warning, and then runs every workflow against in-memory checkpoints. On
crash or restart every in-flight run is lost with no recovery. The
operator sees no error.

This is unacceptable in production. Durability must be a hard precondition
for serving traffic.

## Decision

In production, a non-functional Postgres checkpointer is **fatal**. The
process refuses to start.

`MemorySaver` is permitted only in non-production environments and only
when explicitly opted into.

### Environment classification

Two environment variables drive the policy:

| Variable | Values | Default |
|---|---|---|
| `ARCHON_ENV` | `production`, `staging`, `dev`, `test` | `dev` |
| `LANGGRAPH_CHECKPOINTING` | `postgres`, `memory`, `disabled` (and the legacy aliases `false`, `0`, `off`, `none` for `disabled`) | `postgres` |

The startup matrix:

| `ARCHON_ENV` | `LANGGRAPH_CHECKPOINTING` | Behaviour |
|---|---|---|
| `production` | `postgres` (default) | Postgres saver MUST initialise. Any failure is FATAL — process exits non-zero. |
| `production` | `memory` | REJECTED — process exits non-zero on startup with explicit error. |
| `production` | `disabled` | REJECTED — process exits non-zero on startup with explicit error. |
| `staging` | `postgres` | Same as production. Failure is FATAL. |
| `staging` | `memory` | REJECTED. |
| `dev` / `test` | any | All values permitted. `memory` and `disabled` are advisory-warning, not fatal. |
| unset | any | Treated as `dev`. |

In short: any environment classified as `production` or `staging` requires
a functioning Postgres checkpointer. `memory` is only legal when
`ARCHON_ENV` is `dev` or `test`.

### Startup-check timing

Durability is checked **before** the API server begins accepting requests
and **before** the worker enters its event loop:

- API server: in `app/main.py` (or equivalent ASGI startup hook) the
  startup task awaits `get_checkpointer()` and verifies it returned a
  Postgres saver if the environment requires one. If not, raise
  `SystemExit(1)` synchronously before the FastAPI lifespan completes.
- Worker: in `worker.py` `main()` (line 498), before `asyncio.gather`
  spawns the loops, perform the same check.

Failing to check at startup is a violation. The check MUST run before any
HTTP listener is bound or any drain tick fires.

### Error message format

Fatal startup errors MUST be emitted as a single structured log line at
level `CRITICAL` followed by an unconditional `SystemExit(1)`. The log
fields:

```
event="checkpointer_durability_failed"
archon_env="production"
langgraph_checkpointing="postgres"
reason="<short cause: import_error|connect_error|setup_error|invalid_config>"
detail="<exception class name and message, truncated to 500 chars>"
remediation="Set DATABASE_URL to a reachable PostgreSQL DSN with langgraph-checkpoint-postgres installed; or set ARCHON_ENV=dev to permit MemorySaver"
```

Specifically prohibited: silent fallback, `WARNING`-level downgrade,
`MemorySaver` substitution.

### Code changes (concrete)

`backend/app/langgraph/checkpointer.py` `get_checkpointer()` is replaced
with policy-aware behaviour:

```python
async def get_checkpointer() -> BaseCheckpointSaver | None:
    global _saver, _saver_initialized
    if _saver_initialized:
        return _saver

    env = os.getenv("ARCHON_ENV", "dev").lower().strip()
    backend = os.getenv("LANGGRAPH_CHECKPOINTING", "postgres").lower().strip()
    is_durable_env = env in {"production", "staging"}

    # Policy gate: durable env + non-postgres backend = fatal
    if is_durable_env and backend != "postgres":
        _fatal_durability(
            reason="invalid_config",
            detail=f"ARCHON_ENV={env} requires LANGGRAPH_CHECKPOINTING=postgres, got {backend}",
        )

    if backend in _DISABLED_VALUES:
        _saver = None
        _saver_initialized = True
        return None

    if backend == "memory":
        # Reachable only in dev/test (gate above blocks durable env)
        from langgraph.checkpoint.memory import MemorySaver
        _saver = MemorySaver()
        _saver_initialized = True
        return _saver

    # backend == postgres
    try:
        from langgraph.checkpoint.postgres.aio import (
            AsyncConnectionPool, AsyncPostgresSaver,
        )
    except ImportError as exc:
        if is_durable_env:
            _fatal_durability(reason="import_error", detail=str(exc))
        # dev fallback as today
        from langgraph.checkpoint.memory import MemorySaver
        _saver = MemorySaver()
        _saver_initialized = True
        return _saver

    try:
        dsn = _get_db_dsn()
        pool = AsyncConnectionPool(
            conninfo=dsn, max_size=5,
            kwargs={"autocommit": True, "prepare_threshold": 0},
            open=False,
        )
        await pool.open()
        saver = AsyncPostgresSaver(conn=pool)
        await saver.setup()
        _saver = saver
        _saver_initialized = True
        return saver
    except Exception as exc:
        if is_durable_env:
            reason = "connect_error" if "connect" in repr(exc).lower() else "setup_error"
            _fatal_durability(reason=reason, detail=f"{type(exc).__name__}: {exc}")
        # dev fallback
        from langgraph.checkpoint.memory import MemorySaver
        _saver = MemorySaver()
        _saver_initialized = True
        return _saver


def _fatal_durability(*, reason: str, detail: str) -> None:
    logger.critical(
        "checkpointer_durability_failed",
        extra={
            "archon_env": os.getenv("ARCHON_ENV", "dev"),
            "langgraph_checkpointing": os.getenv("LANGGRAPH_CHECKPOINTING", "postgres"),
            "reason": reason,
            "detail": detail[:500],
            "remediation": (
                "Set DATABASE_URL to a reachable PostgreSQL DSN with "
                "langgraph-checkpoint-postgres installed; or set ARCHON_ENV=dev "
                "to permit MemorySaver"
            ),
        },
    )
    raise SystemExit(1)
```

The function still returns `None` for the explicitly-disabled case, but
disabled is forbidden in durable environments by the policy gate.

## Consequences

### Positive

- Production cannot run without durability. A misconfigured deploy fails
  fast with a clear remediation message instead of corrupting run state
  silently.
- Operators see a `CRITICAL` event tied to a non-zero exit, which alerts
  trip on. The current `WARNING` log does not.
- Test and dev workflows are unaffected — `memory` remains the simple
  in-process option.

### Negative

- A previously "soft" failure mode is now hard. Deployments that used to
  start with degraded durability now refuse to start. This is the point,
  but it requires deploy pipelines to set `ARCHON_ENV` correctly.
- Container images and CI runners that don't classify themselves
  (`ARCHON_ENV` unset) default to `dev`. Production deployment manifests
  MUST set `ARCHON_ENV=production` explicitly.

### Neutral

- The legacy `disabled`/`false`/`0`/`off`/`none` aliases are retained for
  dev compatibility.
- The DSN resolution chain (`_get_db_dsn`, lines 44–79) is unchanged.

## Implementation notes

### Required deployment manifest changes

- Production Helm chart / docker-compose / launchd plist MUST set
  `ARCHON_ENV=production`.
- `DATABASE_URL` (or `ARCHON_DATABASE_URL` or `LANGGRAPH_CHECKPOINT_DSN`)
  MUST be reachable.
- `langgraph-checkpoint-postgres` MUST be in the production wheel set.

### Worker comment fix

`worker.py` line 506 contains a comment that says
"set LANGGRAPH_CHECKPOINTING=memory (default)" — the actual default is
`postgres`. This comment must be updated as part of the implementation
to read:

> Checkpointing default is `postgres`. In production this is required and
> failures are fatal. Set `LANGGRAPH_CHECKPOINTING=memory` only in dev or
> test environments where durability is not needed.

### Test plan (informative)

- Unit: `ARCHON_ENV=production` + simulated import error -> `SystemExit(1)`
  with `event="checkpointer_durability_failed"` log.
- Unit: `ARCHON_ENV=production` + simulated connect error -> same.
- Unit: `ARCHON_ENV=production` + `LANGGRAPH_CHECKPOINTING=memory` ->
  `SystemExit(1)` with `reason="invalid_config"`.
- Unit: `ARCHON_ENV=dev` + `LANGGRAPH_CHECKPOINTING=memory` -> succeeds,
  returns `MemorySaver`.
- Integration: API server start with bad DSN in production -> process
  exits non-zero before binding port.

### Forbidden

- Catching `SystemExit` to keep the server running.
- Adding new fallback paths without amending this ADR.
- Treating `staging` as non-durable.

## See also

- ADR-001 — durability is per-run-row; the checkpointer threads through
  every `WorkflowRun` execution
- ADR-002 — `run.paused` and `run.resumed` events are emitted by the
  checkpointer hooks; they MUST NOT be emitted by `MemorySaver` runs in
  production (because production rejects `MemorySaver`)
- ADR-006 — the legacy `Execution` write path does NOT use the
  checkpointer; runs migrated to `WorkflowRun` inherit the durability
  policy
