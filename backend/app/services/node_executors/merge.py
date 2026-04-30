"""Merge node executor — combines outputs from multiple upstream branches.

Strategy selection:
  ``"first_complete"`` / ``"first"``   first non-empty upstream output
  ``"all_complete"``  / ``"all"``      list of all upstream outputs (default)
  ``"concat"``                          concatenate list-typed values + scalars
  ``"merge_dicts"``   / ``"merge"``    deep-merge dicts; last value wins on
                                       scalar conflicts

Both the legacy short names (``first``, ``all``, ``merge``) and the
Phase 3 master plan names (``first_complete``, ``all_complete``,
``merge_dicts``) are accepted.
"""

from __future__ import annotations

from typing import Any

from app.services.node_executors import NodeContext, NodeExecutor, NodeResult, register


def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


# Strategy aliases — map the operator-facing name to a canonical id.
_STRATEGY_ALIASES: dict[str, str] = {
    "first": "first_complete",
    "first_complete": "first_complete",
    "all": "all_complete",
    "all_complete": "all_complete",
    "concat": "concat",
    "merge": "merge_dicts",
    "merge_dicts": "merge_dicts",
}


@register("mergeNode")
class MergeNodeExecutor(NodeExecutor):
    """Combine multiple upstream outputs into one."""

    async def execute(self, ctx: NodeContext) -> NodeResult:
        raw_strategy: str = str(ctx.config.get("strategy") or "all_complete").lower()
        strategy = _STRATEGY_ALIASES.get(raw_strategy, "all_complete")

        upstream_values = list(ctx.inputs.values())

        if strategy == "first_complete":
            for val in upstream_values:
                if val:
                    return NodeResult(
                        status="completed",
                        output={"merged": val, "strategy": strategy},
                    )
            return NodeResult(
                status="completed",
                output={"merged": None, "strategy": strategy},
            )

        if strategy == "concat":
            combined: list[Any] = []
            for val in upstream_values:
                if isinstance(val, list):
                    combined.extend(val)
                elif val is not None:
                    combined.append(val)
            return NodeResult(
                status="completed",
                output={"merged": combined, "strategy": strategy},
            )

        if strategy == "merge_dicts":
            merged: dict[str, Any] = {}
            for val in upstream_values:
                if isinstance(val, dict):
                    merged = _deep_merge(merged, val)
            return NodeResult(
                status="completed",
                output={"merged": merged, "strategy": strategy},
            )

        # Default: "all_complete" — return list of all upstream outputs
        return NodeResult(
            status="completed",
            output={
                "merged": upstream_values,
                "branch_count": len(upstream_values),
                "strategy": strategy,
            },
        )
