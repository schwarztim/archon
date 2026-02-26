"""Enterprise wizard routes — Natural Language → Agent pipeline.

Endpoints:
  POST /wizard/describe  — NLP analysis of a description
  POST /wizard/plan      — structured build plan
  POST /wizard/build     — generate agent definition + source
  POST /wizard/validate  — security scan & compliance check
  POST /wizard/refine    — iterative refinement (max 3)
  POST /wizard/full      — all-in-one pipeline

All routes are authenticated, RBAC-checked, tenant-scoped, and audit-logged.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status

from app.interfaces.models.enterprise import AuthenticatedUser
from app.middleware.rbac import require_permission
from app.models.wizard import (
    GeneratedAgent,
    NLAnalysis,
    NLBuildPlan,
    NLBuildRequest,
    RefineRequest,
    ValidationResult,
)
from app.services.wizard_service import (
    NLWizardService,
    WizardRequest,
    generate_agent_graph,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/wizard", tags=["wizard"])

_wizard = NLWizardService()


# ── Helpers ──────────────────────────────────────────────────────────


def _meta(*, request_id: str | None = None, **extra: Any) -> dict[str, Any]:
    """Build standard envelope meta block."""
    return {
        "request_id": request_id or str(uuid4()),
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        **extra,
    }


# ── Routes ───────────────────────────────────────────────────────────


@router.post("/describe", status_code=status.HTTP_200_OK)
async def describe(
    body: NLBuildRequest,
    user: AuthenticatedUser = Depends(require_permission("agents", "create")),
) -> dict[str, Any]:
    """Accept a natural-language description and return NLP analysis."""
    request_id = str(uuid4())
    try:
        analysis = await _wizard.describe(user.tenant_id, user, body.description)
    except Exception as exc:
        logger.exception("Wizard describe failed", extra={"tenant_id": user.tenant_id})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "errors": [{"code": "WIZARD_DESCRIBE_FAILED", "message": str(exc)}],
                "meta": _meta(request_id=request_id),
            },
        ) from exc

    return {
        "data": analysis.model_dump(mode="json"),
        "meta": _meta(request_id=request_id),
    }


@router.post("/plan", status_code=status.HTTP_200_OK)
async def plan(
    body: NLAnalysis,
    user: AuthenticatedUser = Depends(require_permission("agents", "create")),
) -> dict[str, Any]:
    """Accept an NLAnalysis and return a structured build plan."""
    request_id = str(uuid4())
    try:
        build_plan = await _wizard.plan(user.tenant_id, user, body)
    except Exception as exc:
        logger.exception("Wizard plan failed", extra={"tenant_id": user.tenant_id})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "errors": [{"code": "WIZARD_PLAN_FAILED", "message": str(exc)}],
                "meta": _meta(request_id=request_id),
            },
        ) from exc

    return {
        "data": build_plan.model_dump(mode="json"),
        "meta": _meta(request_id=request_id),
    }


@router.post("/build", status_code=status.HTTP_201_CREATED)
async def build(
    body: NLBuildPlan,
    user: AuthenticatedUser = Depends(require_permission("agents", "create")),
) -> dict[str, Any]:
    """Accept a build plan and return a generated agent definition."""
    request_id = str(uuid4())
    try:
        agent = await _wizard.build(user.tenant_id, user, body)
    except Exception as exc:
        logger.exception("Wizard build failed", extra={"tenant_id": user.tenant_id})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "errors": [{"code": "WIZARD_BUILD_FAILED", "message": str(exc)}],
                "meta": _meta(request_id=request_id),
            },
        ) from exc

    return {"data": agent.model_dump(mode="json"), "meta": _meta(request_id=request_id)}


@router.post("/validate", status_code=status.HTTP_200_OK)
async def validate(
    body: GeneratedAgent,
    user: AuthenticatedUser = Depends(require_permission("agents", "create")),
) -> dict[str, Any]:
    """Accept a generated agent and return validation results."""
    request_id = str(uuid4())
    try:
        result = await _wizard.validate(user.tenant_id, user, body)
    except Exception as exc:
        logger.exception("Wizard validate failed", extra={"tenant_id": user.tenant_id})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "errors": [{"code": "WIZARD_VALIDATE_FAILED", "message": str(exc)}],
                "meta": _meta(request_id=request_id),
            },
        ) from exc

    return {
        "data": result.model_dump(mode="json"),
        "meta": _meta(request_id=request_id),
    }


@router.post("/refine", status_code=status.HTTP_200_OK)
async def refine(
    body: RefineRequest,
    user: AuthenticatedUser = Depends(require_permission("agents", "create")),
) -> dict[str, Any]:
    """Iteratively refine a generated agent based on user feedback."""
    request_id = str(uuid4())
    try:
        refined = await _wizard.refine(
            user.tenant_id,
            user,
            body.agent,
            body.feedback,
            body.iteration,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "errors": [{"code": "WIZARD_REFINE_LIMIT", "message": str(exc)}],
                "meta": _meta(request_id=request_id),
            },
        ) from exc
    except Exception as exc:
        logger.exception("Wizard refine failed", extra={"tenant_id": user.tenant_id})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "errors": [{"code": "WIZARD_REFINE_FAILED", "message": str(exc)}],
                "meta": _meta(request_id=request_id),
            },
        ) from exc

    return {
        "data": refined.model_dump(mode="json"),
        "meta": _meta(request_id=request_id),
    }


@router.post("/full", status_code=status.HTTP_201_CREATED)
async def full_pipeline(
    body: NLBuildRequest,
    user: AuthenticatedUser = Depends(require_permission("agents", "create")),
) -> dict[str, Any]:
    """Run the complete Describe → Plan → Build → Validate pipeline."""
    request_id = str(uuid4())
    try:
        agent, validation = await _wizard.full_pipeline(
            user.tenant_id,
            user,
            body.description,
        )
    except Exception as exc:
        logger.exception(
            "Wizard full pipeline failed", extra={"tenant_id": user.tenant_id}
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "errors": [{"code": "WIZARD_PIPELINE_FAILED", "message": str(exc)}],
                "meta": _meta(request_id=request_id),
            },
        ) from exc

    return {
        "data": {
            "agent": agent.model_dump(mode="json"),
            "validation": validation.model_dump(mode="json"),
        },
        "meta": _meta(request_id=request_id),
    }


@router.post("/generate", status_code=status.HTTP_201_CREATED)
async def generate(
    body: WizardRequest,
) -> dict[str, Any]:
    """Convert a natural-language description into an agent graph definition."""
    request_id = str(uuid4())
    try:
        result = await generate_agent_graph(body.description)
    except Exception as exc:
        logger.exception("Wizard generate failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "errors": [{"code": "WIZARD_GENERATE_FAILED", "message": str(exc)}],
                "meta": _meta(request_id=request_id),
            },
        ) from exc

    return {
        "data": result.model_dump(mode="json"),
        "meta": _meta(request_id=request_id),
    }
