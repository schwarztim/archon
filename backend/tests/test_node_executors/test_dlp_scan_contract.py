"""dlpScanNode contract tests — Phase 3 / WS9.

The DLP node delegates to ``DLPService.scan_content``.  Output envelope:
``{"risk_level": str, "finding_count": int, "action": str, "passed": bool}``.
On block-action high-severity findings → ``status="failed"``.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.node_executors import NODE_EXECUTORS  # noqa: E402
from tests.test_node_executors import make_ctx  # noqa: E402


def _scan(risk_level, action, findings_count: int = 0) -> MagicMock:
    """Build a DLPScanResultSchema-shaped MagicMock."""
    from app.models.dlp import DLPScanResultSchema  # noqa: PLC0415

    m = MagicMock(spec=DLPScanResultSchema)
    m.risk_level = risk_level
    m.action = action
    m.findings = [MagicMock() for _ in range(findings_count)]
    return m


# ---------------------------------------------------------------------------
# 1. input schema
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dlp_input_schema_minimal_no_inputs():
    """Empty ctx.inputs → scans an empty string; returns completed."""
    from app.models.dlp import RiskLevel, ScanAction  # noqa: PLC0415

    ctx = make_ctx("dlpScanNode", config={})
    with patch(
        "app.services.dlp_service.DLPService.scan_content",
        return_value=_scan(RiskLevel.LOW, ScanAction.ALLOW),
    ):
        r = await NODE_EXECUTORS["dlpScanNode"].execute(ctx)
    assert r.status == "completed"


@pytest.mark.asyncio
async def test_dlp_input_schema_camel_and_snake():
    from app.models.dlp import RiskLevel, ScanAction  # noqa: PLC0415

    ctx_c = make_ctx(
        "dlpScanNode",
        config={"actionOnViolation": "block"},
        inputs={"x": "hi"},
    )
    ctx_s = make_ctx(
        "dlpScanNode",
        config={"action_on_violation": "block"},
        inputs={"x": "hi"},
    )
    with patch(
        "app.services.dlp_service.DLPService.scan_content",
        return_value=_scan(RiskLevel.LOW, ScanAction.ALLOW),
    ):
        rc = await NODE_EXECUTORS["dlpScanNode"].execute(ctx_c)
        rs = await NODE_EXECUTORS["dlpScanNode"].execute(ctx_s)
    assert rc.status == "completed" and rs.status == "completed"


# ---------------------------------------------------------------------------
# 2. output schema
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dlp_output_envelope_shape():
    from app.models.dlp import RiskLevel, ScanAction  # noqa: PLC0415

    ctx = make_ctx("dlpScanNode", config={}, inputs={"x": "hello"})
    with patch(
        "app.services.dlp_service.DLPService.scan_content",
        return_value=_scan(RiskLevel.LOW, ScanAction.ALLOW),
    ):
        r = await NODE_EXECUTORS["dlpScanNode"].execute(ctx)

    assert r.status == "completed"
    for key in ("risk_level", "finding_count", "action", "passed"):
        assert key in r.output


# ---------------------------------------------------------------------------
# 3. success path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dlp_low_risk_passes():
    from app.models.dlp import RiskLevel, ScanAction  # noqa: PLC0415

    ctx = make_ctx("dlpScanNode", config={}, inputs={"x": "Hello world"})
    with patch(
        "app.services.dlp_service.DLPService.scan_content",
        return_value=_scan(RiskLevel.LOW, ScanAction.ALLOW),
    ):
        r = await NODE_EXECUTORS["dlpScanNode"].execute(ctx)
    assert r.status == "completed"
    assert r.output["passed"] is True


@pytest.mark.asyncio
async def test_dlp_high_severity_with_flag_action_passes():
    """High-severity + actionOnViolation=flag still completes (records but doesn't block)."""
    from app.models.dlp import RiskLevel, ScanAction  # noqa: PLC0415

    ctx = make_ctx(
        "dlpScanNode",
        config={"actionOnViolation": "flag"},
        inputs={"x": "secret-here"},
    )
    with patch(
        "app.services.dlp_service.DLPService.scan_content",
        return_value=_scan(RiskLevel.HIGH, ScanAction.ALLOW, findings_count=2),
    ):
        r = await NODE_EXECUTORS["dlpScanNode"].execute(ctx)
    assert r.status == "completed"


# ---------------------------------------------------------------------------
# 4. failure path — block action + high severity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dlp_high_severity_with_block_action_fails():
    from app.models.dlp import RiskLevel, ScanAction  # noqa: PLC0415

    ctx = make_ctx(
        "dlpScanNode",
        config={"actionOnViolation": "block"},
        inputs={"x": "AKIA0000000000000000"},
    )
    with patch(
        "app.services.dlp_service.DLPService.scan_content",
        return_value=_scan(RiskLevel.CRITICAL, ScanAction.BLOCK, findings_count=1),
    ):
        r = await NODE_EXECUTORS["dlpScanNode"].execute(ctx)
    assert r.status == "failed"
    assert "DLP violation" in (r.error or "")


@pytest.mark.asyncio
async def test_dlp_service_raises_returns_failed():
    """Exception in DLPService is caught; status=failed with the exc class in error."""
    ctx = make_ctx("dlpScanNode", config={}, inputs={"x": "hi"})
    with patch(
        "app.services.dlp_service.DLPService.scan_content",
        side_effect=RuntimeError("provider down"),
    ):
        r = await NODE_EXECUTORS["dlpScanNode"].execute(ctx)
    assert r.status == "failed"
    assert "RuntimeError" in (r.error or "")


# ---------------------------------------------------------------------------
# 5. cancellation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dlp_cancellation_not_applicable():
    pytest.skip("cancellation N/A — DLP scan is atomic")


# ---------------------------------------------------------------------------
# 6. retry classification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dlp_retry_classification_on_transient():
    """Provider-down is presented as a generic failure; the dispatcher classifies."""
    ctx = make_ctx("dlpScanNode", config={}, inputs={"x": "hi"})
    with patch(
        "app.services.dlp_service.DLPService.scan_content",
        side_effect=TimeoutError("503 service unavailable"),
    ):
        r = await NODE_EXECUTORS["dlpScanNode"].execute(ctx)
    assert r.status == "failed"
    assert "TimeoutError" in (r.error or "")


# ---------------------------------------------------------------------------
# 7. tenant isolation — tenant_id forwarded to scan_content
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dlp_tenant_id_forwarded_to_service():
    from app.models.dlp import RiskLevel, ScanAction  # noqa: PLC0415

    captured: dict = {}

    def _capture(*, tenant_id, content):
        captured["tenant_id"] = tenant_id
        captured["content"] = content
        return _scan(RiskLevel.LOW, ScanAction.ALLOW)

    ctx = make_ctx(
        "dlpScanNode",
        config={},
        inputs={"x": "hi"},
        tenant_id="tenant-zeta",
    )
    with patch(
        "app.services.dlp_service.DLPService.scan_content",
        side_effect=_capture,
    ):
        await NODE_EXECUTORS["dlpScanNode"].execute(ctx)

    assert captured["tenant_id"] == "tenant-zeta"


# ---------------------------------------------------------------------------
# 8. event emission
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dlp_event_emission_not_applicable():
    pytest.skip(
        "event emission N/A — DLP returns NodeResult; cost-gate semantics live downstream"
    )
