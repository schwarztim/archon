"""QA Trigger Service — submits QA runs to Azure Logic Apps and handles callbacks."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config import settings
from app.logging_config import get_logger
from app.models.qa import QAWorkflowRequest

logger = get_logger(__name__)


class QATriggerService:
    """Service for triggering and tracking QA workflow requests via Azure Logic Apps."""

    # ── Trigger ──────────────────────────────────────────────────────────────

    @staticmethod
    async def trigger_qa(
        session: AsyncSession,
        *,
        workflow_id: str | None = None,
        workflow_run_id: str | None = None,
        payload: dict[str, Any] | None = None,
        trigger_source: str = "manual",
        tenant_id: str | None = None,
    ) -> QAWorkflowRequest:
        """Create a QA request record and POST it to Azure Logic Apps.

        If the Logic Apps endpoint is not configured, the request is saved
        with status ``pending`` so it can be processed later.

        Args:
            session: Async database session.
            workflow_id: Optional workflow to associate with this QA run.
            workflow_run_id: Optional workflow run that triggered QA.
            payload: Arbitrary QA payload forwarded to Logic Apps.
            trigger_source: Who/what triggered this (manual, workflow_completion, api).
            tenant_id: Tenant scope.

        Returns:
            Persisted QAWorkflowRequest record.
        """
        now = datetime.utcnow()
        request = QAWorkflowRequest(
            workflow_id=workflow_id,
            workflow_run_id=workflow_run_id,
            trigger_source=trigger_source,
            status="pending",
            request_payload=payload or {},
            tenant_id=tenant_id,
            created_at=now,
            updated_at=now,
        )
        session.add(request)
        await session.commit()
        await session.refresh(request)

        endpoint = settings.LOGIC_APPS_QA_ENDPOINT
        if not endpoint:
            logger.warning(
                "qa_trigger_endpoint_not_configured",
                request_id=request.id,
            )
            return request

        # POST to Logic Apps
        try:
            async with httpx.AsyncClient(timeout=settings.QA_TRIGGER_TIMEOUT) as client:
                body: dict[str, Any] = {
                    "archon_request_id": request.id,
                    "workflow_id": workflow_id,
                    "workflow_run_id": workflow_run_id,
                    "trigger_source": trigger_source,
                    "tenant_id": tenant_id,
                    **(payload or {}),
                }
                resp = await client.post(endpoint, json=body)
                resp.raise_for_status()

                response_data: dict[str, Any] = {}
                try:
                    response_data = resp.json()
                except Exception:
                    response_data = {"raw": resp.text}

                logic_apps_run_id = (
                    response_data.get("run_id")
                    or resp.headers.get("x-ms-workflow-run-id")
                    or resp.headers.get("location", "").split("/")[-1]
                    or None
                )

                request.status = "submitted"
                request.logic_apps_run_id = logic_apps_run_id
                request.response_payload = response_data
                request.updated_at = datetime.utcnow()
                session.add(request)
                await session.commit()
                await session.refresh(request)

                logger.info(
                    "qa_trigger_submitted",
                    request_id=request.id,
                    logic_apps_run_id=logic_apps_run_id,
                )

        except httpx.HTTPStatusError as exc:
            logger.error(
                "qa_trigger_http_error",
                request_id=request.id,
                status_code=exc.response.status_code,
                detail=exc.response.text,
            )
            request.status = "failed"
            request.error_message = (
                f"HTTP {exc.response.status_code}: {exc.response.text}"
            )
            request.updated_at = datetime.utcnow()
            session.add(request)
            await session.commit()
            await session.refresh(request)

        except httpx.RequestError as exc:
            logger.error(
                "qa_trigger_request_error",
                request_id=request.id,
                error=str(exc),
            )
            request.status = "failed"
            request.error_message = f"Request error: {exc}"
            request.updated_at = datetime.utcnow()
            session.add(request)
            await session.commit()
            await session.refresh(request)

        return request

    # ── Callback ─────────────────────────────────────────────────────────────

    @staticmethod
    async def handle_callback(
        session: AsyncSession,
        *,
        logic_apps_run_id: str,
        result: dict[str, Any],
    ) -> QAWorkflowRequest | None:
        """Process a callback from Logic Apps after QA completes.

        Args:
            session: Async database session.
            logic_apps_run_id: The Logic Apps run ID to correlate.
            result: Callback result payload from Logic Apps.

        Returns:
            Updated QAWorkflowRequest, or None if no matching record found.
        """
        stmt = select(QAWorkflowRequest).where(
            QAWorkflowRequest.logic_apps_run_id == logic_apps_run_id
        )
        db_result = await session.exec(stmt)
        request = db_result.first()

        if request is None:
            logger.warning(
                "qa_callback_no_match",
                logic_apps_run_id=logic_apps_run_id,
            )
            return None

        now = datetime.utcnow()
        outcome_status = result.get("status", "completed")
        # Normalise to known statuses
        if outcome_status not in ("completed", "failed", "in_progress"):
            outcome_status = "completed"

        request.status = outcome_status
        request.callback_received = True
        request.response_payload = result
        request.updated_at = now
        if outcome_status in ("completed", "failed"):
            request.completed_at = now
        if outcome_status == "failed":
            request.error_message = result.get("error_message") or result.get("error")

        session.add(request)
        await session.commit()
        await session.refresh(request)

        logger.info(
            "qa_callback_processed",
            request_id=request.id,
            logic_apps_run_id=logic_apps_run_id,
            status=request.status,
        )
        return request

    # ── Queries ───────────────────────────────────────────────────────────────

    @staticmethod
    async def list_requests(
        session: AsyncSession,
        *,
        tenant_id: str | None = None,
        status_filter: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[QAWorkflowRequest], int]:
        """Query QA requests with optional tenant and status filtering.

        Returns:
            Tuple of (page items, total count).
        """
        stmt = select(QAWorkflowRequest)
        if tenant_id is not None:
            stmt = stmt.where(QAWorkflowRequest.tenant_id == tenant_id)
        if status_filter is not None:
            stmt = stmt.where(QAWorkflowRequest.status == status_filter)

        count_result = await session.exec(stmt)
        all_items = list(count_result.all())
        total = len(all_items)
        page = all_items[offset : offset + limit]
        return page, total

    @staticmethod
    async def get_request(
        session: AsyncSession,
        request_id: str,
    ) -> QAWorkflowRequest | None:
        """Fetch a single QA request by ID."""
        return await session.get(QAWorkflowRequest, request_id)


__all__ = ["QATriggerService"]
