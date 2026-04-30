"""Idempotency contract enforcement for run creation (ADR-004).

Public surface:
  - validate_key(key) — raise HTTPException(400) on bad format
  - compute_input_hash(*, kind, workflow_id, agent_id, input_data) — sha256 hex
  - check_and_acquire(session, *, tenant_id, idempotency_key, input_hash)
    Returns (existing_run, hit) where:
        hit=False  → no prior run exists for (tenant_id, key); caller proceeds
        hit=True   → prior run exists with matching input_hash (replay)
    Raises IdempotencyConflict when prior run exists but input_hash differs.

The DB-level partial unique index ``uq_workflow_runs_tenant_idem`` is the
ultimate source of truth — this module performs an opportunistic SELECT
first and the caller relies on the IntegrityError path for races.

ADR reference: docs/adr/orchestration/ADR-004-idempotency-contract.md
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select


_KEY_RE = re.compile(r"^[A-Za-z0-9_\-:.]{1,255}$")


class IdempotencyConflict(Exception):
    """Raised when an idempotency key has been used with a different input.

    Routes catch this and return HTTP 409 with the existing run id.
    """

    def __init__(self, *, key: str, existing_run_id: UUID) -> None:
        super().__init__(
            f"idempotency key {key!r} already used with different input "
            f"(existing run: {existing_run_id})"
        )
        self.key = key
        self.existing_run_id = existing_run_id


def validate_key(key: str) -> None:
    """Validate idempotency key format per ADR-004 §Key sources.

    Raises HTTPException(400) on invalid format. Empty/None passes silently —
    callers should check for None before calling.
    """
    if not isinstance(key, str) or not _KEY_RE.match(key):
        raise HTTPException(
            status_code=400,
            detail="Idempotency key must match ^[A-Za-z0-9_\\-:.]{1,255}$",
        )


def compute_input_hash(
    *,
    kind: str,
    workflow_id: UUID | None,
    agent_id: UUID | None,
    input_data: dict[str, Any] | None,
) -> str:
    """Compute sha256 of canonical_json(input envelope).

    Per ADR-004 §Hash computation. Order of fields: kind, workflow_id,
    agent_id, input_data.
    """
    obj = {
        "kind": kind,
        "workflow_id": str(workflow_id) if workflow_id is not None else None,
        "agent_id": str(agent_id) if agent_id is not None else None,
        "input_data": input_data or {},
    }
    body = json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


async def check_and_acquire(
    session: AsyncSession,
    *,
    tenant_id: UUID | None,
    idempotency_key: str,
    input_hash: str,
) -> tuple[Any | None, bool]:
    """Look up an existing WorkflowRun by (tenant_id, idempotency_key).

    Returns:
        (None, False)         — no existing run; caller proceeds with insert.
        (existing_run, True)  — existing run with matching input_hash (replay).

    Raises:
        IdempotencyConflict   — existing run with different input_hash.

    The DB partial unique index guarantees at most one match. This function
    does NOT itself insert — the caller commits the new row and handles
    IntegrityError as a race for re-resolution.
    """
    # Local import avoids circular dependency between services packages.
    from app.models.workflow import WorkflowRun

    stmt = select(WorkflowRun).where(
        WorkflowRun.tenant_id == tenant_id,
        WorkflowRun.idempotency_key == idempotency_key,
    )
    result = await session.exec(stmt)
    existing = result.first()

    if existing is None:
        return None, False

    if existing.input_hash != input_hash:
        raise IdempotencyConflict(
            key=idempotency_key,
            existing_run_id=existing.id,
        )

    return existing, True


__all__ = [
    "IdempotencyConflict",
    "check_and_acquire",
    "compute_input_hash",
    "validate_key",
]
