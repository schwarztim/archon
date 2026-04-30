"""Stream output node executor — write output to channel and persist as artifact.

Phase 3 / WS9 — Executor Workstream 4 (W4d).

Promoted from STUB to BETA: persists the streamed content as an artifact
via ``ctx.write_artifact`` (when the ActivityContext interface is
available) and emits to the WebSocket execution stream channel when the
``ExecutionStreamManager`` is reachable.

When the executor is invoked via the legacy ``NodeContext`` path (no
``write_artifact`` on the context), the content is still returned in the
output dict and a warning is logged.

Output shape::

    {
        "stream_format": str,       # "sse" | "json" (from config)
        "target_channel": str,
        "content": str,
        "artifact_ref": str | None, # artifact:// URI when persisted
        "char_count": int,
        "streamed": bool,           # True iff WebSocket delivery was attempted
    }

BETA caveats (tracked in feature-matrix.yaml):
  - WebSocket delivery is best-effort: if the channel manager is
    unavailable or the channel has no subscribers, the output is still
    persisted as an artifact and the step completes successfully.
  - SSE formatting wraps each content fragment in ``data: <text>\\n\\n``.
  - JSON formatting wraps the whole content in
    ``{"type": "output", "content": <text>}``.
  - The artifact write uses ``ctx.write_artifact`` when available
    (ActivityContext path) or falls back to a no-op log.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.services.node_executors import NodeContext, NodeExecutor, NodeResult, register

logger = logging.getLogger(__name__)

_DEFAULT_STREAM_FORMAT = "json"


def _collect_content(ctx: NodeContext) -> str:
    """Gather upstream outputs into a single string."""
    parts: list[str] = []
    for v in (ctx.inputs or {}).values():
        if isinstance(v, dict):
            text = (
                v.get("content")
                or v.get("output")
                or v.get("text")
                or v.get("result")
                or v
            )
            parts.append(str(text))
        else:
            parts.append(str(v))
    return "\n".join(parts)


def _format_content(content: str, stream_format: str) -> str:
    """Apply SSE or JSON envelope to *content*."""
    if stream_format == "sse":
        # Wrap each line as an SSE data event.
        lines = content.splitlines() or [""]
        return "".join(f"data: {line}\n\n" for line in lines)
    # Default: JSON envelope.
    return json.dumps({"type": "output", "content": content}, ensure_ascii=False)


async def _try_websocket_emit(
    target_channel: str,
    payload: str,
    stream_format: str,
) -> bool:
    """Attempt to push *payload* to the WebSocket channel manager.

    Returns True if delivery was attempted (channel manager reachable),
    False if the manager was not available (graceful degradation).
    """
    try:
        from app.services.websocket_manager import (  # noqa: PLC0415
            ExecutionStreamManager,
            get_stream_manager,
        )

        manager = get_stream_manager()
        if manager is None:
            return False
        await manager.emit(
            channel=target_channel,
            data={"format": stream_format, "payload": payload},
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "streamOutputNode.websocket_emit_skipped: %s",
            exc,
        )
        return False


async def _try_write_artifact(
    ctx: NodeContext,
    content: str,
    stream_format: str,
) -> str | None:
    """Persist content as an artifact if write_artifact is available.

    Returns the artifact URI or None if the context does not support it.
    """
    write_artifact = getattr(ctx, "write_artifact", None)
    if not callable(write_artifact):
        return None
    try:
        ref: str = await write_artifact(
            name="stream_output",
            payload=content,
            metadata={
                "node_type": "streamOutputNode",
                "stream_format": stream_format,
                "step_id": ctx.step_id,
            },
        )
        return ref
    except Exception as exc:  # noqa: BLE001
        logger.warning("streamOutputNode.artifact_write_failed: %s", exc)
        return None


@register("streamOutputNode")
class StreamOutputNodeExecutor(NodeExecutor):
    """Execute streamOutputNode: format content, push to channel, persist artifact."""

    async def execute(self, ctx: NodeContext) -> NodeResult:
        config = ctx.config
        stream_format: str = str(
            config.get("stream_format") or config.get("streamFormat") or _DEFAULT_STREAM_FORMAT
        ).lower()
        if stream_format not in ("sse", "json"):
            stream_format = _DEFAULT_STREAM_FORMAT

        target_channel: str = str(
            config.get("target_channel")
            or config.get("targetChannel")
            or f"run:{ctx.step_id}"
        )

        # Resolve content: prefer explicit config, then upstream inputs.
        raw_content: str = str(
            config.get("content") or _collect_content(ctx)
        )

        formatted = _format_content(raw_content, stream_format)

        # Best-effort WebSocket delivery.
        streamed = await _try_websocket_emit(target_channel, formatted, stream_format)

        # Persist artifact.
        artifact_ref = await _try_write_artifact(ctx, formatted, stream_format)
        if artifact_ref:
            logger.debug(
                "streamOutputNode.artifact_written",
                extra={"ref": artifact_ref, "step_id": ctx.step_id},
            )

        output: dict[str, Any] = {
            "stream_format": stream_format,
            "target_channel": target_channel,
            "content": raw_content,
            "artifact_ref": artifact_ref,
            "char_count": len(raw_content),
            "streamed": streamed,
        }

        return NodeResult(status="completed", output=output)
