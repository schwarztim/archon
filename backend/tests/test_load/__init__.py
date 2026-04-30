"""Phase 6 — Scale Squad load test suite.

Five load profiles validate the unified run dispatcher under parallel
execution pressure with stubbed LLMs:

    1. test_load_many_simple_workflows  — N parallel one-step runs
    2. test_load_fanout_fanin           — N runs, each with parallel fanout/merge
    3. test_load_llm_stubs              — N runs, each with multiple LLM nodes
    4. test_load_approval_pause         — N runs that pause and bulk-resume
    5. test_load_retries_failures       — N flaky runs exercising RetryPolicy

Each profile dispatches via ``asyncio.gather`` and asserts:
    * total_completed_runs == N within budget
    * every run has the canonical event chain
    * no double-execution (workflow_run_steps row count matches expected)

Configurable via ``LOAD_TEST_N`` env var. Default 50 (local), CI=10.
"""
