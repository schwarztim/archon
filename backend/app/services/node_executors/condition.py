"""Condition node executor — evaluates an expression and emits a branch hint.

Per ADR-003, this executor MUST NOT decide which downstream node runs nor
mutate engine state.  It evaluates the configured expression and emits a
``_hint`` envelope describing which downstream branch the engine should
schedule.  The engine consumes the hint and skips the unselected branch
with ``step.skipped`` events.

Hint shape (canonical, per Phase 3 master plan)::

    {
        "_hint": {
            "kind": "branch",
            "selected_step_ids": ["<step_id>"],
            "alternatives": ["<true_branch>", "<false_branch>"],  # informational
            "selected_label": "true" | "false",                    # informational
        }
    }

Configuration shape::

    {
        "type": "conditionNode",
        "config": {
            "expression": "x > 5",          # or "expr"
            "true_branch": "<step_id>",     # step_id scheduled when expr is True
            "false_branch": "<step_id>",    # step_id scheduled when expr is False
            # Backward-compat: ``conditions`` ConditionGroup also accepted.
        },
    }

Backward compatibility:

The legacy ``output["branch"]`` key (``"true"``/``"false"``) is preserved so
existing tests and consumers continue working.  The engine prefers ``_hint``
when present.

Uses simpleeval for safe sandboxed expression evaluation.
"""

from __future__ import annotations

import logging
from typing import Any

from app.services.node_executors import NodeContext, NodeExecutor, NodeResult, register

logger = logging.getLogger(__name__)


def _flatten_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    """Flatten upstream outputs into a single dict for expression evaluation."""
    flat: dict[str, Any] = {}
    for step_id, step_out in inputs.items():
        if isinstance(step_out, dict):
            for k, v in step_out.items():
                flat[f"{step_id}.{k}"] = v
                flat[k] = v  # also expose without prefix for convenience
        else:
            flat[step_id] = step_out
    return flat


def _eval_expression(expression: str, names: dict[str, Any]) -> bool:
    """Evaluate *expression* against *names* using simpleeval."""
    try:
        from simpleeval import EvalWithCompoundTypes, FeatureNotAvailable  # noqa: PLC0415

        evaluator = EvalWithCompoundTypes(names=names)
        result = evaluator.eval(expression)
        return bool(result)
    except ImportError:
        # simpleeval not installed — fall back to very restricted ast eval
        logger.warning("simpleeval not installed; falling back to restricted eval")
        return _restricted_eval(expression, names)
    except FeatureNotAvailable as exc:
        raise ValueError(f"Disallowed expression feature: {exc}") from exc


def _restricted_eval(expression: str, names: dict[str, Any]) -> bool:
    """Minimal safe fallback when simpleeval is absent — literal comparisons only."""
    import ast  # noqa: PLC0415

    # Replace known names in expression with their literal repr
    for name, value in names.items():
        expression = expression.replace(name, repr(value))

    tree = ast.parse(expression, mode="eval")
    # Only allow Compare, BoolOp, UnaryOp, Constant, Name nodes
    for node in ast.walk(tree):
        if not isinstance(
            node,
            (
                ast.Expression,
                ast.Compare,
                ast.BoolOp,
                ast.UnaryOp,
                ast.And,
                ast.Or,
                ast.Not,
                ast.Eq,
                ast.NotEq,
                ast.Lt,
                ast.LtE,
                ast.Gt,
                ast.GtE,
                ast.Constant,
                ast.Name,
                ast.Load,
            ),
        ):
            raise ValueError(f"Disallowed AST node in expression: {type(node).__name__}")
    return bool(eval(compile(tree, "<expr>", "eval"), {"__builtins__": {}}, names))  # noqa: S307


@register("conditionNode")
class ConditionNodeExecutor(NodeExecutor):
    """Evaluate a condition expression and emit an ADR-003 branch hint."""

    async def execute(self, ctx: NodeContext) -> NodeResult:
        config = ctx.config
        # Accept both "expression" (legacy) and "expr" (Phase 3 master plan)
        expression: str | None = config.get("expression") or config.get("expr")

        # Also support the visual condition builder's ConditionGroup format
        condition_group = config.get("conditions")
        if not expression and condition_group:
            expression = _build_expression_from_group(condition_group)

        if not expression:
            return NodeResult(
                status="failed",
                error="conditionNode: no expression or conditions configured",
            )

        names = _flatten_inputs(ctx.inputs)
        # Add node_data scalars as top-level names too
        names.update({k: v for k, v in config.items() if isinstance(v, (str, int, float, bool))})

        try:
            result = _eval_expression(expression, names)
        except Exception as exc:  # noqa: BLE001
            logger.warning("conditionNode.eval_error", exc_info=True)
            return NodeResult(
                status="failed",
                error=f"conditionNode expression error: {exc}",
            )

        branch_label = "true" if result else "false"
        true_branch_id: str | None = config.get("true_branch") or config.get("trueBranch")
        false_branch_id: str | None = config.get("false_branch") or config.get("falseBranch")

        # Build alternatives list (only step_ids that are configured)
        alternatives = [b for b in (true_branch_id, false_branch_id) if b]

        # The selected step_id is the one mapped to the chosen branch label.
        selected_step_id: str | None = (
            true_branch_id if result else false_branch_id
        )

        output: dict[str, Any] = {
            "branch": branch_label,        # legacy
            "result": result,              # legacy
        }

        # Only emit the hint envelope when we have step ids to route to.
        if selected_step_id is not None:
            output["_hint"] = {
                "kind": "branch",
                "selected_step_ids": [selected_step_id],
                "alternatives": alternatives,
                "selected_label": branch_label,
            }

        return NodeResult(status="completed", output=output)


def _build_expression_from_group(group: dict) -> str:
    """Convert a ConditionGroup dict into a simpleeval-compatible expression."""
    if not isinstance(group, dict):
        return "False"
    logic: str = group.get("logic", "AND")
    conditions: list[dict] = group.get("conditions", [])
    if not conditions:
        return "True"

    parts: list[str] = []
    for row in conditions:
        field_name = row.get("field", "")
        operator = row.get("operator", "equals")
        value = row.get("value", "")

        # Map operator to Python expression
        op_map = {
            "equals": f"{field_name!r} == {value!r}",
            "not_equals": f"{field_name!r} != {value!r}",
            "contains": f"{value!r} in str({field_name!r})",
            "gt": f"{field_name!r} > {value!r}",
            "lt": f"{field_name!r} < {value!r}",
            "gte": f"{field_name!r} >= {value!r}",
            "lte": f"{field_name!r} <= {value!r}",
            "starts_with": f"str({field_name!r}).startswith({value!r})",
            "ends_with": f"str({field_name!r}).endswith({value!r})",
        }
        parts.append(op_map.get(operator, "False"))

    joiner = " and " if logic == "AND" else " or "
    return f"({joiner.join(parts)})"
