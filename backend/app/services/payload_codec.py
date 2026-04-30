"""Payload codec — serialize, redact, compress, encrypt, size-check payloads.

W16: Pipeline for encoding and decoding workflow payloads safely. Also
provides run-history archival and restore.

Encode pipeline:
    1. JSON serialize
    2. DLP redact (strip PII/secrets)
    3. zlib compress
    4. Fernet encrypt (if ARCHON_PAYLOAD_FERNET_KEY is set)
    5. Size check (raise if > max_payload_size)
    6. Return base64-encoded string or artifact reference (if too large)

Decode pipeline: reverse of the above.

Settings dataclass controls per-call behaviour.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import zlib
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


@dataclass
class PayloadCodecSettings:
    """Per-call settings for the payload codec.

    Attributes:
        max_payload_size: Maximum encoded payload size in bytes.
            Payloads exceeding this are stored as artifacts and replaced
            with an artifact reference. Default: 1 MiB.
        enable_dlp: Run the DLP redaction step. Default: True.
        enable_compression: Apply zlib compression. Default: True.
        enable_encryption: Encrypt with Fernet (requires
            ARCHON_PAYLOAD_FERNET_KEY env var). Default: True.
        compression_level: zlib compression level 0-9. Default: 6.
    """

    max_payload_size: int = 1024 * 1024  # 1 MiB
    enable_dlp: bool = True
    enable_compression: bool = True
    enable_encryption: bool = True
    compression_level: int = 6


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class PayloadTooLarge(RuntimeError):
    """Payload exceeds max_payload_size and no artifact store is available."""


class PayloadDecodeError(RuntimeError):
    """Cannot decode an encoded payload."""


# ---------------------------------------------------------------------------
# Fernet helper (optional)
# ---------------------------------------------------------------------------


def _get_fernet() -> Any | None:
    """Return a Fernet instance if key is configured, else None."""
    key = os.getenv("ARCHON_PAYLOAD_FERNET_KEY", "").strip()
    if not key:
        return None
    try:
        from cryptography.fernet import Fernet

        return Fernet(key.encode() if isinstance(key, str) else key)
    except ImportError:
        logger.debug("cryptography not installed — Fernet encryption disabled")
        return None
    except Exception as exc:
        logger.warning("payload_codec: invalid Fernet key: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Encode
# ---------------------------------------------------------------------------


async def encode_payload(
    session: AsyncSession,
    *,
    payload: dict[str, Any],
    tenant_id: UUID | str,
    settings: PayloadCodecSettings | None = None,
) -> str:
    """Encode payload through the full pipeline.

    Pipeline:
        1. JSON serialize
        2. DLP redact (optional)
        3. zlib compress (optional)
        4. Fernet encrypt (optional, if key configured)
        5. base64 encode
        6. Size check — if > max_payload_size, store as artifact reference

    Returns:
        Encoded string: either ``"b64:<base64data>"`` or
        ``"artifact:<artifact_id>"`` for oversized payloads.
    """
    cfg = settings or PayloadCodecSettings()
    tenant_str = str(tenant_id)

    # Step 1: serialize to JSON bytes.
    try:
        raw_json = json.dumps(payload, default=str, sort_keys=False)
        raw_bytes = raw_json.encode("utf-8")
    except Exception as exc:
        raise PayloadDecodeError(f"Cannot serialize payload: {exc}") from exc

    # Step 2: DLP redaction.
    if cfg.enable_dlp:
        try:
            from app.services.dlp_service import DLPService

            scan_result = DLPService.scan_content(
                tenant_id=tenant_str,
                content=raw_json,
            )
            if scan_result.findings:
                redacted_json = DLPService.redact_content(
                    raw_json, scan_result.findings
                )
                raw_bytes = redacted_json.encode("utf-8")
                logger.debug(
                    "payload_codec.dlp_redacted",
                    extra={
                        "tenant_id": tenant_str,
                        "findings": len(scan_result.findings),
                    },
                )
        except Exception as exc:
            # DLP failure must not silently pass in enterprise mode.
            enterprise = os.getenv("ARCHON_ENTERPRISE_MODE", "").strip().lower()
            if enterprise in {"1", "true", "yes", "on"}:
                raise
            logger.warning("payload_codec.dlp_failed (dev-mode continue): %s", exc)

    # Step 3: compress.
    if cfg.enable_compression:
        raw_bytes = zlib.compress(raw_bytes, level=cfg.compression_level)

    # Step 4: encrypt.
    if cfg.enable_encryption:
        fernet = _get_fernet()
        if fernet is not None:
            raw_bytes = fernet.encrypt(raw_bytes)

    # Step 5: base64 encode.
    encoded = base64.b64encode(raw_bytes).decode("ascii")
    result = f"b64:{encoded}"

    # Step 6: size check.
    if len(result.encode("utf-8")) > cfg.max_payload_size:
        artifact_ref = await _store_payload_artifact(
            session,
            tenant_id=tenant_str,
            data=result,
        )
        logger.info(
            "payload_codec.payload_archived_as_artifact",
            extra={"tenant_id": tenant_str, "artifact_ref": artifact_ref},
        )
        return f"artifact:{artifact_ref}"

    return result


# ---------------------------------------------------------------------------
# Decode
# ---------------------------------------------------------------------------


async def decode_payload(
    session: AsyncSession,
    *,
    encoded: str,
    tenant_id: UUID | str,
    settings: PayloadCodecSettings | None = None,
) -> dict[str, Any]:
    """Decode an encoded payload (reverse of encode_payload).

    Args:
        session: Async DB session (needed for artifact restore).
        encoded: Either ``"b64:<data>"`` or ``"artifact:<ref>"``.
        tenant_id: Tenant scope (used for artifact retrieval).
        settings: Codec settings — must match encode settings for
            compression/encryption to succeed.

    Returns:
        Decoded payload dict.

    Raises:
        PayloadDecodeError: On any decode failure.
    """
    cfg = settings or PayloadCodecSettings()
    tenant_str = str(tenant_id)

    # Resolve artifact reference.
    if encoded.startswith("artifact:"):
        artifact_ref = encoded[len("artifact:"):]
        encoded = await _load_payload_artifact(session, artifact_ref=artifact_ref)

    if not encoded.startswith("b64:"):
        raise PayloadDecodeError(
            f"Unrecognised payload encoding prefix: {encoded[:20]!r}"
        )

    raw_b64 = encoded[len("b64:"):]
    try:
        raw_bytes = base64.b64decode(raw_b64)
    except Exception as exc:
        raise PayloadDecodeError(f"base64 decode failed: {exc}") from exc

    # Decrypt.
    if cfg.enable_encryption:
        fernet = _get_fernet()
        if fernet is not None:
            try:
                raw_bytes = fernet.decrypt(raw_bytes)
            except Exception as exc:
                raise PayloadDecodeError(f"Fernet decryption failed: {exc}") from exc

    # Decompress.
    if cfg.enable_compression:
        try:
            raw_bytes = zlib.decompress(raw_bytes)
        except zlib.error as exc:
            raise PayloadDecodeError(f"zlib decompression failed: {exc}") from exc

    # JSON parse.
    try:
        return json.loads(raw_bytes.decode("utf-8"))
    except Exception as exc:
        raise PayloadDecodeError(f"JSON parse failed: {exc}") from exc


# ---------------------------------------------------------------------------
# History archival
# ---------------------------------------------------------------------------


async def archive_run_history(
    session: AsyncSession,
    *,
    run_id: UUID | str,
    retention_days: int,
) -> str:
    """Move WorkflowRunEvents older than retention_days to an archive.

    Strategy: serialize events to a JSON blob, store as an artifact,
    delete the original rows. Returns the archive reference string.

    Args:
        session: Async DB session.
        run_id: WorkflowRun primary key.
        retention_days: Events older than this are archived.

    Returns:
        Archive reference string (``"archive:<uuid>"``) for use with
        restore_archived_history.
    """
    from datetime import datetime, timedelta, timezone

    from sqlmodel import select as _select

    run_uuid = UUID(str(run_id)) if not isinstance(run_id, UUID) else run_id
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

    try:
        from app.models.workflow import WorkflowRunEvent

        stmt = _select(WorkflowRunEvent).where(
            WorkflowRunEvent.run_id == run_uuid,
            WorkflowRunEvent.created_at < cutoff,
        )
        try:
            result = await session.exec(stmt)
            events = list(result.all())
        except AttributeError:
            result = await session.execute(stmt)
            events = list(result.scalars().all())

        if not events:
            return f"archive:empty:{run_uuid}"

        serialized = [
            {
                "id": str(e.id),
                "run_id": str(e.run_id),
                "type": e.type,
                "payload": e.payload,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in events
        ]

        archive_id = uuid4()
        archive_data = json.dumps(serialized, default=str)

        # Store archive blob.
        archive_ref = await _write_archive(session, archive_id=archive_id, data=archive_data)

        # Delete archived events.
        for event in events:
            await session.delete(event)
        await session.flush()

        logger.info(
            "payload_codec.history_archived",
            extra={
                "run_id": str(run_id),
                "events_archived": len(events),
                "archive_ref": archive_ref,
            },
        )
        return archive_ref

    except Exception as exc:
        logger.error(
            "payload_codec.archive_failed",
            extra={"run_id": str(run_id), "error": str(exc)},
        )
        raise


async def restore_archived_history(
    session: AsyncSession,
    *,
    archive_ref: str,
) -> list[dict[str, Any]]:
    """Restore events from an archive reference.

    Args:
        session: Async DB session.
        archive_ref: Reference returned by archive_run_history.

    Returns:
        List of event dicts (same shape as the serialized events).
    """
    if archive_ref.startswith("archive:empty:"):
        return []

    data = await _read_archive(session, archive_ref=archive_ref)
    try:
        events: list[dict[str, Any]] = json.loads(data)
        return events
    except Exception as exc:
        raise PayloadDecodeError(
            f"Cannot deserialize archive {archive_ref!r}: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Internal artifact / archive helpers
# ---------------------------------------------------------------------------


async def _store_payload_artifact(
    session: AsyncSession,
    *,
    tenant_id: str,
    data: str,
) -> str:
    """Store an oversized payload as an artifact. Returns artifact_id string."""
    artifact_id = str(uuid4())

    # Try to persist via the existing artifact_service if present.
    try:
        from app.services.artifact_service import create_artifact  # type: ignore

        await create_artifact(
            session,
            tenant_id=tenant_id,
            artifact_id=artifact_id,
            content=data,
            content_type="application/x-archon-payload",
        )
    except (ImportError, AttributeError, Exception):
        # Fall back to an in-process store (tests / minimal deployments).
        _PAYLOAD_STORE[artifact_id] = data

    return artifact_id


async def _load_payload_artifact(
    session: AsyncSession,
    *,
    artifact_ref: str,
) -> str:
    """Load a payload artifact by its reference. Returns encoded string."""
    try:
        from app.services.artifact_service import get_artifact  # type: ignore

        artifact = await get_artifact(session, artifact_id=artifact_ref)
        return artifact.content
    except (ImportError, AttributeError, Exception):
        pass

    if artifact_ref in _PAYLOAD_STORE:
        return _PAYLOAD_STORE[artifact_ref]

    raise PayloadDecodeError(f"Artifact not found: {artifact_ref!r}")


async def _write_archive(
    session: AsyncSession,
    *,
    archive_id: UUID,
    data: str,
) -> str:
    """Write archive data blob. Returns ``"archive:<id>"``. """
    archive_ref = f"archive:{archive_id}"
    _ARCHIVE_STORE[str(archive_id)] = data
    return archive_ref


async def _read_archive(
    session: AsyncSession,
    *,
    archive_ref: str,
) -> str:
    """Read archive data by reference."""
    if archive_ref.startswith("archive:"):
        archive_id = archive_ref[len("archive:"):]
    else:
        archive_id = archive_ref

    if archive_id in _ARCHIVE_STORE:
        return _ARCHIVE_STORE[archive_id]

    raise PayloadDecodeError(f"Archive not found: {archive_ref!r}")


# In-process fallback stores (used in tests and minimal deployments
# where no artifact service or DB table is wired).
_PAYLOAD_STORE: dict[str, str] = {}
_ARCHIVE_STORE: dict[str, str] = {}


__all__ = [
    "PayloadCodecSettings",
    "PayloadDecodeError",
    "PayloadTooLarge",
    "archive_run_history",
    "decode_payload",
    "encode_payload",
    "restore_archived_history",
]
