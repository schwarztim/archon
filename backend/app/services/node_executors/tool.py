"""Tool node executor — look up and invoke a registered tool.

Legacy NodeContext path
-----------------------
``ToolNodeExecutor`` is the old stub that recorded tool intent but never
invoked anything real.

ActivityContext entry (W4b)
---------------------------
``execute_tool(context)`` is the real implementation:

1. Reads ``node_config["tool_name"]`` and ``node_config["tool_input"]``.
2. Looks up the tool in ``TOOL_REGISTRY`` (a module-level dict mapping
   tool names to async callables).
3. Calls the tool with ``tool_input``, captures the return value.
4. Appends a ``tool_call`` audit event to ``WorkflowRunEvent`` via
   ``context.db_session`` when a session is available.
5. Returns ``ActivityResult`` with the tool output.

Tool registry
~~~~~~~~~~~~~
``TOOL_REGISTRY`` is populated at module load from two sources:

* Built-in tools defined in this module (calculator, echo).
* External tools registered via ``register_tool(name, fn)`` — called by
  plugin modules at import time.

Adding a tool::

    from app.services.node_executors.tool import register_tool

    async def my_tool(input_data: dict) -> dict:
        return {"result": input_data["x"] * 2}

    register_tool("double", my_tool)
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from app.services.node_executors import NodeContext, NodeExecutor, NodeResult, register

logger = logging.getLogger(__name__)

# ── Tool registry ─────────────────────────────────────────────────────

# Maps tool_name -> async callable(input_data: dict) -> dict.
TOOL_REGISTRY: dict[str, Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]] = {}


def register_tool(
    name: str,
    fn: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
) -> None:
    """Register *fn* as the handler for *name* in the global tool registry."""
    TOOL_REGISTRY[name] = fn


# ── Built-in tools ────────────────────────────────────────────────────


async def _tool_echo(input_data: dict[str, Any]) -> dict[str, Any]:
    """Echo the input back as output — useful for testing."""
    return {"echo": input_data}


async def _tool_calculator(input_data: dict[str, Any]) -> dict[str, Any]:
    """Evaluate a simple arithmetic expression from ``input_data["expression"]``."""
    expr: str = str(input_data.get("expression", ""))
    # Restrict to safe characters only.
    allowed = set("0123456789+-*/(). ")
    if not all(c in allowed for c in expr):
        raise ValueError(f"Unsafe expression: {expr!r}")
    result = eval(expr, {"__builtins__": {}})  # noqa: S307, PGH001
    return {"result": result, "expression": expr}


register_tool("echo", _tool_echo)
register_tool("calculator", _tool_calculator)


# ── Legacy NodeContext executor (stub promoted via ActivityContext) ────


@register("toolNode")
class ToolNodeExecutor(NodeExecutor):
    """Stub implementation — real execution via execute_tool(ActivityContext)."""

    async def execute(self, ctx: NodeContext) -> NodeResult:
        config = ctx.config
        tool_name = config.get("toolName") or config.get("tool_name") or "unknown"
        tool_params = config.get("parameters") or {}

        return NodeResult(
            status="completed",
            output={
                "_stub": True,
                "tool_name": tool_name,
                "parameters": tool_params,
                "result": None,
            },
        )


# ── ActivityContext entry ──────────────────────────────────────────────


async def execute_tool(context: Any) -> Any:
    """W4b: look up and invoke a registered tool, return ActivityResult.

    ``context`` is an ``ActivityContext`` (typed as ``Any`` to avoid a
    circular import at module load).

    Config keys (``context.node_config``):
      tool_name        — name of the tool to invoke (required).
      tool_input       — dict passed to the tool callable (default: {}).
      timeout_seconds  — not enforced at this layer; the activity runtime
                         cancellation hook handles long-running tools.
    """
    from app.services.activity_runtime import ActivityResult  # noqa: PLC0415

    config: dict[str, Any] = context.node_config or {}
    tool_name: str = (
        config.get("tool_name") or config.get("toolName") or ""
    ).strip()
    tool_input: dict[str, Any] = config.get("tool_input") or {}

    if not tool_name:
        return ActivityResult(
            status="failed",
            error_code="ValueError",
            error_message="toolNode: tool_name is required",
            non_retryable=True,
        )

    tool_fn = TOOL_REGISTRY.get(tool_name)
    if tool_fn is None:
        return ActivityResult(
            status="failed",
            error_code="ToolNotFound",
            error_message=(
                f"toolNode: tool {tool_name!r} is not registered; "
                f"available tools: {sorted(TOOL_REGISTRY)}"
            ),
            non_retryable=True,
        )

    try:
        tool_output: dict[str, Any] = await tool_fn(tool_input)
    except Exception as exc:  # noqa: BLE001
        logger.warning("execute_tool.error tool=%s", tool_name, exc_info=True)
        return ActivityResult(
            status="failed",
            error_code=type(exc).__name__,
            error_message=str(exc)[:1024],
        )

    # Audit: append a tool_call event when a DB session is available.
    _emit_tool_audit(context, tool_name, tool_input, tool_output)

    return ActivityResult(
        status="completed",
        output_data={
            "tool_name": tool_name,
            "tool_input": tool_input,
            "tool_output": tool_output,
        },
    )


def _emit_tool_audit(
    context: Any,
    tool_name: str,
    tool_input: dict[str, Any],
    tool_output: dict[str, Any],
) -> None:
    """Best-effort: append a tool_call audit row when a DB session is present.

    Failures are logged and swallowed so audit gaps never fail the activity.
    """
    if context.db_session is None:
        return
    try:
        import asyncio  # noqa: PLC0415

        async def _write() -> None:
            from sqlalchemy import text  # noqa: PLC0415

            await context.db_session.execute(
                text(
                    "INSERT INTO workflow_run_events "
                    "(run_id, step_id, event_type, payload, created_at) "
                    "VALUES (:run_id, :step_id, :event_type, :payload, now())"
                ),
                {
                    "run_id": context.run_id,
                    "step_id": context.step_id,
                    "event_type": "tool_call",
                    "payload": {
                        "tool_name": tool_name,
                        "tool_input": tool_input,
                        "tool_output": tool_output,
                    },
                },
            )
            await context.db_session.commit()

        # Schedule on the running loop if inside an async context.
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(_write())
    except Exception as exc:  # noqa: BLE001
        logger.debug("execute_tool: audit write failed: %s", exc)
