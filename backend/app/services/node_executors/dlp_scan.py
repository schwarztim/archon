"""DLP scan node executor — calls DLPService.scan_content on input data.

If any high-severity finding is detected and actionOnViolation is "block",
the node fails and the workflow is aborted.
"""

from __future__ import annotations

import logging

from app.services.node_executors import NodeContext, NodeExecutor, NodeResult, register

logger = logging.getLogger(__name__)


@register("dlpScanNode")
class DLPScanNodeExecutor(NodeExecutor):
    """Scan inputs for PII / secrets using the DLP service."""

    async def execute(self, ctx: NodeContext) -> NodeResult:
        from app.services.dlp_service import DLPService  # noqa: PLC0415

        config = ctx.config
        action_on_violation: str = (
            config.get("actionOnViolation") or config.get("action_on_violation") or "flag"
        )
        # Which input key to scan — defaults to scanning ALL upstream outputs as JSON
        import json  # noqa: PLC0415

        content_to_scan = json.dumps(ctx.inputs) if ctx.inputs else ""
        # Allow explicit override
        if config.get("inputKey"):
            input_key = config["inputKey"]
            content_to_scan = str(ctx.inputs.get(input_key, ""))

        tenant_id = ctx.tenant_id or "default"

        try:
            scan_result = DLPService.scan_content(
                tenant_id=tenant_id,
                content=content_to_scan,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("dlpScanNode.scan_error", exc_info=True)
            return NodeResult(
                status="failed",
                error=f"DLP scan failed: {type(exc).__name__}: {exc}",
            )

        risk_level = str(scan_result.risk_level.value if hasattr(scan_result.risk_level, "value") else scan_result.risk_level)
        action = str(scan_result.action.value if hasattr(scan_result.action, "value") else scan_result.action)
        finding_count = len(scan_result.findings)

        logger.info(
            "dlpScanNode.scanned",
            extra={
                "step_id": ctx.step_id,
                "risk_level": risk_level,
                "finding_count": finding_count,
            },
        )

        # Block if high/critical severity and action_on_violation is "block"
        high_severity = risk_level in ("high", "critical")
        if high_severity and action_on_violation == "block":
            return NodeResult(
                status="failed",
                error=f"DLP violation: {risk_level} risk detected ({finding_count} findings). Workflow aborted.",
                output={"risk_level": risk_level, "finding_count": finding_count, "action": "blocked"},
            )

        return NodeResult(
            status="completed",
            output={
                "risk_level": risk_level,
                "finding_count": finding_count,
                "action": action,
                "passed": not high_severity or action_on_violation != "block",
            },
        )
