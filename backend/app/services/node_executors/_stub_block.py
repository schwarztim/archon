"""Production-mode stub-block enforcement helper.

Phase 3 / WS9 — Node Contract.

A stub-classified node executor (see ``status_registry``) returns
``status='completed'`` without doing the work the node claims to do —
e.g. ``mcpToolNode`` returns ``{_stub: true, result: null}``. In a
durable environment that is a correctness violation: the workflow run
finalises as ``completed`` while no tool was ever invoked.

This module enforces ADR-005's spirit at the node-dispatch boundary:
in ``production`` or ``staging`` (``ARCHON_ENV``), any executor whose
registry status is ``stub``, ``blocked``, or ``designed`` MUST refuse
to run. The dispatcher catches the resulting ``StubBlockError`` and
finalises the run as ``failed`` with ``error_code='stub_blocked'``.

Environment classification matches ADR-005:

    ARCHON_ENV ∈ {production, staging} → durable (block)
    ARCHON_ENV ∈ {dev, test} or unset  → permissive (allow)

See ``docs/adr/orchestration/ADR-005-production-durability-policy.md``.
"""

from __future__ import annotations

import os

from app.services.node_executors.status_registry import (
    NodeStatus,
    get_status,
)

# Environments where stub completion is a correctness violation.
# Mirrors ADR-005 ``is_durable_env`` — anything else is permissive.
_DURABLE_ENVS: frozenset[str] = frozenset({"production", "staging"})

# Statuses that are NOT runnable in a durable environment. ``production``
# and ``beta`` are the only durable-eligible statuses.
_NON_RUNNABLE_STATUSES: frozenset[NodeStatus] = frozenset(
    {NodeStatus.STUB, NodeStatus.BLOCKED, NodeStatus.DESIGNED}
)


class StubBlockError(RuntimeError):
    """A stub-classified node refused to run in a durable environment.

    Carries ``node_type`` and ``status`` for structured event payloads
    (the dispatcher emits ``error_code='stub_blocked'`` and includes
    these in ``step.failed`` / ``run.failed`` payloads).
    """

    def __init__(self, node_type: str, status: NodeStatus, env: str):
        self.node_type = node_type
        self.status = status
        self.env = env
        super().__init__(
            f"node_type={node_type!r} is classified as "
            f"{status.value!r} and cannot run in ARCHON_ENV={env!r}; "
            "stub-classified nodes silently complete without performing "
            "their declared work and are blocked in durable environments."
        )


def _resolve_env(env: str | None) -> str:
    """Return the active ARCHON_ENV (lower-case, defaults to 'dev')."""
    if env is None:
        env = os.getenv("ARCHON_ENV", "dev")
    return (env or "dev").strip().lower()


def assert_node_runnable(node_type: str, env: str | None = None) -> None:
    """Raise :class:`StubBlockError` if *node_type* is not runnable.

    Behaviour:
      - In ``dev`` / ``test`` (or any unrecognised env): always permits.
        Stubs are useful during development and integration testing.
      - In ``production`` / ``staging``: blocks any node whose registry
        status is ``stub``, ``blocked``, or ``designed``.

    This is the single enforcement point. Callers should not duplicate
    the env / status logic — the helper is the contract.
    """
    resolved_env = _resolve_env(env)
    if resolved_env not in _DURABLE_ENVS:
        return

    status = get_status(node_type)
    if status in _NON_RUNNABLE_STATUSES:
        raise StubBlockError(node_type=node_type, status=status, env=resolved_env)


__all__ = [
    "StubBlockError",
    "assert_node_runnable",
]
