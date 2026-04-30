# ADR-004: Idempotency Contract for Run Creation

- **Status:** ACCEPTED
- **Namespace:** orchestration
- **Date:** 2026-04-29
- **Supersedes:** none
- **Superseded by:** none

## Context

Run creation endpoints (`POST /executions`, `POST /execute`,
`POST /agents/{agent_id}/execute`) currently have no idempotency guard.
A retried request from a flaky network — common in CI runners and mobile
clients — produces duplicate runs. The legacy `Execution.create`
(`backend/app/services/execution_service.py` line 539) inserts a fresh
row on every call.

Existing routes (`backend/app/routes/executions.py` lines 81–142,
`backend/app/routes/agents.py` lines 133–156) accept the same input
twice and dispatch twice. There is no fingerprint, no deduplication, no
header recognition.

A grep for "idempotency" in the backend returned zero matches. This
contract is being established new.

## Decision

Run creation endpoints accept an idempotency key. Submitting the same key
twice for the same tenant returns the originally created run on the second
call instead of creating a duplicate.

### Key sources (precedence)

1. `X-Idempotency-Key` HTTP header — **wins** if present.
2. `idempotency_key` field in the request body — used only when the
   header is absent.

If both are present and the header value differs from the body value, the
header value is used and the body value is silently ignored. Clients
SHOULD send only one.

If neither is supplied the endpoint behaves as today — every call creates
a fresh run.

Keys are opaque strings, 1–255 characters, validated against
`^[A-Za-z0-9_\-:.]{1,255}$`. Any other value returns `400 Bad Request`.

### Scope

Idempotency keys are scoped per tenant. The unique constraint is on
`(tenant_id, idempotency_key)` on the `workflow_runs` table. Two tenants
can independently use the same key.

### Behaviour

| Case | Same `(tenant_id, key)` exists? | Same input hash? | Response |
|---|---|---|---|
| New | No | n/a | `201 Created` — new run, body returned |
| Replay | Yes | Yes | `200 OK` — original run returned, no new row |
| Conflict | Yes | No | `409 Conflict` — error body, no new row |

Where "same input hash" is defined as identical `sha256` over the
canonical JSON representation of:

```json
{
  "kind": "<workflow|agent>",
  "workflow_id": "<uuid|null>",
  "agent_id": "<uuid|null>",
  "input_data": {...}
}
```

`canonical_json` rules match ADR-002 (sorted keys, no insignificant
whitespace, UTF-8). The hash is stored in `workflow_runs.input_hash` so
the conflict check is a single column comparison.

The 409 response body:

```json
{
  "error": {
    "code": "idempotency_conflict",
    "message": "Idempotency key already used with different input.",
    "key": "<provided key>",
    "existing_run_id": "<uuid>"
  },
  "meta": {...}
}
```

The 200 replay response body is identical to the original 201 response,
except for the `meta.replay = true` flag and the existing `run.created_at`
(not the current time).

### Schema additions

`workflow_runs` gains two columns:

| Column | Type | Notes |
|---|---|---|
| `idempotency_key` | `VARCHAR(255) NULL` | Nullable — absence preserves today's "always create" behaviour |
| `input_hash` | `CHAR(64) NULL` | sha256 hex; NULL when `idempotency_key` is NULL |

Constraint: a partial unique index on `(tenant_id, idempotency_key)`
where `idempotency_key IS NOT NULL`.

#### Postgres syntax

```sql
CREATE UNIQUE INDEX uq_workflow_runs_tenant_idem
  ON workflow_runs (tenant_id, idempotency_key)
  WHERE idempotency_key IS NOT NULL;
```

#### SQLite syntax (Alembic-friendly)

SQLite supports partial unique indexes with the same syntax as Postgres
since SQLite 3.8.0. Both engines accept:

```sql
CREATE UNIQUE INDEX uq_workflow_runs_tenant_idem
  ON workflow_runs (tenant_id, idempotency_key)
  WHERE idempotency_key IS NOT NULL;
```

Alembic migration (works on both):

```python
op.create_index(
    "uq_workflow_runs_tenant_idem",
    "workflow_runs",
    ["tenant_id", "idempotency_key"],
    unique=True,
    sqlite_where=sa.text("idempotency_key IS NOT NULL"),
    postgresql_where=sa.text("idempotency_key IS NOT NULL"),
)
```

Both `sqlite_where` and `postgresql_where` are honoured by their
respective dialects; the migration is portable.

## Consequences

### Positive

- Network retries from clients are safe by default if they send a key.
- Concurrent duplicate POSTs converge: the database unique-constraint
  serialises them; one wins, the other reads back the winner.
- Conflict (`409`) signals a real client bug — same key, different input
  — instead of silently creating divergent runs.

### Negative

- Every endpoint that creates a `WorkflowRun` must extract the key from
  header or body, compute the hash, attempt the insert, and handle
  unique-violation as a deduplication path. Concrete impact:
  - `routes/executions.py` `create_and_run_execution` (line 81)
  - `routes/executions.py` `create_execution` (line 106)
  - `routes/executions.py` `replay_execution` (line 194)
  - `routes/agents.py` `execute_agent` (line 133)
  - `routes/agents.py` `/agents/{agent_id}/execute` (line 133, alternate)
- Replay endpoint (`POST /executions/{id}/replay`) needs a documented
  default key strategy (RECOMMENDED: `replay:<original_id>:<utc_minute>` —
  not in the binding part of this ADR).

### Neutral

- Existing rows have `idempotency_key = NULL` and are not affected by
  the partial unique index.
- The `input_hash` column is computed even when no key is supplied
  (zero cost, helps observability later).

## Implementation notes

### Insert flow (every endpoint)

```python
def resolve_idempotency_key(req: Request, body: BaseModel) -> str | None:
    header = req.headers.get("X-Idempotency-Key")
    if header is not None:
        validate_key(header)  # raises 400 on bad format
        return header
    body_key = getattr(body, "idempotency_key", None)
    if body_key is not None:
        validate_key(body_key)
        return body_key
    return None


async def create_run_with_idempotency(
    session: AsyncSession,
    tenant_id: UUID,
    new_run: WorkflowRun,
    key: str | None,
) -> tuple[WorkflowRun, bool, bool]:
    """Returns (run, created, conflict).
    - created=True, conflict=False  ->  201 Created
    - created=False, conflict=False ->  200 OK (replay)
    - created=False, conflict=True  ->  409 Conflict
    """
    if key is None:
        session.add(new_run)
        await session.commit()
        await session.refresh(new_run)
        return new_run, True, False

    new_run.idempotency_key = key
    new_run.input_hash = compute_input_hash(new_run)
    try:
        session.add(new_run)
        await session.commit()
        await session.refresh(new_run)
        return new_run, True, False
    except IntegrityError:
        await session.rollback()
        existing = await session.exec(
            select(WorkflowRun).where(
                WorkflowRun.tenant_id == tenant_id,
                WorkflowRun.idempotency_key == key,
            )
        )
        existing = existing.first()
        if existing is None:
            # Race — should not happen, but retry once
            raise
        if existing.input_hash != new_run.input_hash:
            return existing, False, True   # conflict
        return existing, False, False       # replay
```

### Validator

```python
_KEY_RE = re.compile(r"^[A-Za-z0-9_\-:.]{1,255}$")

def validate_key(key: str) -> None:
    if not _KEY_RE.match(key):
        raise HTTPException(
            status_code=400,
            detail="X-Idempotency-Key must match ^[A-Za-z0-9_\\-:.]{1,255}$",
        )
```

### Hash computation

```python
def compute_input_hash(run: WorkflowRun) -> str:
    obj = {
        "kind": run.kind,
        "workflow_id": str(run.workflow_id) if run.workflow_id else None,
        "agent_id": str(run.agent_id) if run.agent_id else None,
        "input_data": run.input_data or {},
    }
    body = json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(body).hexdigest()
```

### TTL / cleanup

Keys are not garbage-collected. A run's idempotency window equals the
lifetime of the run row. If a tenant wants the same key reusable, they
must delete the prior run (separate audit concern; out of scope here).

### Forbidden

- Reading the key from query string — query strings appear in access logs
  and break replay safety.
- Using a non-tenant scope (e.g. global) — would let one tenant block a
  key for all others.
- Returning 201 on a replay — clients use the status code to decide if a
  run was created; lying corrupts their state machine.

## See also

- ADR-001 — `idempotency_key` and `input_hash` are added to the same
  `workflow_runs` schema being reshaped there
- ADR-002 — replay returns the original run; no new `run.created` event
  is emitted on replay
- ADR-006 — the legacy `Execution` table is NOT given idempotency keys;
  the contract applies to `workflow_runs` only
