"""Database query node executor — documented stub for connector-based queries.

TODO: Implement real query execution via the connector framework
(ConnectorService) with the configured connection and query parameters.
"""

from __future__ import annotations

from app.services.node_executors import NodeContext, NodeExecutor, NodeResult, register


@register("databaseQueryNode")
class DatabaseQueryNodeExecutor(NodeExecutor):
    """Stub: records query intent; real execution deferred to v2.

    TODO(v2): look up the connection by connector_id, execute the SQL
    query via ConnectorService, and return rows as dicts.
    """

    async def execute(self, ctx: NodeContext) -> NodeResult:
        config = ctx.config
        query = config.get("query") or ""
        connector_id = config.get("connectorId") or config.get("connector_id") or "unknown"

        return NodeResult(
            status="completed",
            output={
                "_stub": True,
                "connector_id": connector_id,
                "query": query,
                "rows": [],  # TODO(v2): real query result
                "row_count": 0,
            },
        )
