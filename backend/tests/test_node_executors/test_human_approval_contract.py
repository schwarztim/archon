"""humanApprovalNode contract tests — Phase 3 / WS9.

The approval node pauses the run.  In test contexts (no DB session or no
discoverable run_id) the executor returns a synthetic approval id with the
same envelope shape so the resume contract can be exercised.

Output envelope (paused):
``{"approval_id": str, "prompt": str, "_hint": {kind: "approval_required",
   approval_id, step_id, expires_at}}``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.node_executors import NODE_EXECUTORS  # noqa: E402
from tests.test_node_executors import make_ctx  # noqa: E402


# ---------------------------------------------------------------------------
# 1. input schema
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_human_approval_default_prompt():
    """prompt is optional — falls back to a default string."""
    ctx = make_ctx("humanApprovalNode", config={})
    r = await NODE_EXECUTORS["humanApprovalNode"].execute(ctx)
    assert r.status == "paused"
    assert r.output["prompt"]


@pytest.mark.asyncio
async def test_human_approval_camel_and_snake_timeout():
    ctx_c = make_ctx("humanApprovalNode", config={"timeoutHours": 4})
    ctx_s = make_ctx("humanApprovalNode", config={"timeout_hours": 4})
    rc = await NODE_EXECUTORS["humanApprovalNode"].execute(ctx_c)
    rs = await NODE_EXECUTORS["humanApprovalNode"].execute(ctx_s)
    assert rc.status == "paused" and rs.status == "paused"


# ---------------------------------------------------------------------------
# 2. output schema — paused with structured _hint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_human_approval_output_envelope_shape():
    ctx = make_ctx("humanApprovalNode", config={"prompt": "Approve?"})
    r = await NODE_EXECUTORS["humanApprovalNode"].execute(ctx)

    assert r.status == "paused"
    assert r.paused_reason == "awaiting_human_approval"
    assert "approval_id" in r.output
    assert "prompt" in r.output
    assert "_hint" in r.output
    hint = r.output["_hint"]
    assert hint["kind"] == "approval_required"
    assert hint["step_id"] == ctx.step_id
    assert hint["approval_id"] == r.output["approval_id"]


# ---------------------------------------------------------------------------
# 3. success / pause path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_human_approval_synthetic_path_when_no_db():
    """No db_session → synthetic approval id with deterministic prefix."""
    ctx = make_ctx("humanApprovalNode", config={"prompt": "Approve?"}, db_session=None)
    r = await NODE_EXECUTORS["humanApprovalNode"].execute(ctx)
    assert r.status == "paused"
    assert r.output["approval_id"].startswith("approval-")


@pytest.mark.asyncio
async def test_human_approval_real_db_path_calls_service():
    """With a session AND a run_id, defers to approval_service.request_approval."""
    from datetime import datetime, timezone  # noqa: PLC0415

    run_uuid = uuid4()
    session = MagicMock()
    session.flush = AsyncMock(return_value=None)

    fake_approval = MagicMock()
    fake_approval.id = uuid4()
    fake_approval.expires_at = datetime.now(timezone.utc)

    ctx = make_ctx(
        "humanApprovalNode",
        config={"prompt": "Approve?"},
        db_session=session,
        node_data_extra={"run_id": str(run_uuid)},
        tenant_id=str(uuid4()),
    )

    with patch(
        "app.services.approval_service.request_approval",
        new=AsyncMock(return_value=fake_approval),
    ) as mock_req:
        r = await NODE_EXECUTORS["humanApprovalNode"].execute(ctx)

    mock_req.assert_awaited_once()
    assert r.status == "paused"
    assert r.output["approval_id"] == str(fake_approval.id)


# ---------------------------------------------------------------------------
# 4. failure path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_human_approval_invalid_timeout_hours_raises():
    """int(...) coercion of a non-numeric timeout raises before run."""
    ctx = make_ctx("humanApprovalNode", config={"timeoutHours": "not-a-number"})
    with pytest.raises((ValueError, TypeError)):
        await NODE_EXECUTORS["humanApprovalNode"].execute(ctx)


# ---------------------------------------------------------------------------
# 5. cancellation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_human_approval_cancellation_not_applicable():
    pytest.skip(
        "cancellation N/A — pause→resume is the cancel surface; mid-call cancel meaningless"
    )


# ---------------------------------------------------------------------------
# 6. retry classification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_human_approval_retry_not_applicable():
    pytest.skip("retry N/A — pause is the success state; nothing to retry")


# ---------------------------------------------------------------------------
# 7. tenant isolation — tenant flows into approval_service.request_approval
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_human_approval_tenant_id_forwarded_to_service():
    from uuid import UUID  # noqa: PLC0415

    tenant_id = uuid4()
    run_uuid = uuid4()
    session = MagicMock()
    session.flush = AsyncMock(return_value=None)

    fake_approval = MagicMock()
    fake_approval.id = uuid4()
    fake_approval.expires_at = None

    ctx = make_ctx(
        "humanApprovalNode",
        config={"prompt": "Approve?"},
        db_session=session,
        tenant_id=str(tenant_id),
        node_data_extra={"run_id": str(run_uuid)},
    )

    captured: dict = {}

    async def _capture(session, **kw):
        captured.update(kw)
        return fake_approval

    with patch(
        "app.services.approval_service.request_approval",
        new=_capture,
    ):
        await NODE_EXECUTORS["humanApprovalNode"].execute(ctx)

    assert captured.get("tenant_id") == tenant_id
    assert isinstance(captured.get("tenant_id"), UUID)


# ---------------------------------------------------------------------------
# 8. event emission — request_approval is responsible for run.paused event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_human_approval_event_emission_via_service():
    """approval_service.request_approval is the single integration point that
    inserts the approval row, flips run state, and appends the run.paused
    event.  The executor's contract is to call it.
    """
    run_uuid = uuid4()
    session = MagicMock()
    session.flush = AsyncMock(return_value=None)

    fake_approval = MagicMock()
    fake_approval.id = uuid4()
    fake_approval.expires_at = None

    ctx = make_ctx(
        "humanApprovalNode",
        config={"prompt": "Approve?"},
        db_session=session,
        node_data_extra={"run_id": str(run_uuid)},
        tenant_id=str(uuid4()),
    )

    with patch(
        "app.services.approval_service.request_approval",
        new=AsyncMock(return_value=fake_approval),
    ) as mock_req:
        await NODE_EXECUTORS["humanApprovalNode"].execute(ctx)

    # event emission is structural — calling the service is the proxy assertion
    assert mock_req.await_count == 1
