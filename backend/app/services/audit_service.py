"""AuditService — tamper-evident hash-chain audit logging.

Consolidates three legacy audit tables into a single append-only
audit_logs table with SHA-256 hash chain for tamper detection.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog

logger = logging.getLogger(__name__)


def _compute_hash(prev_hash: str, entry_data: dict[str, Any]) -> str:
    """Compute SHA-256(prev_hash + JSON(entry_data, sorted keys))."""
    content = json.dumps(entry_data, sort_keys=True, default=str)
    return hashlib.sha256(f"{prev_hash}{content}".encode()).hexdigest()


class AuditService:
    """Append-only audit service with tamper-evident hash chain.

    Each tenant has an independent chain rooted at the genesis sentinel.
    The hash covers all immutable fields so any modification is detectable.
    """

    # ------------------------------------------------------------------ #
    # Write                                                                #
    # ------------------------------------------------------------------ #

    @staticmethod
    async def log_action(
        *,
        session: AsyncSession,
        tenant_id: str,
        correlation_id: str,
        actor_id: UUID | None,
        action: str,
        resource_type: str | None = None,
        resource_id: str | None = None,
        status_code: int | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> AuditLog:
        """Record an action with tamper-evident hash chain.

        Queries the most recent hash for the tenant to build the chain link,
        then inserts a new entry.  Uses a fresh SELECT … ORDER BY created_at DESC
        rather than relying on in-memory state so it is safe across processes.

        Args:
            session: Active async database session.
            tenant_id: Resolved tenant identifier (from TenantMiddleware).
            correlation_id: Per-request UUID string (from AuditMiddleware).
            actor_id: Authenticated user UUID or None for system/anonymous calls.
            action: Human-readable action string, e.g. "POST /api/v1/agents".
            resource_type: Entity type, e.g. "agent", "user".
            resource_id: String representation of the affected resource ID.
            status_code: HTTP response status code.
            ip_address: Client IP address.
            user_agent: Client User-Agent header value.
            details: Arbitrary extra context (stored as JSON).

        Returns:
            The persisted AuditLog entry.
        """
        # Fetch previous hash for this tenant's chain
        result = await session.execute(
            select(AuditLog.hash)
            .where(AuditLog.tenant_id == tenant_id)
            .order_by(AuditLog.created_at.desc())
            .limit(1)
        )
        prev_hash: str = result.scalar() or "genesis"

        # Build the canonical entry dict for hashing (no mutable fields)
        created_at = datetime.utcnow()
        entry_data: dict[str, Any] = {
            "tenant_id": tenant_id,
            "correlation_id": correlation_id,
            "actor_id": str(actor_id) if actor_id else None,
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "status_code": status_code,
            "ip_address": ip_address,
            "user_agent": user_agent,
            "created_at": created_at.isoformat(),
        }

        entry_hash = _compute_hash(prev_hash, entry_data)

        audit_entry = AuditLog(
            id=uuid4(),
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
            hash=entry_hash,
            prev_hash=prev_hash,
            created_at=created_at,
        )

        session.add(audit_entry)
        await session.commit()
        await session.refresh(audit_entry)
        return audit_entry

    # ------------------------------------------------------------------ #
    # Verify                                                               #
    # ------------------------------------------------------------------ #

    @staticmethod
    async def verify_chain(
        *,
        session: AsyncSession,
        tenant_id: str,
    ) -> dict[str, Any]:
        """Verify the integrity of the hash chain for a tenant.

        Walks every entry in chronological order and checks:
        1. ``entry.prev_hash`` matches the previous entry's hash.
        2. The stored ``entry.hash`` matches the recomputed hash.

        Returns:
            A dict with keys:
            - ``valid`` (bool): True if no tamper detected.
            - ``entries`` (int): Total entries checked.
            - ``errors`` (list[dict]): List of integrity violations (empty if valid).
        """
        result = await session.execute(
            select(AuditLog)
            .where(AuditLog.tenant_id == tenant_id)
            .order_by(AuditLog.created_at.asc())
        )
        entries = list(result.scalars().all())

        if not entries:
            return {"valid": True, "entries": 0, "errors": []}

        errors: list[dict[str, Any]] = []
        prev_hash = "genesis"

        for idx, entry in enumerate(entries):
            # Check prev_hash linkage
            if entry.prev_hash != prev_hash:
                errors.append(
                    {
                        "entry_id": str(entry.id),
                        "index": idx,
                        "error": (
                            f"prev_hash mismatch: expected {prev_hash!r}, "
                            f"got {entry.prev_hash!r}"
                        ),
                    }
                )

            # Recompute hash to check for tampering
            entry_data = {
                "tenant_id": entry.tenant_id,
                "correlation_id": entry.correlation_id,
                "actor_id": str(entry.actor_id) if entry.actor_id else None,
                "action": entry.action,
                "resource_type": entry.resource_type,
                "resource_id": entry.resource_id,
                "status_code": entry.status_code,
                "ip_address": entry.ip_address,
                "user_agent": entry.user_agent,
                "created_at": entry.created_at.isoformat(),
            }
            expected_hash = _compute_hash(prev_hash, entry_data)

            if entry.hash != expected_hash:
                errors.append(
                    {
                        "entry_id": str(entry.id),
                        "index": idx,
                        "error": (
                            f"hash mismatch: expected {expected_hash!r}, "
                            f"got {entry.hash!r}"
                        ),
                    }
                )

            prev_hash = entry.hash

        return {
            "valid": len(errors) == 0,
            "entries": len(entries),
            "errors": errors,
        }
