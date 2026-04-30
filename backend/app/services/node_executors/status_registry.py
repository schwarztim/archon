"""Node executor production-readiness classification.

Phase 3 / WS9 — Node Contract.

Single source of truth in code for whether a registered node executor is
safe to run in a durable (production / staging) environment. Mirrors the
``status`` field in ``docs/feature-matrix.yaml`` for every entry under
``categories.node_executors``.

Status semantics
----------------

``production``
    Real implementation, end-to-end coverage, safe in any environment.
``beta``
    Real implementation with documented caveats; runnable in production
    while gaps in the ``feature-matrix.yaml`` ``gap`` field are tracked.
``stub``
    Returns success without doing the work the node claims to perform.
    MUST be blocked in production / staging — silent stub completion is
    a correctness violation (a workflow's "successful" run never actually
    ran the node).
``blocked``
    Explicitly disabled (e.g. by a kill-switch). Not runnable in any env
    until re-enabled.
``designed``
    Schema/type exists but no implementation registered. Treated like a
    stub for the production gate.

Authoritative source
--------------------

``docs/feature-matrix.yaml`` is the operator-facing source of truth.
This module mirrors that file for runtime enforcement so a misconfigured
or stub-classified node cannot silently complete in a durable environment.
``scripts/check-feature-matrix.py`` validates the YAML against the
codebase; the registry below is hand-synced to that YAML and a unit test
guards against drift between the registry and ``NODE_EXECUTORS``.
"""

from __future__ import annotations

from enum import Enum


class NodeStatus(str, Enum):
    """Production-readiness classification for a node executor."""

    PRODUCTION = "production"
    BETA = "beta"
    STUB = "stub"  # silently completes — must be blocked in prod
    BLOCKED = "blocked"  # explicitly disabled
    DESIGNED = "designed"  # not yet implemented


# ---------------------------------------------------------------------------
# Authoritative classification table
# ---------------------------------------------------------------------------
#
# Mirrors docs/feature-matrix.yaml `categories.node_executors` (28 entries).
# When updating, update the YAML in the same change and re-run
# `python3 scripts/check-feature-matrix.py`.
NODE_STATUS: dict[str, NodeStatus] = {
    # ── Production ────────────────────────────────────────────────────
    "llmNode": NodeStatus.PRODUCTION,
    "inputNode": NodeStatus.PRODUCTION,
    "outputNode": NodeStatus.PRODUCTION,
    # ── Beta ──────────────────────────────────────────────────────────
    "conditionNode": NodeStatus.BETA,
    "switchNode": NodeStatus.BETA,
    "parallelNode": NodeStatus.BETA,
    "mergeNode": NodeStatus.BETA,
    "delayNode": NodeStatus.BETA,
    "humanApprovalNode": NodeStatus.BETA,
    "dlpScanNode": NodeStatus.BETA,
    "costGateNode": NodeStatus.BETA,
    "httpRequestNode": NodeStatus.BETA,
    "subAgentNode": NodeStatus.BETA,
    "subWorkflowNode": NodeStatus.BETA,
    "webhookTriggerNode": NodeStatus.BETA,
    "scheduleTriggerNode": NodeStatus.BETA,
    "embeddingNode": NodeStatus.BETA,
    "structuredOutputNode": NodeStatus.BETA,
    "visionNode": NodeStatus.BETA,
    # ── Stub (must be blocked in production / staging) ────────────────
    "loopNode": NodeStatus.STUB,
    "humanInputNode": NodeStatus.STUB,
    "mcpToolNode": NodeStatus.STUB,
    "toolNode": NodeStatus.STUB,
    "databaseQueryNode": NodeStatus.STUB,
    "functionCallNode": NodeStatus.STUB,
    "vectorSearchNode": NodeStatus.STUB,
    "documentLoaderNode": NodeStatus.STUB,
    "streamOutputNode": NodeStatus.STUB,
}


def get_status(node_type: str) -> NodeStatus:
    """Return the classification for *node_type*.

    Unknown node types are treated as ``DESIGNED`` (no implementation
    registered) — the production gate blocks them.
    """
    return NODE_STATUS.get(node_type, NodeStatus.DESIGNED)


def is_runnable_in_production(node_type: str) -> bool:
    """Return True iff *node_type* is safe to run in a durable environment.

    Only ``production`` and ``beta`` are runnable. ``stub``, ``blocked``,
    and ``designed`` are not — silent success would corrupt run state.
    """
    return get_status(node_type) in (NodeStatus.PRODUCTION, NodeStatus.BETA)


def list_by_status() -> dict[NodeStatus, list[str]]:
    """Group registered node types by status — useful for ops dashboards."""
    grouped: dict[NodeStatus, list[str]] = {s: [] for s in NodeStatus}
    for node_type, status in NODE_STATUS.items():
        grouped[status].append(node_type)
    for status in grouped:
        grouped[status].sort()
    return grouped


__all__ = [
    "NODE_STATUS",
    "NodeStatus",
    "get_status",
    "is_runnable_in_production",
    "list_by_status",
]
