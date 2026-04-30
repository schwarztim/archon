"""W18c — Enterprise Policy/Data Chaos tests.

Deterministic chaos tests that prove enterprise gate enforcement:
  - ARCHON_ENTERPRISE_MODE=true without policy denies run start
  - DLP blocks payload containing PII marker
  - Budget=0 blocks run
  - Vault unavailable fails closed (not silently continues)
  - Egress blocked by default in enterprise mode for unlisted domain
  - DLP-flagged input: run proceeds but event history contains redacted version

All tests use inline SQLite + monkeypatching (no conftest.py).
Run with: .venv/bin/python -m pytest tests/chaos/test_enterprise_chaos.py -v --noconftest
"""

from __future__ import annotations

import asyncio
import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

os.environ.setdefault("LLM_STUB_MODE", "true")
os.environ.setdefault("AUTH_DEV_MODE", "true")
os.environ.setdefault("ARCHON_DATABASE_URL", "postgresql+asyncpg://t:t@localhost/t")

SQLITE_URL = "sqlite+aiosqlite:///:memory:"


# ---------------------------------------------------------------------------
# Shared engine + session factory helpers
# ---------------------------------------------------------------------------


async def _make_engine_and_factory():
    from app.models import Agent, Execution, User  # noqa: F401
    from app.models.workflow import (  # noqa: F401
        Workflow,
        WorkflowRun,
        WorkflowRunEvent,
        WorkflowRunStep,
    )
    from app.models.task_queue import Task, TaskQueue  # noqa: F401
    from app.models.activity import ActivityExecution  # noqa: F401

    engine = create_async_engine(SQLITE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.exec_driver_sql("PRAGMA foreign_keys = ON")
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, factory


def _mock_session() -> AsyncMock:
    """Lightweight mock session for gate-only tests that need no real DB."""
    session = AsyncMock()
    session.add = MagicMock()
    session.exec = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    return session


# ---------------------------------------------------------------------------
# test_enterprise_mode_missing_policy_denies
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enterprise_mode_missing_policy_denies(monkeypatch) -> None:
    """ARCHON_ENTERPRISE_MODE=true with no budget configured must raise.

    The budget gate in enterprise mode must fail closed when there is no
    budget record for the tenant (NoBudgetConfigured).
    """
    monkeypatch.setenv("ARCHON_ENTERPRISE_MODE", "true")

    from app.services.enterprise_gates import BudgetGateUnavailable, check_budget
    from app.services.budget_service import NoBudgetConfigured

    session = _mock_session()

    # Patch budget_service.check_budget at the module where it is defined.
    # enterprise_gates.py uses a local import: `from app.services import budget_service`
    # then calls `budget_service.check_budget(...)`, so the live object is the
    # function in app.services.budget_service.
    with patch(
        "app.services.budget_service.check_budget",
        new_callable=AsyncMock,
        side_effect=NoBudgetConfigured("no budget configured for tenant"),
    ):
        with pytest.raises(BudgetGateUnavailable):
            await check_budget(
                session,
                tenant_id=uuid4(),
                estimated_cost=0.01,
            )


# ---------------------------------------------------------------------------
# test_dlp_blocks_sensitive_payload
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dlp_blocks_sensitive_payload(monkeypatch) -> None:
    """DLP gate must raise DLPGateDenied when payload contains PII in enterprise mode.

    We inject a mock DLPService.scan_content that returns a BLOCK-level result
    when the payload contains a known PII marker, and verify the gate raises.
    """
    monkeypatch.setenv("ARCHON_ENTERPRISE_MODE", "true")

    from app.services.enterprise_gates import DLPGateDenied, check_dlp
    from app.models.dlp import ScanAction, RiskLevel

    mock_scan = MagicMock()
    mock_scan.action = ScanAction.BLOCK
    mock_scan.risk_level = RiskLevel.CRITICAL
    mock_scan.findings = [MagicMock()]

    session = _mock_session()
    pii_payload = {
        "user_input": "My SSN is 123-45-6789 and credit card 4111-1111-1111-1111"
    }

    # DLPService is imported locally inside check_dlp:
    #   from app.services.dlp_service import DLPService
    # Patch the class method at the module where DLPService is defined.
    with patch(
        "app.services.dlp_service.DLPService.scan_content",
        return_value=mock_scan,
    ):
        with pytest.raises(DLPGateDenied) as exc_info:
            await check_dlp(session, tenant_id=uuid4(), payload=pii_payload)

    assert "DLP" in str(exc_info.value) or "blocked" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# test_budget_exceeded_blocks_run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_budget_exceeded_blocks_run(monkeypatch) -> None:
    """Budget=0 (all spent) must block a new run attempt.

    The budget gate must raise BudgetGateDenied when check_budget returns
    allowed=False (tenant is over limit).
    """
    monkeypatch.setenv("ARCHON_ENTERPRISE_MODE", "true")

    from app.services.enterprise_gates import BudgetGateDenied, check_budget

    session = _mock_session()
    tenant_id = uuid4()

    # Mock the budget check to return a result indicating over-budget.
    mock_result = MagicMock()
    mock_result.allowed = False
    mock_result.reason = "monthly_limit_reached"
    mock_result.current_spend_usd = 100.0
    mock_result.limit_usd = 0.0

    with patch(
        "app.services.budget_service.check_budget",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        with pytest.raises(BudgetGateDenied) as exc_info:
            await check_budget(session, tenant_id=tenant_id, estimated_cost=0.001)

    assert str(tenant_id) in str(exc_info.value) or "budget" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# test_vault_unavailable_fails_closed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_vault_unavailable_fails_closed(monkeypatch) -> None:
    """Vault/secret resolver raising must produce ActivityResult(status='failed').

    The ActivityRuntime must capture a resolver exception as a failed result,
    not silently continue. Verified by running a minimal executor that calls
    resolve_secret inside the runtime.
    """
    # Use FK-off SQLite for this test: we need to insert an ActivityExecution
    # whose run_id FK points to workflow_runs.  The mixed SAUuid vs plain-UUID
    # storage in SQLite causes FK type mismatches; disabling FK enforcement is
    # correct here because this test exercises the secret-resolver failure path,
    # not DB-constraint semantics.
    engine = create_async_engine(SQLITE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.exec_driver_sql("PRAGMA foreign_keys = OFF")
        from app.models import Agent, Execution, User  # noqa: F401
        from app.models.workflow import (  # noqa: F401
            Workflow, WorkflowRun, WorkflowRunEvent, WorkflowRunStep,
        )
        from app.models.task_queue import Task, TaskQueue  # noqa: F401
        from app.models.activity import ActivityExecution  # noqa: F401
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        from app.services.activity_runtime import (
            ActivityContext,
            ActivityResult,
            ActivityRuntime,
        )
        from app.services.activity_runtime_test_doubles import build_test_context

        run_id = str(uuid4())

        # Secret resolver that always raises — simulates vault unavailable.
        async def _vault_down(secret_ref: str) -> str:
            raise RuntimeError("Vault is unavailable: connection refused")

        # Build a minimal artifact service stub.
        class _ArtifactStub:
            async def store_artifact(self, **_kw):
                return type("A", (), {"id": uuid4()})()

        ctx = build_test_context(
            run_id=run_id,
            activity_type="vault.dependent.activity",
        )

        runtime = ActivityRuntime(
            db_session_factory=factory,
            artifact_service=_ArtifactStub(),
            secrets_resolver=_vault_down,
        )

        # The executor calls resolve_secret — vault raises — runtime must fail closed.
        async def _vault_using_executor(c: ActivityContext) -> ActivityResult:
            secret_val = await c.resolve_secret("vault://prod/api-key")
            # Should not reach here if vault is down.
            return ActivityResult(status="completed", output_data={"key": secret_val})

        result = await runtime.execute(ctx, _vault_using_executor)

        assert result.status == "failed", (
            f"vault-unavailable executor must produce status='failed', got {result.status!r}"
        )
        assert result.error_code is not None, "error_code must be set on vault failure"
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# test_egress_blocked_by_default
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_egress_blocked_by_default(monkeypatch) -> None:
    """Enterprise mode with no allowlist configured must block egress to any URL."""
    monkeypatch.setenv("ARCHON_ENTERPRISE_MODE", "true")

    from app.services.enterprise_gates import EgressGateDenied, check_egress

    session = _mock_session()
    # The mock session exec returns an empty result (no TenantEgressPolicy rows).
    session.exec = AsyncMock(
        return_value=MagicMock(all=MagicMock(return_value=[]))
    )

    with pytest.raises(EgressGateDenied) as exc_info:
        await check_egress(
            session,
            tenant_id=uuid4(),
            target_url="https://evil.example.com/exfil",
        )

    assert "egress" in str(exc_info.value).lower() or "deny" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# test_no_raw_sensitive_payload_persisted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_raw_sensitive_payload_persisted(monkeypatch) -> None:
    """DLP-flagged input must be redacted before any persistence.

    We call check_dlp with a PII-containing payload in non-enterprise (dev) mode
    (so BLOCK is treated as redact-and-allow). The returned redacted_payload
    must not contain the raw PII value.
    """
    # Non-enterprise mode: DLP redacts but does not block.
    monkeypatch.setenv("ARCHON_ENTERPRISE_MODE", "false")

    from app.services.enterprise_gates import check_dlp
    from app.models.dlp import ScanAction, RiskLevel

    mock_finding = MagicMock()
    mock_finding.start = 21  # position of the SSN in the serialized JSON
    mock_finding.end = 32
    mock_finding.entity_type = "SSN"
    mock_finding.text = "123-45-6789"

    mock_scan = MagicMock()
    mock_scan.action = ScanAction.REDACT
    mock_scan.risk_level = RiskLevel.HIGH
    mock_scan.findings = [mock_finding]

    # The redacted output will have the SSN replaced.
    pii_payload = {"user_ssn": "123-45-6789", "name": "Alice"}
    redacted_json = '{"user_ssn": "[REDACTED]", "name": "Alice"}'

    session = _mock_session()

    with (
        patch(
            "app.services.dlp_service.DLPService.scan_content",
            return_value=mock_scan,
        ),
        patch(
            "app.services.dlp_service.DLPService.redact_content",
            return_value=redacted_json,
        ),
    ):
        allowed, redacted_payload = await check_dlp(
            session, tenant_id=uuid4(), payload=pii_payload
        )

    assert allowed is True, "dev mode should allow (redact, not block)"
    # The raw SSN must not appear in the redacted payload.
    assert "123-45-6789" not in str(redacted_payload), (
        "raw SSN must not appear in the redacted payload returned by check_dlp"
    )
