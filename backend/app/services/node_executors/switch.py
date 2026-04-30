"""Switch node executor — multi-branch routing emitting an ADR-003 branch hint.

Per ADR-003, this executor emits a ``_hint`` envelope describing the single
selected step_id; the engine consumes the hint and skips the unselected
branches with ``step.skipped`` events.

Hint shape::

    {
        "_hint": {
            "kind": "branch",
            "selected_step_ids": ["<step_id>"],
            "alternatives": ["<step_id>", "<step_id>", ...],
            "selected_label": "<case_value>" | "default",
        }
    }

Configuration shape (Phase 3 master plan)::

    {
        "type": "switchNode",
        "config": {
            "value_expr": "...",        # expression evaluated to a value
            "cases": {                  # mapping value → step_id
                "red":   "step-3",
                "blue":  "step-4",
            },
            "default_step_id": "step-5",
        },
    }

Backward compatibility:
    The legacy list shape (``cases: [{value, label}, ...]``) is still
    accepted; in that case no ``_hint`` is emitted because no step_id is
    available.  Legacy ``output["branch"]`` / ``output["matched"]`` keys
    are preserved.
"""

from __future__ import annotations

import logging
from typing import Any

from app.services.node_executors import NodeContext, NodeExecutor, NodeResult, register
from app.services.node_executors.condition import _flatten_inputs

logger = logging.getLogger(__name__)


def _evaluate_expr(expression: str, names: dict[str, Any]) -> Any:
    """Evaluate an expression in a sandboxed namespace, returning its value."""
    try:
        from simpleeval import EvalWithCompoundTypes  # noqa: PLC0415

        return EvalWithCompoundTypes(names=names).eval(expression)
    except ImportError:
        # simpleeval not installed — fall back to a simple Python eval in a
        # restricted namespace (no builtins), safe for literal expressions.
        try:
            return eval(expression, {"__builtins__": {}}, names)  # noqa: S307
        except Exception:  # noqa: BLE001
            return expression  # treat expression itself as the value
    except Exception:  # noqa: BLE001
        return expression


@register("switchNode")
class SwitchNodeExecutor(NodeExecutor):
    """Evaluate an expression and select a case → emit ADR-003 branch hint.

    The executor accepts both the new dict-cases shape (``cases: {value:
    step_id}``) and the legacy list-cases shape (``cases: [{value, label}]``).
    """

    async def execute(self, ctx: NodeContext) -> NodeResult:
        config = ctx.config
        # Accept both "expression" (legacy) and "value_expr" (Phase 3)
        expression: str | None = (
            config.get("expression")
            or config.get("value_expr")
            or config.get("valueExpr")
        )
        if not expression:
            return NodeResult(
                status="failed",
                error="switchNode: expression / value_expr is required",
            )

        cases_raw = config.get("cases")
        default_step_id: str | None = (
            config.get("default_step_id") or config.get("defaultStepId")
        )

        names = _flatten_inputs(ctx.inputs)
        names.update({k: v for k, v in config.items() if isinstance(v, (str, int, float, bool))})

        evaluated = _evaluate_expr(expression, names)
        evaluated_str = str(evaluated)

        matched_branch_label = "default"
        matched = False
        selected_step_id: str | None = default_step_id
        alternatives: list[str] = []

        if isinstance(cases_raw, dict):
            # Phase 3 dict shape: {value: step_id}
            alternatives = [sid for sid in cases_raw.values() if isinstance(sid, str) and sid]
            if default_step_id:
                alternatives = list(dict.fromkeys(alternatives + [default_step_id]))

            for case_value, case_step_id in cases_raw.items():
                if str(case_value) == evaluated_str and isinstance(case_step_id, str):
                    matched_branch_label = str(case_value)
                    matched = True
                    selected_step_id = case_step_id
                    break

        elif isinstance(cases_raw, list):
            # Legacy list shape: [{"value": ..., "label": ...}]
            for case in cases_raw:
                if not isinstance(case, dict):
                    continue
                case_value = case.get("value")
                if case_value is not None and str(evaluated_str) == str(case_value):
                    matched_branch_label = str(case_value)
                    matched = True
                    # Legacy shape has no step_id — leave selected as default (None)
                    break

        output: dict[str, Any] = {
            "branch": matched_branch_label,        # legacy
            "matched": matched,                     # legacy
            "evaluated_value": evaluated_str,       # legacy
        }

        # Emit hint only when we can resolve a concrete step_id.
        if selected_step_id is not None:
            output["_hint"] = {
                "kind": "branch",
                "selected_step_ids": [selected_step_id],
                "alternatives": alternatives or [selected_step_id],
                "selected_label": matched_branch_label,
            }

        return NodeResult(status="completed", output=output)
