"""Helpers for the vertical-slice integration test (Wave 0).

Provides reusable fixtures and helpers for driving the REST API end-to-end:
- TestClient setup (uses session-scoped client from conftest.py).
- Auth header construction (currently a no-op because AUTH_DEV_MODE=true
  produces a synthetic admin user — see backend/app/middleware/auth.py).
- Workflow / agent factories that POST against the real REST surface.
- Polling helper that waits for terminal status with a hard timeout.

This module deliberately contains NO assertions — those live in
test_vertical_slice.py.  All it does is reduce the volume of boilerplate
in the actual test, so the test reads top-to-bottom as a story:

    1. POST a workflow            (factory)
    2. POST an execution          (factory)
    3. Poll until terminal        (helper)
    4. GET the run, assert state  (test)
    5. Query DB for steps         (test)
"""

from __future__ import annotations

import time
from typing import Any
from uuid import UUID, uuid4

# ---------------------------------------------------------------------------
# Auth — AUTH_DEV_MODE returns a synthetic admin user when no token is sent,
# so callers do not need to inject a header.  We still expose this helper
# so the test reads naturally and so future auth modes can be slotted in
# without touching the test body.
# ---------------------------------------------------------------------------


def auth_headers() -> dict[str, str]:
    """Return headers required to authenticate against the test API.

    With ARCHON_AUTH_DEV_MODE=true the middleware returns a synthetic admin
    user when no Bearer token is present, so this is currently empty.
    """
    return {}


# ---------------------------------------------------------------------------
# Workflow / agent factories
# ---------------------------------------------------------------------------


def make_minimal_agent_payload(name: str | None = None) -> dict[str, Any]:
    """Build the smallest valid AgentCreate body the API accepts.

    The agent is referenced by every step in our minimal workflow, so even
    when the workflow's per-step `node_type` is what actually drives the
    executor, we need a real agent_id for `WorkflowStepCreate.agent_id`
    (see backend/app/routes/workflows.py:WorkflowStepCreate — agent_id is
    a required field on the schema).
    """
    return {
        "name": name or f"slice-agent-{uuid4().hex[:8]}",
        "description": "Vertical slice heartbeat agent (REST-driven).",
        "definition": {
            "system_prompt": "You are a deterministic stub assistant.",
            "model": "gpt-3.5-turbo",
            "disable_checkpointing": True,
        },
        "tags": ["vertical-slice", "heartbeat"],
    }


def make_minimal_workflow_payload(
    agent_id: str,
    name: str | None = None,
) -> dict[str, Any]:
    """Build a 2-step (input → llm → output) workflow for the heartbeat path.

    The workflow_engine dispatches by `type` / `node_type` field.  We rely
    on the registered NODE_EXECUTORS (`inputNode`, `llmNode`, `outputNode`)
    so the LLM stub mode produces a deterministic `[STUB]` marker without
    touching any real provider.
    """
    return {
        "name": name or f"slice-workflow-{uuid4().hex[:8]}",
        "description": "Vertical slice heartbeat: input → llm → output.",
        "steps": [
            {
                "name": "input",
                "agent_id": agent_id,
                "config": {
                    "type": "inputNode",
                    "node_type": "inputNode",
                    "initialInput": {"message": "Hello from vertical slice"},
                },
                "depends_on": [],
            },
            {
                "name": "llm",
                "agent_id": agent_id,
                "config": {
                    "type": "llmNode",
                    "node_type": "llmNode",
                    "model": "gpt-3.5-turbo",
                    "prompt": "Respond to: {input}",
                    "max_tokens": 64,
                },
                "depends_on": ["input"],
            },
            {
                "name": "output",
                "agent_id": agent_id,
                "config": {
                    "type": "outputNode",
                    "node_type": "outputNode",
                },
                "depends_on": ["llm"],
            },
        ],
        "is_active": True,
        "created_by": "vertical-slice-test",
    }


def step_with_node_type_at_top(step: dict[str, Any]) -> dict[str, Any]:
    """workflow_engine._normalize_steps reads node_type from top-level OR config.

    The REST schema (WorkflowStepCreate) only persists `name`, `agent_id`,
    `config`, `depends_on` — it does NOT propagate a top-level `type` /
    `node_type` field.  workflow_engine looks first at the top level, then
    falls back to `step.get("type")` if present.  When the step is loaded
    back from the DB (Workflow.steps JSON column), only the dict that
    create_workflow built ends up there.

    To make `node_type` reachable, callers may wrap a payload via this
    helper if/when a future schema migration lifts `node_type` to the top
    level.  Today it is a no-op — included for self-documenting test code.
    """
    return step


# ---------------------------------------------------------------------------
# Polling helper
# ---------------------------------------------------------------------------


_TERMINAL_STATES = {"completed", "failed", "cancelled", "paused"}


def poll_until_terminal(
    client: Any,
    run_id: str,
    *,
    api_prefix: str = "/api/v1",
    endpoint: str = "executions",
    timeout_s: float = 5.0,
    interval_s: float = 0.1,
) -> dict[str, Any]:
    """Poll GET /api/v1/{endpoint}/{run_id} until status is terminal.

    Returns the last response JSON body.  Does NOT raise on timeout — the
    caller asserts on the returned status so the test reports its own
    failure mode (which is the deliverable for Wave 0).

    Args:
        client:        TestClient (or AsyncClient/sync wrapper).
        run_id:        UUID of the execution / workflow run.
        api_prefix:    e.g. "/api/v1".
        endpoint:      "executions" or "workflows/{wf_id}/runs" — the
                       caller chooses based on which surface they are
                       exercising.
        timeout_s:     Hard deadline; default 5s per Wave 0 plan.
        interval_s:    Poll interval; default 100ms per Wave 0 plan.

    Returns:
        The last response.json() observed.  Includes a synthetic
        ``"_polling_timed_out": True`` key when the poll budget was
        exhausted without seeing a terminal state.
    """
    deadline = time.monotonic() + timeout_s
    last_body: dict[str, Any] = {}

    while time.monotonic() < deadline:
        url = f"{api_prefix}/{endpoint}/{run_id}"
        resp = client.get(url, headers=auth_headers())
        last_body = (
            resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        )
        # Status can live at .data.status (envelope) or .status (flat).
        data_block = (
            last_body.get("data")
            if isinstance(last_body, dict) and isinstance(last_body.get("data"), dict)
            else last_body
        )
        status = (data_block or {}).get("status")
        if status in _TERMINAL_STATES:
            return last_body
        time.sleep(interval_s)

    last_body["_polling_timed_out"] = True
    return last_body


def is_valid_uuid(s: str) -> bool:
    """Cheap guard for run_id assertions."""
    try:
        UUID(str(s))
        return True
    except (ValueError, TypeError, AttributeError):
        return False


__all__ = [
    "auth_headers",
    "make_minimal_agent_payload",
    "make_minimal_workflow_payload",
    "step_with_node_type_at_top",
    "poll_until_terminal",
    "is_valid_uuid",
]
