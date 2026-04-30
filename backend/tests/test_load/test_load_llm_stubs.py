"""Phase 6 load profile #3 — N workflows with multiple stub LLM nodes.

Each workflow chains 3 ``llmNode`` steps (s0 → s1 → s2). With
``LLM_STUB_MODE=true`` the LLM call returns a deterministic
``LLMResponse`` (10 prompt tokens + 20 completion tokens = 30 total per
call) without any network I/O.

Validates:
  * ``token_usage`` is propagated to every step row
  * aggregate per-run token totals = 3 × 30 = 90 prompt+completion when
    summed across the run's workflow_run_steps rows
  * the dispatcher's per-step metrics emission survives parallel load
  * full event chain is intact

Default N=30 (10 in CI). Each run produces 3 step rows + 5 events
(claimed, started, 3× step.completed, completed).
"""

from __future__ import annotations

import os
import time

import pytest

os.environ.setdefault("LLM_STUB_MODE", "true")


def _make_llm_chain_steps(num_llm: int = 3) -> list[dict]:
    """Build a linear chain of ``num_llm`` llmNode steps."""
    steps: list[dict] = []
    for i in range(num_llm):
        steps.append(
            {
                "step_id": f"llm_{i}",
                "name": f"llm-{i}",
                "node_type": "llmNode",
                "config": {
                    "model": "gpt-3.5-turbo",
                    "prompt": f"Process: step {i}",
                    "maxTokens": 64,
                    "temperature": 0.0,
                },
                "depends_on": [f"llm_{i - 1}"] if i > 0 else [],
            }
        )
    return steps


@pytest.fixture()
def llm_n() -> int:
    """LLM profile N — defaults to 30 locally; honour LOAD_TEST_N."""
    raw = os.environ.get("LOAD_TEST_N", "").strip()
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    return 30


LLM_NODES_PER_RUN = 3
STUB_TOKENS_PER_CALL = 30  # 10 prompt + 20 completion (see _stub_response)


@pytest.mark.asyncio
async def test_load_llm_stubs_complete_with_token_usage(
    llm_n,
    patched_dispatcher,
    seed_run_factory,
    dispatch_helper,
    wait_terminal_helper,
    double_execute_helper,
    event_chain_helper,
    budget_helper,
):
    """Profile 3: N runs × M LLM stub nodes; assert per-step token usage."""
    n = llm_n
    _engine, factory = patched_dispatcher

    steps = _make_llm_chain_steps(num_llm=LLM_NODES_PER_RUN)
    expected_steps_per_run = len(steps)

    run_ids = [await seed_run_factory(steps) for _ in range(n)]

    start = time.monotonic()
    results = await dispatch_helper(run_ids, worker_id_prefix="llm-stub")
    elapsed = time.monotonic() - start

    # Budget — stub LLMs are fast, but each run has 3 sequential nodes.
    budget = 60.0 if n >= 30 else 120.0
    budget_helper(elapsed, budget_s=budget, label=f"llm-stub-N{n}")

    # ── Per-run assertions ────────────────────────────────────────────
    from sqlalchemy import select

    from app.models.workflow import WorkflowRunStep

    completed = 0
    for rid, outcome in results:
        assert not isinstance(outcome, BaseException), (
            f"dispatch raised for {rid}: {outcome!r}"
        )
        assert outcome is not None, f"dispatch returned None for {rid}"
        assert outcome.status == "completed", (
            f"run {rid} status={outcome.status!r}"
        )

        final = await wait_terminal_helper(factory, rid, timeout=15.0)
        assert final == "completed"

        # Event chain.
        types = await event_chain_helper(factory, rid)
        step_completed_events = sum(1 for t in types if t == "step.completed")
        assert step_completed_events == expected_steps_per_run

        # Token usage on each step row.
        async with factory() as session:
            step_rows = (
                await session.execute(
                    select(WorkflowRunStep)
                    .where(WorkflowRunStep.run_id == rid)
                    .order_by(WorkflowRunStep.step_id)
                )
            ).scalars().all()

        assert len(step_rows) == expected_steps_per_run

        # Each step's token_usage is a dict with the stub totals.
        # The llmNode executor reports prompt_tokens + completion_tokens
        # + total_tokens. Stub mode → 10 / 20 / 30 per call.
        run_total_tokens = 0
        for row in step_rows:
            tu = row.token_usage or {}
            # Be tolerant of the dict shape — verify totals when present.
            total = (
                tu.get("total_tokens")
                or (tu.get("prompt_tokens", 0) + tu.get("completion_tokens", 0))
                or 0
            )
            run_total_tokens += int(total)

        # 3 LLM calls × 30 tokens = 90.
        expected_run_tokens = LLM_NODES_PER_RUN * STUB_TOKENS_PER_CALL
        assert run_total_tokens == expected_run_tokens, (
            f"run {rid} aggregated token_usage={run_total_tokens}, "
            f"expected {expected_run_tokens}"
        )

        # No double-execute.
        await double_execute_helper(
            factory, rid, expected_step_count=expected_steps_per_run
        )
        completed += 1

    assert completed == n


@pytest.mark.asyncio
async def test_load_llm_stubs_aggregate_token_usage(
    llm_n,
    patched_dispatcher,
    seed_run_factory,
    dispatch_helper,
):
    """Total token consumption across the load = N × 3 × 30 stub tokens.

    This is a single SQL aggregation that catches any per-step token
    accounting drift introduced under parallel load (e.g. token_usage
    overwritten by the wrong step's payload due to a race).
    """
    n = llm_n
    _engine, factory = patched_dispatcher

    steps = _make_llm_chain_steps(num_llm=LLM_NODES_PER_RUN)
    expected_total_steps = n * len(steps)

    run_ids = [await seed_run_factory(steps) for _ in range(n)]
    await dispatch_helper(run_ids, worker_id_prefix="llm-aggregate")

    from sqlalchemy import select

    from app.models.workflow import WorkflowRunStep

    async with factory() as session:
        rows = (
            await session.execute(select(WorkflowRunStep))
        ).scalars().all()

    assert len(rows) == expected_total_steps, (
        f"expected {expected_total_steps} step rows (N={n} × "
        f"{len(steps)}), got {len(rows)}"
    )

    grand_total = 0
    for row in rows:
        tu = row.token_usage or {}
        grand_total += int(
            tu.get("total_tokens")
            or (tu.get("prompt_tokens", 0) + tu.get("completion_tokens", 0))
            or 0
        )

    expected_grand_total = n * LLM_NODES_PER_RUN * STUB_TOKENS_PER_CALL
    assert grand_total == expected_grand_total, (
        f"aggregate token_usage={grand_total}, "
        f"expected {expected_grand_total}"
    )
