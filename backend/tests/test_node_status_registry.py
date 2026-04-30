"""Unit tests for the node executor status registry (Phase 3 / WS9).

Guards against:
  - Drift between ``NODE_EXECUTORS`` (the runtime registry) and
    ``NODE_STATUS`` (the production-readiness table). Adding a new
    executor without classifying it MUST fail the suite.
  - Quiet-success on unknown node types — they should classify as
    ``DESIGNED`` (treated as non-runnable in production).
  - Misclassification slipping through ``is_runnable_in_production`` —
    only ``production`` and ``beta`` are runnable.
  - Bucketing regressions in ``list_by_status``.
"""

from __future__ import annotations

import pytest

from app.services.node_executors import NODE_EXECUTORS
from app.services.node_executors.status_registry import (
    NODE_STATUS,
    NodeStatus,
    get_status,
    is_runnable_in_production,
    list_by_status,
)


def test_every_registered_node_has_status() -> None:
    """Drift guard: every registered executor must have a NODE_STATUS entry.

    Adding a new node executor without classifying its production-readiness
    is a governance bug — the runtime gate cannot decide whether to allow
    or block it. This test fails immediately so the contributor must
    classify the node before merging.
    """
    registered = set(NODE_EXECUTORS.keys())
    classified = set(NODE_STATUS.keys())
    missing = registered - classified
    assert not missing, (
        f"Registered node executors missing from NODE_STATUS: {sorted(missing)}. "
        f"Every executor in NODE_EXECUTORS must be classified in "
        f"node_executors/status_registry.py and mirrored in "
        f"docs/feature-matrix.yaml."
    )


def test_no_orphan_classifications() -> None:
    """The reverse drift guard: NODE_STATUS must not list unregistered types.

    A classification for a node_type that is not in NODE_EXECUTORS is
    either a typo or a removed executor whose entry was forgotten.
    """
    registered = set(NODE_EXECUTORS.keys())
    classified = set(NODE_STATUS.keys())
    orphans = classified - registered
    assert not orphans, (
        f"NODE_STATUS lists node types not in NODE_EXECUTORS: {sorted(orphans)}. "
        f"Either restore the executor registration or remove the classification."
    )


def test_get_status_for_unknown_returns_designed() -> None:
    """Unknown / unregistered node types fall through to DESIGNED.

    DESIGNED is treated as non-runnable in production — fail-closed by
    default for anything the registry does not recognise.
    """
    assert get_status("totallyMadeUpNode") is NodeStatus.DESIGNED
    assert get_status("") is NodeStatus.DESIGNED


def test_is_runnable_in_production_blocks_stubs() -> None:
    """Only production + beta are runnable in durable environments."""
    assert is_runnable_in_production("llmNode") is True  # production
    assert is_runnable_in_production("conditionNode") is True  # beta
    assert is_runnable_in_production("loopNode") is False  # stub
    assert is_runnable_in_production("mcpToolNode") is False  # stub
    assert is_runnable_in_production("unknownXYZ") is False  # designed


def test_list_by_status_groups_correctly() -> None:
    """Every classified node appears in exactly one status bucket."""
    grouped = list_by_status()

    # All five status buckets are present (even if empty).
    assert set(grouped.keys()) == set(NodeStatus)

    # Round-trip: union of buckets == NODE_STATUS keys, no overlap.
    flattened: list[str] = []
    for nodes in grouped.values():
        flattened.extend(nodes)
    assert sorted(flattened) == sorted(NODE_STATUS.keys())
    assert len(flattened) == len(set(flattened)), "node appears in multiple buckets"

    # Spot-check: known production / beta / stub members land where expected.
    assert "llmNode" in grouped[NodeStatus.PRODUCTION]
    assert "conditionNode" in grouped[NodeStatus.BETA]
    assert "loopNode" in grouped[NodeStatus.STUB]
    assert "mcpToolNode" in grouped[NodeStatus.STUB]


def test_node_status_enum_str_values() -> None:
    """Enum values are the canonical lowercase strings used in YAML."""
    assert NodeStatus.PRODUCTION.value == "production"
    assert NodeStatus.BETA.value == "beta"
    assert NodeStatus.STUB.value == "stub"
    assert NodeStatus.BLOCKED.value == "blocked"
    assert NodeStatus.DESIGNED.value == "designed"


@pytest.mark.parametrize(
    "node_type,expected_status",
    [
        # Production
        ("llmNode", NodeStatus.PRODUCTION),
        ("inputNode", NodeStatus.PRODUCTION),
        ("outputNode", NodeStatus.PRODUCTION),
        # Beta — sample
        ("conditionNode", NodeStatus.BETA),
        ("dlpScanNode", NodeStatus.BETA),
        ("costGateNode", NodeStatus.BETA),
        ("delayNode", NodeStatus.BETA),
        ("embeddingNode", NodeStatus.BETA),
        ("structuredOutputNode", NodeStatus.BETA),
        ("visionNode", NodeStatus.BETA),
        # Stub — sample (must be blocked in production)
        ("loopNode", NodeStatus.STUB),
        ("mcpToolNode", NodeStatus.STUB),
        ("toolNode", NodeStatus.STUB),
        ("humanInputNode", NodeStatus.STUB),
        ("databaseQueryNode", NodeStatus.STUB),
        ("functionCallNode", NodeStatus.STUB),
        ("vectorSearchNode", NodeStatus.STUB),
        ("documentLoaderNode", NodeStatus.STUB),
        ("streamOutputNode", NodeStatus.STUB),
    ],
)
def test_classification_pins(node_type: str, expected_status: NodeStatus) -> None:
    """Pin known classifications so accidental edits are caught.

    Mirrors docs/feature-matrix.yaml. If the matrix changes for any of
    these nodes, update both files in the same change.
    """
    assert get_status(node_type) is expected_status
