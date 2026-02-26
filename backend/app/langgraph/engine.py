"""LangGraph-based agent execution engine.

Provides ``create_graph`` to build a compiled LangGraph ``StateGraph`` from a
JSON agent definition, and ``execute_agent`` to run it asynchronously.

``execute_agent`` now accepts an optional ``tenant_id`` for tenant-isolated
execution with audit logging and credential injection.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.langgraph.nodes import process_node, respond_node
from app.langgraph.state import AgentState

logger = logging.getLogger(__name__)


def _should_respond(state: AgentState) -> str:
    """Conditional edge: route to 'respond' unless an error occurred."""
    if state.get("error"):
        return END
    return "respond"


def create_graph(definition: dict[str, Any]) -> CompiledStateGraph:
    """Build a compiled LangGraph ``StateGraph`` from an agent definition.

    For the vertical slice the definition is inspected only for an optional
    ``skip_processing`` flag.  The default graph is::

        START ─▶ process ──(conditional)──▶ respond ─▶ END

    Args:
        definition: Agent definition dict (currently uses ``skip_processing``).

    Returns:
        A compiled ``CompiledStateGraph`` ready for ``ainvoke``.
    """
    graph = StateGraph(AgentState)

    graph.add_node("process", process_node)
    graph.add_node("respond", respond_node)

    if definition.get("skip_processing"):
        graph.set_entry_point("respond")
    else:
        graph.set_entry_point("process")
        graph.add_conditional_edges("process", _should_respond)

    graph.add_edge("respond", END)

    return graph.compile()


async def _inject_credentials(
    definition: dict[str, Any],
    tenant_id: str,
) -> dict[str, Any]:
    """Fetch tenant credentials from SecretsManager and inject into definition.

    Looks for ``credentials`` keys in the definition and resolves them from
    the Vault-backed SecretsManager, scoped to the given tenant.

    Returns:
        A shallow copy of *definition* with resolved credential values.
    """
    from app.secrets.manager import get_secrets_manager

    credential_paths: list[str] = definition.get("credentials", [])
    if not credential_paths:
        return definition

    secrets = await get_secrets_manager()
    resolved: dict[str, Any] = {}
    for path in credential_paths:
        try:
            resolved[path] = await secrets.get_secret(path, tenant_id)
        except Exception:
            logger.warning(
                "Failed to resolve credential",
                extra={"path": path, "tenant_id": tenant_id},
            )

    enriched = {**definition, "resolved_credentials": resolved}
    return enriched


async def execute_agent(
    agent_id: str,
    definition: dict[str, Any],
    input_data: dict[str, Any],
    *,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """Create and run an agent graph, returning a result dict.

    Args:
        agent_id: Unique identifier for the agent (used in logging/tracing).
        definition: JSON-serialisable agent definition forwarded to
            ``create_graph``.
        input_data: Caller-supplied input; must contain a ``message`` key
            whose value is the user prompt string.
        tenant_id: Optional tenant identifier for tenant-isolated execution.
            When provided, credentials are injected from SecretsManager and
            all operations are audit-logged with the tenant context.

    Returns:
        On success::

            {"output": <any>, "steps": [...], "status": "completed"}

        On failure::

            {"error": "<description>", "status": "failed"}
    """
    log_extra: dict[str, Any] = {"agent_id": agent_id}
    if tenant_id:
        log_extra["tenant_id"] = tenant_id

    logger.info("graph.execution.start", extra=log_extra)

    try:
        # Inject tenant credentials when tenant context is available
        effective_definition = definition
        if tenant_id:
            effective_definition = await _inject_credentials(
                definition, tenant_id
            )

        compiled = create_graph(effective_definition)

        user_message = input_data.get("message", "")
        initial_state: dict[str, Any] = {
            "messages": [HumanMessage(content=str(user_message))],
            "current_step": "process",
            "output": None,
            "error": None,
        }

        result = await compiled.ainvoke(initial_state)

        steps = [
            m.content
            for m in result.get("messages", [])
            if hasattr(m, "content")
        ]

        logger.info("graph.execution.complete", extra=log_extra)

        return {
            "output": result.get("output"),
            "steps": steps,
            "status": "completed",
        }

    except Exception as exc:  # noqa: BLE001
        logger.error(
            "graph.execution.error",
            extra={**log_extra, "error": type(exc).__name__},
        )
        return {
            "error": f"{type(exc).__name__}: {exc}",
            "status": "failed",
        }


class LangGraphEngine:
    """Convenience wrapper exposing the functional API as a class.

    Provides ``execute_graph`` with tenant-aware execution, credential
    injection, and audit logging.
    """

    async def execute_graph(
        self,
        agent_id: str,
        definition: dict[str, Any],
        input_data: dict[str, Any],
        *,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        """Execute an agent graph, delegating to :func:`execute_agent`.

        Args:
            agent_id: Unique identifier for the agent.
            definition: Agent definition dict.
            input_data: Must contain a ``message`` key with the user prompt.
            tenant_id: Optional tenant for isolation and credential injection.

        Returns:
            Result dict with ``output``, ``steps``, and ``status`` keys.
        """
        return await execute_agent(
            agent_id, definition, input_data, tenant_id=tenant_id
        )
