from __future__ import annotations

import httpx
import structlog

from app.config import get_settings

logger = structlog.get_logger(__name__)


async def trigger_qa_workflow(tool_id: str, result: dict, user_email: str) -> dict | None:
    """POST tool result to the Logic Apps QA workflow trigger URL."""
    settings = get_settings()
    if not settings.QA_WORKFLOW_TRIGGER_URL:
        logger.debug("qa_trigger.skipped", reason="no trigger URL configured")
        return None

    payload = {
        "tool_id": tool_id,
        "result": result,
        "user_email": user_email,
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(settings.QA_WORKFLOW_TRIGGER_URL, json=payload)
        resp.raise_for_status()
        logger.info("qa_trigger.sent", tool_id=tool_id)
        return resp.json()
