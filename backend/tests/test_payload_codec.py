"""Payload codec tests — W16.

All tests use inline SQLite, no conftest.py.

Tests verify:
  - encode → decode roundtrip
  - large payload stored as artifact reference
  - DLP redaction strips sensitive fields
  - budget fail-closed in enterprise mode
  - DLP blocks sensitive payload in enterprise mode
  - egress default deny in enterprise mode
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel

from app.models import AuditLog

# ---------------------------------------------------------------------------
# Inline SQLite setup
# ---------------------------------------------------------------------------

_ENGINE = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
_AsyncSession = sessionmaker(_ENGINE, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture(autouse=True)
async def create_tables():
    async with _ENGINE.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield
    async with _ENGINE.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)


@pytest_asyncio.fixture
async def session():
    async with _AsyncSession() as s:
        yield s


# ---------------------------------------------------------------------------
# Payload codec tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_payload_encode_decode_roundtrip(session: AsyncSession):
    """encode_payload followed by decode_payload returns the original dict."""
    from app.services.payload_codec import PayloadCodecSettings, decode_payload, encode_payload

    payload = {"message": "hello", "count": 42, "nested": {"key": "value"}}
    tenant_id = uuid4()
    settings = PayloadCodecSettings(enable_encryption=False)  # no Fernet key in tests

    encoded = await encode_payload(session, payload=payload, tenant_id=tenant_id, settings=settings)
    assert encoded.startswith("b64:")

    decoded = await decode_payload(session, encoded=encoded, tenant_id=tenant_id, settings=settings)
    assert decoded == payload


@pytest.mark.asyncio
async def test_encode_decode_roundtrip_with_complex_types(session: AsyncSession):
    """Codec handles nested dicts, lists, and numeric types correctly."""
    from app.services.payload_codec import PayloadCodecSettings, decode_payload, encode_payload

    payload: dict[str, Any] = {
        "string_val": "test",
        "int_val": 99,
        "float_val": 3.14,
        "list_val": [1, 2, 3],
        "nested": {"deep": {"deeper": "value"}},
        "null_val": None,
    }
    settings = PayloadCodecSettings(enable_encryption=False, enable_dlp=False)
    tid = uuid4()

    encoded = await encode_payload(session, payload=payload, tenant_id=tid, settings=settings)
    decoded = await decode_payload(session, encoded=encoded, tenant_id=tid, settings=settings)
    assert decoded == payload


@pytest.mark.asyncio
async def test_large_payload_stored_as_artifact(session: AsyncSession):
    """A payload exceeding max_payload_size is returned as an artifact reference."""
    from app.services.payload_codec import PayloadCodecSettings, decode_payload, encode_payload

    # Create a payload large enough to exceed a 100-byte limit.
    payload = {"data": "x" * 500}
    settings = PayloadCodecSettings(
        max_payload_size=100,
        enable_encryption=False,
        enable_dlp=False,
        enable_compression=False,
    )
    tid = uuid4()

    encoded = await encode_payload(session, payload=payload, tenant_id=tid, settings=settings)
    assert encoded.startswith("artifact:")

    # Restore the artifact.
    decoded = await decode_payload(session, encoded=encoded, tenant_id=tid, settings=settings)
    assert decoded == payload


@pytest.mark.asyncio
async def test_redaction_strips_sensitive_fields(session: AsyncSession):
    """DLP redaction removes PII patterns from encoded payloads."""
    from app.services.payload_codec import PayloadCodecSettings, decode_payload, encode_payload

    # Include an SSN pattern in the payload.
    payload = {"user": "Alice", "ssn": "123-45-6789", "note": "test"}
    settings = PayloadCodecSettings(
        enable_encryption=False,
        enable_dlp=True,
        enable_compression=False,
    )
    tid = uuid4()

    encoded = await encode_payload(session, payload=payload, tenant_id=tid, settings=settings)
    # Decode without DLP (compression off, no encryption).
    decoded = await decode_payload(session, encoded=encoded, tenant_id=tid, settings=settings)

    # The decoded value should not contain the raw SSN pattern.
    import json
    decoded_str = json.dumps(decoded)
    assert "123-45-6789" not in decoded_str, (
        "SSN should have been redacted during encoding"
    )


@pytest.mark.asyncio
async def test_payload_decode_error_on_corrupt_data(session: AsyncSession):
    """PayloadDecodeError is raised when the encoded data is corrupt."""
    from app.services.payload_codec import PayloadDecodeError, PayloadCodecSettings, decode_payload

    settings = PayloadCodecSettings(enable_encryption=False)
    with pytest.raises(PayloadDecodeError):
        await decode_payload(
            session,
            encoded="b64:!!! not valid base64 !!!",
            tenant_id=uuid4(),
            settings=settings,
        )


@pytest.mark.asyncio
async def test_payload_decode_error_on_unknown_prefix(session: AsyncSession):
    """PayloadDecodeError is raised for unrecognised encoding prefix."""
    from app.services.payload_codec import PayloadDecodeError, PayloadCodecSettings, decode_payload

    settings = PayloadCodecSettings(enable_encryption=False)
    with pytest.raises(PayloadDecodeError):
        await decode_payload(
            session,
            encoded="unknown:somedata",
            tenant_id=uuid4(),
            settings=settings,
        )


# ---------------------------------------------------------------------------
# Enterprise gate tests (budget, DLP, egress)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_budget_fail_closed_in_enterprise(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    """In enterprise mode, budget service unavailability raises BudgetGateUnavailable."""
    monkeypatch.setenv("ARCHON_ENTERPRISE_MODE", "true")

    from app.services.budget_service import BudgetLookupFailed
    from app.services.enterprise_gates import BudgetGateUnavailable, check_budget

    # Make budget_service.check_budget raise a BudgetLookupFailed (service failure).
    with patch(
        "app.services.budget_service.check_budget",
        new=AsyncMock(side_effect=BudgetLookupFailed("DB connection failed")),
    ):
        with pytest.raises(BudgetGateUnavailable):
            await check_budget(session, tenant_id=uuid4(), estimated_cost=0.01)


@pytest.mark.asyncio
async def test_budget_fail_open_in_dev(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    """In dev mode, an unexpected error in budget service → allow (fail-open)."""
    monkeypatch.delenv("ARCHON_ENTERPRISE_MODE", raising=False)

    from app.services.enterprise_gates import check_budget

    with patch(
        "app.services.budget_service.check_budget",
        new=AsyncMock(side_effect=RuntimeError("unexpected DB error")),
    ):
        result = await check_budget(session, tenant_id=uuid4(), estimated_cost=0.01)
    assert result is True


@pytest.mark.asyncio
async def test_dlp_blocks_sensitive_payload_in_enterprise(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    """In enterprise mode, a payload with CRITICAL DLP risk raises DLPGateDenied."""
    monkeypatch.setenv("ARCHON_ENTERPRISE_MODE", "true")

    from app.services.enterprise_gates import DLPGateDenied, check_dlp

    # Payload containing an AWS access key (CRITICAL risk level).
    # Pattern: \b(AKIA|ABIA|ACCA|ASIA)[0-9A-Z]{16}\b — exactly 16 uppercase chars after prefix.
    payload = {"key": "AKIAIOSFODNN7EXAMPLE", "data": "test"}

    with pytest.raises(DLPGateDenied):
        await check_dlp(session, tenant_id=uuid4(), payload=payload)


@pytest.mark.asyncio
async def test_dlp_redacts_in_dev_mode(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    """In dev mode, DLP findings cause redaction but do not raise."""
    monkeypatch.delenv("ARCHON_ENTERPRISE_MODE", raising=False)

    from app.services.enterprise_gates import check_dlp

    payload = {"email": "user@example.com", "note": "hello"}
    allowed, redacted = await check_dlp(session, tenant_id=uuid4(), payload=payload)
    assert allowed is True
    # Redacted payload should not contain the raw email.
    import json
    redacted_str = json.dumps(redacted)
    assert "user@example.com" not in redacted_str


@pytest.mark.asyncio
async def test_egress_default_deny_in_enterprise(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    """In enterprise mode with no allowlist, egress is denied by default."""
    monkeypatch.setenv("ARCHON_ENTERPRISE_MODE", "true")

    from app.services.enterprise_gates import EgressGateDenied, check_egress

    with pytest.raises(EgressGateDenied):
        await check_egress(
            session,
            tenant_id=uuid4(),
            target_url="https://external-api.example.com/webhook",
        )


@pytest.mark.asyncio
async def test_egress_allow_in_dev_mode_no_allowlist(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    """In dev mode with no allowlist, egress returns False (warning) but does not raise."""
    monkeypatch.delenv("ARCHON_ENTERPRISE_MODE", raising=False)

    from app.services.enterprise_gates import check_egress

    result = await check_egress(
        session,
        tenant_id=uuid4(),
        target_url="https://external-api.example.com/webhook",
    )
    # Dev mode with no allowlist → True (warning logged, no raise).
    assert result is True


@pytest.mark.asyncio
async def test_check_secret_access_no_grant_table_allows(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    """When no TenantSecretGrant table exists, secret access defaults to allow."""
    monkeypatch.setenv("ARCHON_ENTERPRISE_MODE", "true")

    from app.services.enterprise_gates import check_secret_access

    # No grant table model exists → falls through to True.
    result = await check_secret_access(
        session,
        tenant_id=uuid4(),
        secret_ref="vault://prod/api-key",
    )
    assert result is True


# ---------------------------------------------------------------------------
# Archive / restore tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_archive_and_restore_run_history(session: AsyncSession):
    """archive_run_history archives no events when none are old enough;
    restore_archived_history returns an empty list for 'archive:empty:' refs."""
    from app.services.payload_codec import archive_run_history, restore_archived_history

    run_id = uuid4()
    # No events in DB → returns "archive:empty:<run_id>".
    ref = await archive_run_history(session, run_id=run_id, retention_days=30)
    assert ref.startswith("archive:empty:")

    # Restore empty archive → empty list.
    events = await restore_archived_history(session, archive_ref=ref)
    assert events == []
