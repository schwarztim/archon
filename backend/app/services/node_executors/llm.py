"""LLM node executor — calls call_llm and emits routing metadata.

Phase 4 / WS10 — Model Routing Squad.

The executor preserves its Phase 3 contract (calls ``call_llm`` directly
when no tenant context is available, returns content + token usage + cost)
but additionally attempts a routed call when a tenant_id is present in
the NodeContext.  The routing decision is included in ``output["routing"]``
so it can be persisted into ``workflow_run_steps`` for replayability and
emitted as a Prometheus counter.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from app.services.node_executors import NodeContext, NodeExecutor, NodeResult, register

logger = logging.getLogger(__name__)


@register("llmNode")
class LLMNodeExecutor(NodeExecutor):
    """Execute an llmNode: routes to a provider and emits decision metadata."""

    async def execute(self, ctx: NodeContext) -> NodeResult:
        from app.langgraph.llm import call_llm  # noqa: PLC0415

        config = ctx.config
        model: str = config.get("model") or "gpt-3.5-turbo"
        system: str | None = config.get("systemPrompt") or config.get("system_prompt")
        max_tokens: int = int(config.get("maxTokens") or config.get("max_tokens") or 1024)
        temperature: float = float(config.get("temperature") or 0.7)
        capability_required: list[str] = list(
            config.get("capabilityRequired")
            or config.get("capability_required")
            or []
        )

        # Build prompt from config or upstream inputs
        prompt: str = (
            config.get("prompt")
            or config.get("userPrompt")
            or config.get("user_prompt")
            or str(ctx.inputs)
        )

        # Inject upstream outputs into the prompt if placeholder present
        for step_id, step_out in ctx.inputs.items():
            prompt = prompt.replace(f"{{{step_id}}}", str(step_out))

        # Decide which path to take: routed (tenant-scoped) or direct.
        routing_decision: Any = None
        try:
            tenant_uuid = _coerce_tenant_uuid(ctx.tenant_id)
        except (ValueError, TypeError):
            tenant_uuid = None

        try:
            if tenant_uuid is not None:
                from app.langgraph.llm import call_llm_routed  # noqa: PLC0415

                response, routing_decision = await call_llm_routed(
                    tenant_id=tenant_uuid,
                    messages=[{"role": "user", "content": prompt}],
                    requested_model=model,
                    capability_required=capability_required,
                    session=ctx.db_session,
                    system=system,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
            else:
                response = await call_llm(
                    prompt,
                    model=model,
                    system=system,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )

            output: dict[str, Any] = {
                "content": response.content,
                "model_used": response.model_used,
                "latency_ms": response.latency_ms,
            }
            if routing_decision is not None:
                output["routing"] = {
                    "model": routing_decision.model,
                    "provider": routing_decision.provider,
                    "reason": routing_decision.reason,
                    "fallback_chain": list(routing_decision.fallback_chain or []),
                }
                _record_route_metric(
                    str(ctx.tenant_id),
                    routing_decision.reason,
                )

            return NodeResult(
                status="completed",
                output=output,
                token_usage={
                    "prompt_tokens": response.prompt_tokens,
                    "completion_tokens": response.completion_tokens,
                    "total_tokens": response.total_tokens,
                },
                cost_usd=response.cost_usd,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("llmNode.execute_error", exc_info=True)
            return NodeResult(status="failed", error=f"{type(exc).__name__}: {exc}")


def _coerce_tenant_uuid(value: Any) -> UUID | None:
    """Coerce a string / UUID / None into a UUID.  Returns None on any miss."""
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    s = str(value).strip()
    if not s:
        return None
    return UUID(s)


def _record_route_metric(tenant_id: str, reason: str) -> None:
    """Increment ``archon_model_route_decision_total{tenant_id, reason}``.

    The metrics middleware doesn't yet expose a generic counter helper, so
    this writes directly into its in-memory dict.  Failures are silent —
    metric emission must never break a workflow run.
    """
    try:
        from app.middleware import metrics_middleware as mm  # noqa: PLC0415

        # Lazy-attach a private counter dict on the module the first time
        # we observe a routing decision.  Dynamic attachment keeps the
        # middleware module unaware of router internals.
        bucket: dict[tuple[str, str], int] = getattr(
            mm, "_route_decision_counts", None
        )  # type: ignore[assignment]
        if bucket is None:
            bucket = {}
            setattr(mm, "_route_decision_counts", bucket)
        bucket[(tenant_id, reason)] = bucket.get((tenant_id, reason), 0) + 1
    except Exception as exc:  # noqa: BLE001
        logger.debug("metric_emit_failed: %s", exc)
