"""Improvement Engine — collects gaps, analyses them with Azure OpenAI, generates proposals."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import httpx
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config import settings
from app.logging_config import get_logger
from app.models.improvement import ImprovementGap, ImprovementProposal

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Azure OpenAI helpers
# ---------------------------------------------------------------------------

_AZURE_API_VERSION = "2024-02-01"


async def _call_azure_openai(
    messages: list[dict[str, str]],
) -> str | None:
    """Send a chat-completion request to Azure OpenAI.

    Returns the assistant's reply text, or None on failure.
    Gracefully degrades if the endpoint or key is not configured.
    """
    endpoint = settings.AZURE_OPENAI_ENDPOINT
    api_key = settings.AZURE_OPENAI_API_KEY
    model = settings.AZURE_OPENAI_MODEL

    if not endpoint or not api_key:
        logger.warning("azure_openai_not_configured")
        return None

    url = (
        f"{endpoint.rstrip('/')}/openai/deployments/{model}"
        f"/chat/completions?api-version={_AZURE_API_VERSION}"
    )

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                url,
                headers={"api-key": api_key, "Content-Type": "application/json"},
                json={"messages": messages, "max_tokens": 2000, "temperature": 0.2},
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
    except httpx.HTTPStatusError as exc:
        logger.error(
            "azure_openai_http_error",
            status_code=exc.response.status_code,
            detail=exc.response.text[:200],
        )
    except httpx.RequestError as exc:
        logger.error("azure_openai_request_error", error=str(exc))
    except (KeyError, IndexError, ValueError) as exc:
        logger.error("azure_openai_parse_error", error=str(exc))
    return None


# ---------------------------------------------------------------------------
# ImprovementEngineService
# ---------------------------------------------------------------------------


class ImprovementEngineService:
    """Collect system gaps, analyse with Azure OpenAI, and generate proposals."""

    # ── Gap collection ───────────────────────────────────────────────────────

    @staticmethod
    async def collect_gaps(
        session: AsyncSession,
        tenant_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Collect raw gap data from governance, health, workflows and security scans.

        Returns a list of gap dicts (not yet persisted).
        """
        raw_gaps: list[dict[str, Any]] = []

        # 1. Governance compliance records
        try:
            from app.models.governance import ComplianceRecord

            stmt = select(ComplianceRecord).where(
                ComplianceRecord.status != "compliant"
            )
            result = await session.exec(stmt)
            for rec in result.all():
                raw_gaps.append(
                    {
                        "category": "compliance",
                        "source": "governance",
                        "severity": "high",
                        "title": f"Non-compliant record for policy {rec.policy_id}",
                        "description": (
                            f"Compliance check failed with status '{rec.status}'."
                        ),
                        "evidence": {
                            "details": rec.details,
                            "checked_at": str(rec.checked_at),
                        },
                        "affected_resources": {"policy_id": str(rec.policy_id)},
                        "tenant_id": tenant_id,
                    }
                )
        except Exception:
            logger.exception("gap_collection_compliance_error")

        # 2. Health checks
        try:
            from app.models.lifecycle import HealthCheck

            stmt = select(HealthCheck).where(HealthCheck.status == "unhealthy")
            result = await session.exec(stmt)
            for hc in result.all():
                raw_gaps.append(
                    {
                        "category": "health",
                        "source": "lifecycle",
                        "severity": "medium",
                        "title": f"Unhealthy deployment: {hc.deployment_id}",
                        "description": (
                            f"Health check reports unhealthy status. "
                            f"Last checked: {hc.checked_at}."
                        ),
                        "evidence": {
                            "details": hc.details,
                            "checked_at": str(hc.checked_at),
                        },
                        "affected_resources": {"deployment_id": str(hc.deployment_id)},
                        "tenant_id": tenant_id,
                    }
                )
        except Exception:
            logger.exception("gap_collection_health_error")

        # 3. Failed workflow runs
        try:
            from app.models.workflow import WorkflowRun

            stmt = select(WorkflowRun).where(WorkflowRun.status == "failed")
            result = await session.exec(stmt)
            for run in result.all():
                raw_gaps.append(
                    {
                        "category": "workflow",
                        "source": "workflow_engine",
                        "severity": "medium",
                        "title": f"Failed workflow run {run.id}",
                        "description": (
                            f"Workflow run failed for workflow {run.workflow_id}. "
                            f"Error: {getattr(run, 'error', 'unknown')}."
                        ),
                        "evidence": {
                            "run_id": str(run.id),
                            "trigger_type": run.trigger_type,
                            "started_at": str(run.started_at),
                        },
                        "affected_resources": {"workflow_id": str(run.workflow_id)},
                        "tenant_id": tenant_id,
                    }
                )
        except Exception:
            logger.exception("gap_collection_workflow_error")

        # 4. Security scan results (red team / vulnerability findings)
        try:
            from app.models.redteam import VulnerabilityFinding

            stmt = select(VulnerabilityFinding).where(
                VulnerabilityFinding.status != "resolved"
            )
            result = await session.exec(stmt)
            for finding in result.all():
                raw_gaps.append(
                    {
                        "category": "security",
                        "source": "redteam",
                        "severity": getattr(finding, "severity", "medium"),
                        "title": f"Unresolved vulnerability: {finding.title}",
                        "description": finding.description,
                        "evidence": {
                            "scan_id": str(getattr(finding, "scan_id", "")),
                            "attack_vector": getattr(finding, "attack_vector", ""),
                        },
                        "affected_resources": {
                            "finding_id": str(finding.id),
                        },
                        "tenant_id": tenant_id,
                    }
                )
        except Exception:
            logger.exception("gap_collection_security_error")

        logger.info("gap_collection_complete", count=len(raw_gaps))
        return raw_gaps

    # ── LLM analysis ─────────────────────────────────────────────────────────

    @staticmethod
    async def analyze_gaps(
        gaps: list[dict[str, Any]],
    ) -> list[dict[str, Any]] | None:
        """Send collected gaps to Azure OpenAI for structured analysis.

        Returns a list of proposal dicts, or None if the LLM call failed.
        """
        if not gaps:
            return []

        gap_summary = json.dumps(
            [
                {
                    "id": i,
                    "category": g["category"],
                    "severity": g["severity"],
                    "title": g["title"],
                    "description": g["description"],
                }
                for i, g in enumerate(gaps)
            ],
            indent=2,
        )

        system_prompt = (
            "You are an AI platform improvement advisor. Given a list of detected gaps "
            "in an AI orchestration platform, produce structured improvement proposals. "
            "Return a JSON array where each element has: "
            '{"gap_index": <int>, "title": <str>, "description": <str>, '
            '"proposed_changes": {"steps": [...]}, "impact_analysis": {"risk": <str>, '
            '"effort": <str>, "benefit": <str>}, "confidence_score": <float 0-1>}. '
            "Return ONLY the JSON array, no markdown, no explanation."
        )

        user_prompt = f"Gaps to analyse:\n{gap_summary}"

        reply = await _call_azure_openai(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
        )

        if reply is None:
            return None

        try:
            proposals = json.loads(reply)
            if not isinstance(proposals, list):
                logger.warning(
                    "azure_openai_unexpected_format", type=type(proposals).__name__
                )
                return None
            return proposals
        except json.JSONDecodeError as exc:
            logger.error(
                "azure_openai_json_decode_error", error=str(exc), reply=reply[:200]
            )
            return None

    # ── Proposal persistence ──────────────────────────────────────────────────

    @staticmethod
    async def generate_proposals(
        session: AsyncSession,
        gaps: list[dict[str, Any]],
        analysis: list[dict[str, Any]],
        tenant_id: str | None = None,
    ) -> list[ImprovementProposal]:
        """Persist ImprovementProposal records from LLM analysis output.

        Also persists the originating ImprovementGap records if not already saved.
        """
        # Persist gaps first and collect their IDs by original index
        gap_records: list[ImprovementGap] = []
        for gap_data in gaps:
            gap = ImprovementGap(
                category=gap_data.get("category", "performance"),
                source=gap_data.get("source", "system"),
                severity=gap_data.get("severity", "medium"),
                title=gap_data.get("title", ""),
                description=gap_data.get("description", ""),
                evidence=gap_data.get("evidence"),
                affected_resources=gap_data.get("affected_resources"),
                tenant_id=gap_data.get("tenant_id") or tenant_id,
            )
            session.add(gap)
            gap_records.append(gap)

        await session.flush()  # get IDs assigned

        # Persist proposals
        proposals: list[ImprovementProposal] = []
        model_name = settings.AZURE_OPENAI_MODEL

        for item in analysis:
            gap_index = item.get("gap_index")
            gap_id: str | None = None
            if gap_index is not None and 0 <= gap_index < len(gap_records):
                gap_id = gap_records[gap_index].id

            proposal = ImprovementProposal(
                gap_id=gap_id,
                title=item.get("title", "Untitled proposal"),
                description=item.get("description", ""),
                proposed_changes=item.get("proposed_changes"),
                impact_analysis=item.get("impact_analysis"),
                confidence_score=float(item.get("confidence_score", 0.0)),
                status="proposed",
                analysis_model=model_name,
                tenant_id=tenant_id,
            )
            session.add(proposal)
            proposals.append(proposal)

        await session.commit()
        for p in proposals:
            await session.refresh(p)

        logger.info(
            "proposals_generated",
            gap_count=len(gap_records),
            proposal_count=len(proposals),
        )
        return proposals

    # ── Full analysis cycle ───────────────────────────────────────────────────

    @staticmethod
    async def run_analysis_cycle(
        session: AsyncSession,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        """Run the full improvement analysis pipeline: collect → analyse → propose.

        Returns a summary dict with counts.
        """
        logger.info("improvement_analysis_cycle_start", tenant_id=tenant_id)

        gaps = await ImprovementEngineService.collect_gaps(session, tenant_id=tenant_id)
        if not gaps:
            logger.info("improvement_analysis_no_gaps")
            return {"gaps_found": 0, "proposals_created": 0, "status": "no_gaps"}

        analysis = await ImprovementEngineService.analyze_gaps(gaps)
        if analysis is None:
            # LLM unavailable — persist gaps without proposals
            analysis = []
            logger.warning("improvement_analysis_llm_unavailable")

        proposals = await ImprovementEngineService.generate_proposals(
            session,
            gaps=gaps,
            analysis=analysis,
            tenant_id=tenant_id,
        )

        summary = {
            "gaps_found": len(gaps),
            "proposals_created": len(proposals),
            "status": "completed",
        }
        logger.info("improvement_analysis_cycle_complete", **summary)
        return summary

    # ── Queries ───────────────────────────────────────────────────────────────

    @staticmethod
    async def list_gaps(
        session: AsyncSession,
        *,
        tenant_id: str | None = None,
        category: str | None = None,
        severity: str | None = None,
        resolved: bool | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[ImprovementGap], int]:
        """Query improvement gaps with filters. Returns (page, total)."""
        stmt = select(ImprovementGap)
        if tenant_id is not None:
            stmt = stmt.where(ImprovementGap.tenant_id == tenant_id)
        if category is not None:
            stmt = stmt.where(ImprovementGap.category == category)
        if severity is not None:
            stmt = stmt.where(ImprovementGap.severity == severity)
        if resolved is not None:
            stmt = stmt.where(ImprovementGap.resolved == resolved)

        result = await session.exec(stmt)
        all_items = list(result.all())
        total = len(all_items)
        page = all_items[offset : offset + limit]
        return page, total

    @staticmethod
    async def list_proposals(
        session: AsyncSession,
        *,
        tenant_id: str | None = None,
        status: str | None = None,
        gap_id: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[ImprovementProposal], int]:
        """Query improvement proposals with filters. Returns (page, total)."""
        stmt = select(ImprovementProposal)
        if tenant_id is not None:
            stmt = stmt.where(ImprovementProposal.tenant_id == tenant_id)
        if status is not None:
            stmt = stmt.where(ImprovementProposal.status == status)
        if gap_id is not None:
            stmt = stmt.where(ImprovementProposal.gap_id == gap_id)

        result = await session.exec(stmt)
        all_items = list(result.all())
        total = len(all_items)
        page = all_items[offset : offset + limit]
        return page, total

    @staticmethod
    async def update_proposal_status(
        session: AsyncSession,
        proposal_id: str,
        *,
        status: str,
        approved_by: str | None = None,
    ) -> ImprovementProposal | None:
        """Update the status of a proposal (approve/reject/complete/implementing).

        Args:
            session: Async database session.
            proposal_id: ID of the proposal to update.
            status: New status value.
            approved_by: User ID of the approver (for approved status).

        Returns:
            Updated proposal, or None if not found.
        """
        proposal = await session.get(ImprovementProposal, proposal_id)
        if proposal is None:
            return None

        valid_statuses = {
            "proposed",
            "approved",
            "implementing",
            "completed",
            "rejected",
        }
        if status not in valid_statuses:
            raise ValueError(
                f"Invalid status '{status}'. Must be one of {valid_statuses}."
            )

        now = datetime.utcnow()
        proposal.status = status
        proposal.updated_at = now
        if status == "approved":
            proposal.approved_by = approved_by
            proposal.approved_at = now

        # If a proposal is completed, mark its originating gap as resolved
        if status == "completed" and proposal.gap_id:
            gap = await session.get(ImprovementGap, proposal.gap_id)
            if gap and not gap.resolved:
                gap.resolved = True
                gap.resolved_at = now
                gap.resolved_by_proposal_id = proposal.id
                session.add(gap)

        session.add(proposal)
        await session.commit()
        await session.refresh(proposal)

        logger.info(
            "proposal_status_updated",
            proposal_id=proposal_id,
            status=status,
        )
        return proposal


__all__ = ["ImprovementEngineService"]
