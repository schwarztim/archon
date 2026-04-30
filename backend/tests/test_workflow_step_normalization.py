"""Tests for app.services.workflow_engine._normalize_steps.

Phase 1 fix: REST `WorkflowStepCreate` persists `node_type` either at the top
level (preferred, lifted by the route handler) OR nested under `config`
(legacy and slice-helper shape). The normalizer must accept both, with the
top-level value winning when both are present.
"""
from __future__ import annotations

import pytest

from app.services.workflow_engine import (
    WorkflowValidationError,
    _normalize_steps,
)


def test_node_type_at_top_level_wins() -> None:
    raw_steps = [
        {
            "step_id": "s1",
            "name": "input",
            "node_type": "inputNode",
            "config": {"node_type": "WRONG"},
        }
    ]
    norm, order, _ = _normalize_steps(raw_steps)
    assert order == ["s1"]
    assert norm["s1"]["node_type"] == "inputNode"


def test_node_type_falls_back_to_config_node_type() -> None:
    """The slice-helper shape: node_type is only inside config."""
    raw_steps = [
        {
            "step_id": "s1",
            "name": "llm",
            "config": {"node_type": "llmNode", "model": "gpt-3.5-turbo"},
        }
    ]
    norm, _, _ = _normalize_steps(raw_steps)
    assert norm["s1"]["node_type"] == "llmNode"


def test_node_type_falls_back_to_config_type() -> None:
    raw_steps = [
        {
            "step_id": "s1",
            "name": "output",
            "config": {"type": "outputNode"},
        }
    ]
    norm, _, _ = _normalize_steps(raw_steps)
    assert norm["s1"]["node_type"] == "outputNode"


def test_step_with_only_agent_id_uses_legacy_path() -> None:
    raw_steps = [
        {
            "step_id": "s1",
            "name": "legacy",
            "agent_id": "00000000-0000-0000-0000-000000000001",
            "config": {},
        }
    ]
    norm, _, _ = _normalize_steps(raw_steps)
    assert norm["s1"]["agent_id"] == "00000000-0000-0000-0000-000000000001"
    assert norm["s1"]["node_type"] is None


def test_step_with_neither_raises() -> None:
    raw_steps = [
        {
            "step_id": "s1",
            "name": "broken",
            "config": {},
        }
    ]
    with pytest.raises(WorkflowValidationError):
        _normalize_steps(raw_steps)
