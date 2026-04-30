"""Structured output node executor — documented stub for JSON-mode LLM calls.

TODO: Implement via call_llm with response_format={"type": "json_object"}
and validate against the configured JSON schema.
"""

from __future__ import annotations

from app.services.node_executors import NodeContext, NodeExecutor, NodeResult, register


@register("structuredOutputNode")
class StructuredOutputNodeExecutor(NodeExecutor):
    """Stub: returns placeholder structured output.

    TODO(v2): call call_llm with json_mode=True and the configured schema,
    then validate and return the parsed JSON.
    """

    async def execute(self, ctx: NodeContext) -> NodeResult:
        config = ctx.config
        model = config.get("model") or "gpt-4o-mini"
        schema = config.get("schema") or {}

        return NodeResult(
            status="completed",
            output={
                "_stub": True,
                "model": model,
                "schema": schema,
                "result": {},  # TODO(v2): real structured output
            },
        )
