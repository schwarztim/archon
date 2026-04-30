"""Tamper-evident hash chain for the audit_logs table (Phase 4 / WS13).

Every audit row carries a SHA-256 link to the previous row in the same
tenant's chain.  Tampering with any historical field — action, status_code,
ip_address, etc. — breaks the chain and is detectable by ``verify_audit_chain``.

Design notes
------------
* Each tenant has an independent chain rooted at ``"genesis"`` so one tenant
  cannot poison another tenant's chain.
* The canonical payload is built from the full set of fields that must be
  hash-protected (id + timestamp + every immutable field).  Adding or removing
  a field requires a backfill — the hash is the authoritative checksum.
* ``append_audit_log`` issues a ``SELECT … FOR UPDATE`` on Postgres so
  concurrent appends within the same tenant serialize on the chain head.
  On SQLite (tests) the locking hint is silently ignored — the SQLite engine
  serializes writes already, so the chain remains intact.

This module is *separate* from ``WorkflowRunEvent`` chaining (W1.1) which
operates per-run on a different table.  Do not conflate the two.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections import defaultdict
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog

logger = logging.getLogger(__name__)


# Per-tenant in-process append lock.  Postgres uses SELECT … FOR UPDATE for
# cross-process serialisation; this lock additionally covers the case where
# multiple coroutines in the same process race for the chain head before the
# DB even sees their queries (notably under SQLite where FOR UPDATE is a no-op
# and the async driver lets reads interleave between writes).
_TENANT_LOCKS: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


def _tenant_lock(tenant_id: str) -> asyncio.Lock:
    """Return a per-tenant asyncio lock."""
    return _TENANT_LOCKS[tenant_id]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Sentinel prev_hash for the first entry in any chain.
GENESIS_HASH = "genesis"

#: Set of fields that participate in the canonical hashed payload.  Listed in
#: deterministic order (the JSON dumper sorts keys, but keeping the list
#: explicit makes review easier).
HASH_PROTECTED_FIELDS: tuple[str, ...] = (
    "id",
    "tenant_id",
    "correlation_id",
    "actor_id",
    "action",
    "resource_type",
    "resource_id",
    "status_code",
    "ip_address",
    "user_agent",
    "details",
    "created_at",
)


# ---------------------------------------------------------------------------
# Canonical payload + hash computation
# ---------------------------------------------------------------------------


def canonical_audit_payload(row: AuditLog) -> str:
    """Return a stable JSON representation of *row* for hashing.

    The output is sorted-key JSON over :data:`HASH_PROTECTED_FIELDS`; any field
    value is coerced via ``default=str`` so UUIDs and datetimes serialise
    consistently.  Two rows with identical protected fields always produce the
    same string.
    """
    payload: dict[str, Any] = {
        "id": str(row.id) if row.id is not None else None,
        "tenant_id": row.tenant_id,
        "correlation_id": row.correlation_id,
        "actor_id": str(row.actor_id) if row.actor_id is not None else None,
        "action": row.action,
        "resource_type": row.resource_type,
        "resource_id": row.resource_id,
        "status_code": row.status_code,
        "ip_address": row.ip_address,
        "user_agent": row.user_agent,
        "details": row.details,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
    return json.dumps(payload, sort_keys=True, default=str)


def compute_audit_hash(prev_hash: str, payload_json: str) -> str:
    """Return ``sha256(prev_hash + payload_json)`` as a lowercase hex digest."""
    return hashlib.sha256(f"{prev_hash}{payload_json}".encode()).hexdigest()


# ---------------------------------------------------------------------------
# Append (write side)
# ---------------------------------------------------------------------------


async def _select_chain_head(
    session: AsyncSession, tenant_id: str
) -> str:
    """Return the most recent ``hash`` for *tenant_id* (or genesis)."""
    stmt = (
        select(AuditLog.hash)
        .where(AuditLog.tenant_id == tenant_id)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(1)
    )
    # Postgres: FOR UPDATE serialises concurrent appenders on the chain head.
    # SQLite: with_for_update is a no-op; serialised writes already.
    try:
        stmt = stmt.with_for_update()
    except Exception:
        # Some dialects reject the hint at SQL-compile time.  Best effort.
        logger.debug("audit_chain: with_for_update not supported; falling back")
    try:
        result = await session.execute(stmt)
        prev = result.scalar()
    except OperationalError:
        # Some dialects (very old SQLite builds, broken async drivers) reject
        # FOR UPDATE at execute time.  Retry without the hint.
        plain_stmt = (
            select(AuditLog.hash)
            .where(AuditLog.tenant_id == tenant_id)
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .limit(1)
        )
        result = await session.execute(plain_stmt)
        prev = result.scalar()
    return prev or GENESIS_HASH


async def append_audit_log(
    session: AsyncSession,
    *,
    tenant_id: str,
    actor_id: UUID | None,
    action: str,
    resource_type: str | None = None,
    resource_id: str | None = None,
    status_code: int | None = None,
    correlation_id: str = "",
    details: dict[str, Any] | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> AuditLog:
    """Append a tamper-evident :class:`AuditLog` row.

    Atomically:
      1. Selects the latest hash for *tenant_id* (genesis when empty).
      2. Builds the canonical payload over all protected fields.
      3. Computes the SHA-256 link.
      4. Inserts the row and commits.

    Concurrency safety: a per-tenant asyncio lock serialises in-process
    appenders so two coroutines cannot observe the same chain head.  On
    Postgres the SELECT additionally takes a row-level lock (FOR UPDATE) for
    cross-process serialisation.  On SQLite FOR UPDATE is a no-op but the
    asyncio lock still applies.

    Returns
    -------
    AuditLog
        The persisted entry with ``hash`` and ``prev_hash`` populated.
    """
    async with _tenant_lock(tenant_id):
        prev_hash = await _select_chain_head(session, tenant_id)

        # Pre-allocate id and timestamp so the canonical payload includes them.
        row_id = uuid4()
        created_at = datetime.utcnow()

        entry = AuditLog(
            id=row_id,
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            actor_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            status_code=status_code,
            ip_address=ip_address,
            user_agent=user_agent,
            details=details,
            hash="",  # placeholder; computed below
            prev_hash=prev_hash,
            created_at=created_at,
        )

        payload = canonical_audit_payload(entry)
        entry.hash = compute_audit_hash(prev_hash, payload)

        session.add(entry)
        await session.commit()
        await session.refresh(entry)
        return entry


# ---------------------------------------------------------------------------
# Verify (read side)
# ---------------------------------------------------------------------------


async def verify_audit_chain(
    session: AsyncSession,
    *,
    tenant_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> dict[str, Any]:
    """Recompute and verify the hash chain.

    Parameters
    ----------
    session
        Active async DB session.
    tenant_id
        When supplied, verify only that tenant's chain.  When ``None``,
        verify every tenant present in the table independently — each tenant
        chain is rooted at genesis.  The aggregate ``chain_verified`` is the
        AND of every tenant's verdict.
    since, until
        Optional inclusive timestamp bounds.  Limiting the scan removes the
        ability to detect a corruption *before* ``since`` (the chain head will
        not match genesis), so the function reports the missing-prefix as a
        corruption only when ``since`` is None — see implementation notes
        below.

    Returns
    -------
    dict
        ``{"chain_verified": bool, "total_events": int,
           "first_corruption_at_id": UUID | None,
           "first_corruption_field": str | None}``

        ``first_corruption_field`` is ``"prev_hash"`` for chain-link breaks or
        ``"hash"`` for payload tampering.  The reported corruption point is
        the *earliest* (in chronological order) violation found across all
        scanned tenants.
    """
    # ── Discover tenants in scope ────────────────────────────────────
    if tenant_id is not None:
        tenants: list[str] = [tenant_id]
    else:
        tenants_stmt = select(AuditLog.tenant_id).distinct()
        tres = await session.execute(tenants_stmt)
        tenants = sorted({t for (t,) in tres.all()})

    total_events = 0
    first_corruption_at_id: UUID | None = None
    first_corruption_field: str | None = None
    first_corruption_ts: datetime | None = None

    for tid in tenants:
        # Pull rows for this tenant in chronological order.  Use the same
        # tiebreaker as the writer so verify is deterministic when multiple
        # rows share a created_at value.
        stmt = (
            select(AuditLog)
            .where(AuditLog.tenant_id == tid)
            .order_by(AuditLog.created_at.asc(), AuditLog.id.asc())
        )
        if since is not None:
            stmt = stmt.where(AuditLog.created_at >= since)
        if until is not None:
            stmt = stmt.where(AuditLog.created_at <= until)
        result = await session.execute(stmt)
        rows = list(result.scalars().all())

        # Decide the expected starting prev_hash.  When the caller passed
        # `since`, we cannot verify the prefix, so we trust the first row's
        # claimed prev_hash and only check internal consistency.  Without
        # `since` the first row must chain to genesis.
        if since is None:
            expected_prev = GENESIS_HASH
        else:
            expected_prev = rows[0].prev_hash if rows else GENESIS_HASH

        for row in rows:
            total_events += 1

            # 1) prev_hash linkage check.
            if row.prev_hash != expected_prev:
                if (
                    first_corruption_ts is None
                    or row.created_at < first_corruption_ts
                ):
                    first_corruption_at_id = row.id
                    first_corruption_field = "prev_hash"
                    first_corruption_ts = row.created_at

            # 2) Payload tamper check (recompute the hash).
            payload = canonical_audit_payload(row)
            recomputed = compute_audit_hash(row.prev_hash, payload)
            if recomputed != row.hash:
                if (
                    first_corruption_ts is None
                    or row.created_at < first_corruption_ts
                ):
                    first_corruption_at_id = row.id
                    first_corruption_field = "hash"
                    first_corruption_ts = row.created_at

            # Move forward — chain to the row's *stored* hash so a single
            # tampered link does not cascade into N false-positives.
            expected_prev = row.hash

    return {
        "chain_verified": first_corruption_at_id is None,
        "total_events": total_events,
        "first_corruption_at_id": first_corruption_at_id,
        "first_corruption_field": first_corruption_field,
    }


__all__ = [
    "GENESIS_HASH",
    "HASH_PROTECTED_FIELDS",
    "append_audit_log",
    "canonical_audit_payload",
    "compute_audit_hash",
    "verify_audit_chain",
]
