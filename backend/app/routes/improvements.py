"""Improvement Engine endpoints.

Provides gap analysis, proposal management, and a dashboard summary.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.database import get_session
from app.logging_config import get_logger
from app.models.improvement import ImprovementGap, ImprovementProposal
from app.services.improvement_engine import ImprovementEngineService

router = APIRouter(prefix="/improvements", tags=["improvements"])
logger = get_logger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _meta(**extra: Any) -> dict[str, Any]:
    return {
        "request_id": str(uuid4()),
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        **extra,
    }


def _gap_to_dict(gap: ImprovementGap) -> dict[str, Any]:
    return {
        "id": gap.id,
        "category": gap.category,
        "source": gap.source,
        "severity": gap.severity,
        "title": gap.title,
        "description": gap.description,
        "evidence": gap.evidence,
        "affected_resources": gap.affected_resources,
        "tenant_id": gap.tenant_id,
        "created_at": gap.created_at.isoformat() if gap.created_at else None,
        "resolved": gap.resolved,
        "resolved_at": gap.resolved_at.isoformat() if gap.resolved_at else None,
        "resolved_by_proposal_id": gap.resolved_by_proposal_id,
    }


def _proposal_to_dict(proposal: ImprovementProposal) -> dict[str, Any]:
    return {
        "id": proposal.id,
        "gap_id": proposal.gap_id,
        "title": proposal.title,
        "description": proposal.description,
        "proposed_changes": proposal.proposed_changes,
        "impact_analysis": proposal.impact_analysis,
        "confidence_score": proposal.confidence_score,
        "status": proposal.status,
        "analysis_model": proposal.analysis_model,
        "tenant_id": proposal.tenant_id,
        "created_at": proposal.created_at.isoformat() if proposal.created_at else None,
        "updated_at": proposal.updated_at.isoformat() if proposal.updated_at else None,
        "approved_by": proposal.approved_by,
        "approved_at": proposal.approved_at.isoformat()
        if proposal.approved_at
        else None,
    }


# ── Request schemas ────────────────────────────────────────────────────────────


class AnalyzeTriggerRequest(BaseModel):
    tenant_id: str | None = None


class ProposalStatusUpdate(BaseModel):
    status: str
    approved_by: str | None = None


# ── Routes ─────────────────────────────────────────────────────────────────────


@router.post("/analyze", status_code=201)
async def trigger_analysis(
    body: AnalyzeTriggerRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Manually trigger the improvement analysis cycle.

    Collects gaps from governance, health, workflows, and security scans,
    then calls Azure OpenAI to generate improvement proposals.
    """
    from app.config import settings

    if not settings.IMPROVEMENT_ENGINE_ENABLED:
        raise HTTPException(
            status_code=503,
            detail="Improvement engine is disabled",
        )

    summary = await ImprovementEngineService.run_analysis_cycle(
        session, tenant_id=body.tenant_id
    )
    return {"data": summary, "meta": _meta()}


@router.get("/gaps")
async def list_gaps(
    tenant_id: str | None = Query(default=None),
    category: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    resolved: bool | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List improvement gaps with optional filtering."""
    items, total = await ImprovementEngineService.list_gaps(
        session,
        tenant_id=tenant_id,
        category=category,
        severity=severity,
        resolved=resolved,
        limit=limit,
        offset=offset,
    )
    return {
        "data": [_gap_to_dict(g) for g in items],
        "meta": _meta(pagination={"total": total, "limit": limit, "offset": offset}),
    }


@router.get("/gaps/{gap_id}")
async def get_gap(
    gap_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get a single improvement gap by ID."""
    gap = await session.get(ImprovementGap, gap_id)
    if gap is None:
        raise HTTPException(status_code=404, detail="Gap not found")
    return {"data": _gap_to_dict(gap), "meta": _meta()}


@router.get("/proposals")
async def list_proposals(
    tenant_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    gap_id: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List improvement proposals with optional filtering."""
    items, total = await ImprovementEngineService.list_proposals(
        session,
        tenant_id=tenant_id,
        status=status,
        gap_id=gap_id,
        limit=limit,
        offset=offset,
    )
    return {
        "data": [_proposal_to_dict(p) for p in items],
        "meta": _meta(pagination={"total": total, "limit": limit, "offset": offset}),
    }


@router.get("/proposals/{proposal_id}")
async def get_proposal(
    proposal_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get a single improvement proposal by ID."""
    proposal = await session.get(ImprovementProposal, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return {"data": _proposal_to_dict(proposal), "meta": _meta()}


@router.put("/proposals/{proposal_id}")
async def update_proposal(
    proposal_id: str,
    body: ProposalStatusUpdate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Update a proposal's status (approve/reject/complete/implementing)."""
    try:
        proposal = await ImprovementEngineService.update_proposal_status(
            session,
            proposal_id,
            status=body.status,
            approved_by=body.approved_by,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return {"data": _proposal_to_dict(proposal), "meta": _meta()}


@router.get("/dashboard")
async def dashboard(
    tenant_id: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Return summary statistics for the improvements dashboard.

    Includes gap counts by category and proposal counts by status.
    """
    # Gaps by category
    gap_stmt = select(ImprovementGap)
    if tenant_id:
        gap_stmt = gap_stmt.where(ImprovementGap.tenant_id == tenant_id)
    gap_result = await session.exec(gap_stmt)
    all_gaps = list(gap_result.all())

    gaps_by_category: dict[str, int] = {}
    gaps_by_severity: dict[str, int] = {}
    for g in all_gaps:
        gaps_by_category[g.category] = gaps_by_category.get(g.category, 0) + 1
        gaps_by_severity[g.severity] = gaps_by_severity.get(g.severity, 0) + 1

    # Proposals by status
    prop_stmt = select(ImprovementProposal)
    if tenant_id:
        prop_stmt = prop_stmt.where(ImprovementProposal.tenant_id == tenant_id)
    prop_result = await session.exec(prop_stmt)
    all_proposals = list(prop_result.all())

    proposals_by_status: dict[str, int] = {}
    for p in all_proposals:
        proposals_by_status[p.status] = proposals_by_status.get(p.status, 0) + 1

    unresolved_gaps = sum(1 for g in all_gaps if not g.resolved)
    resolved_gaps = sum(1 for g in all_gaps if g.resolved)

    return {
        "data": {
            "gaps": {
                "total": len(all_gaps),
                "unresolved": unresolved_gaps,
                "resolved": resolved_gaps,
                "by_category": gaps_by_category,
                "by_severity": gaps_by_severity,
            },
            "proposals": {
                "total": len(all_proposals),
                "by_status": proposals_by_status,
            },
        },
        "meta": _meta(),
    }
