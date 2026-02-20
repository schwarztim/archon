"""Sandbox execution endpoints — enterprise edition."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.interfaces.models.enterprise import AuthenticatedUser
from app.middleware.auth import require_auth
from app.middleware.rbac import require_permission
from app.secrets.manager import get_secrets_manager
from app.services.sandbox_service import (
    SandboxExecuteRequest,
    SandboxResourceLimits,
    SandboxService,
    sandbox_service,
)
from starlette.responses import Response
from app.models.sandbox import (
    ArenaConfig,
    ArenaTestCase,
    SandboxConfig,
)

router = APIRouter(tags=["sandbox"])


# ── Helpers ──────────────────────────────────────────────────────────


def _meta(*, request_id: str | None = None, **extra: Any) -> dict[str, Any]:
    """Build standard envelope meta block."""
    return {
        "request_id": request_id or str(uuid4()),
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        **extra,
    }


# ── Request schemas ──────────────────────────────────────────────────


class SessionCreateRequest(BaseModel):
    """Payload to create a sandbox session."""

    resource_limits: SandboxResourceLimits = Field(default_factory=SandboxResourceLimits)


class SandboxCreateRequest(BaseModel):
    """Payload for creating an enterprise sandbox."""

    config: SandboxConfig = Field(default_factory=SandboxConfig)


class SandboxExecuteInRequest(BaseModel):
    """Payload for executing an agent inside a sandbox."""

    agent_id: UUID
    input_data: dict[str, Any] = Field(default_factory=dict)


class ArenaRequest(BaseModel):
    """Payload for an arena A/B comparison."""

    config: ArenaConfig


class BenchmarkRequest(BaseModel):
    """Payload for running a benchmark suite."""

    agent_id: UUID
    benchmark_set_id: UUID


# ── Legacy routes (backward compatible) ─────────────────────────────


@router.post("/sandbox/execute", status_code=200)
async def execute_sandbox(body: SandboxExecuteRequest) -> dict[str, Any]:
    """Run code in an isolated sandbox with resource limits."""
    result = await sandbox_service.execute(
        code=body.code,
        resource_limits=body.resource_limits,
        session_id=body.session_id,
    )
    return {
        "data": result.model_dump(mode="json"),
        "meta": _meta(),
    }


@router.post("/sandbox/sessions", status_code=201)
async def create_session(body: SessionCreateRequest) -> dict[str, Any]:
    """Create a new sandbox session."""
    session = sandbox_service.create_session(resource_limits=body.resource_limits)
    return {
        "data": session.model_dump(mode="json"),
        "meta": _meta(),
    }


@router.get("/sandbox/sessions")
async def list_sessions(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """List sandbox sessions with pagination."""
    sessions, total = sandbox_service.list_sessions(limit=limit, offset=offset)
    return {
        "data": [s.model_dump(mode="json") for s in sessions],
        "meta": _meta(
            pagination={"total": total, "limit": limit, "offset": offset},
        ),
    }


@router.get("/sandbox/sessions/{session_id}")
async def get_session(session_id: UUID) -> dict[str, Any]:
    """Get a single sandbox session by ID."""
    session = sandbox_service.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Sandbox session not found")
    return {
        "data": session.model_dump(mode="json"),
        "meta": _meta(),
    }


@router.delete("/sandbox/sessions/{session_id}", status_code=204, response_class=Response)
async def destroy_session(session_id: UUID) -> Response:
    """Destroy a sandbox session."""
    destroyed = sandbox_service.destroy_session(session_id)
    if not destroyed:
        raise HTTPException(status_code=404, detail="Sandbox session not found")
    return Response(status_code=204)


# ── Enterprise sandbox routes ────────────────────────────────────────


@router.post("/api/v1/sandbox", status_code=status.HTTP_201_CREATED)
async def create_sandbox(
    body: SandboxCreateRequest,
    user: AuthenticatedUser = Depends(require_permission("sandbox", "create")),
) -> dict[str, Any]:
    """Create an isolated sandbox environment with resource limits and TTL."""
    sandbox = await sandbox_service.create_sandbox(
        tenant_id=user.tenant_id,
        user=user,
        config=body.config,
    )
    return {
        "data": sandbox.model_dump(mode="json"),
        "meta": _meta(),
    }


@router.post(
    "/api/v1/sandbox/{sandbox_id}/execute",
    status_code=status.HTTP_200_OK,
)
async def execute_in_sandbox(
    sandbox_id: UUID,
    body: SandboxExecuteInRequest,
    user: AuthenticatedUser = Depends(require_permission("sandbox", "execute")),
) -> dict[str, Any]:
    """Execute an agent inside an existing sandbox with dynamic credentials."""
    try:
        secrets = await get_secrets_manager()
    except Exception:
        secrets = None

    try:
        execution = await sandbox_service.execute_in_sandbox(
            sandbox_id=sandbox_id,
            tenant_id=user.tenant_id,
            agent_id=body.agent_id,
            input_data=body.input_data,
            user=user,
            secrets_manager=secrets,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return {
        "data": execution.model_dump(mode="json"),
        "meta": _meta(),
    }


@router.get("/api/v1/sandbox/{sandbox_id}")
async def get_sandbox(
    sandbox_id: UUID,
    user: AuthenticatedUser = Depends(require_auth),
) -> dict[str, Any]:
    """Get sandbox details scoped to the authenticated user's tenant."""
    sandbox = await sandbox_service.get_sandbox(sandbox_id, user.tenant_id)
    if sandbox is None:
        raise HTTPException(status_code=404, detail="Sandbox not found")
    return {
        "data": sandbox.model_dump(mode="json"),
        "meta": _meta(),
    }


@router.get("/api/v1/sandbox")
async def list_sandboxes(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    sandbox_status: str | None = Query(default=None, alias="status"),
    user: AuthenticatedUser = Depends(require_auth),
) -> dict[str, Any]:
    """List sandboxes for the authenticated user's tenant."""
    filters = {}
    if sandbox_status:
        filters["status"] = sandbox_status

    sandboxes, total = await sandbox_service.list_sandboxes(
        tenant_id=user.tenant_id,
        filters=filters if filters else None,
        limit=limit,
        offset=offset,
    )
    return {
        "data": [s.model_dump(mode="json") for s in sandboxes],
        "meta": _meta(
            pagination={"total": total, "limit": limit, "offset": offset},
        ),
    }


@router.delete("/api/v1/sandbox/{sandbox_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_sandbox(
    sandbox_id: UUID,
    user: AuthenticatedUser = Depends(require_permission("sandbox", "delete")),
) -> None:
    """Destroy a sandbox and revoke its dynamic credentials."""
    try:
        secrets = await get_secrets_manager()
    except Exception:
        secrets = None

    destroyed = await sandbox_service.destroy_sandbox(
        sandbox_id=sandbox_id,
        tenant_id=user.tenant_id,
        user=user,
        secrets_manager=secrets,
    )
    if not destroyed:
        raise HTTPException(status_code=404, detail="Sandbox not found")
    return None


@router.post("/api/v1/sandbox/arena", status_code=status.HTTP_200_OK)
async def arena_compare(
    body: ArenaRequest,
    user: AuthenticatedUser = Depends(require_permission("sandbox", "execute")),
) -> dict[str, Any]:
    """Run an arena A/B comparison of multiple agent versions."""
    test_case_dicts = [tc.model_dump() for tc in body.config.test_cases]

    result = await sandbox_service.arena_compare(
        tenant_id=user.tenant_id,
        user=user,
        agent_ids=body.config.agent_ids,
        test_cases=test_case_dicts,
        config=body.config,
    )
    return {
        "data": result.model_dump(mode="json"),
        "meta": _meta(),
    }


@router.post("/api/v1/sandbox/benchmark", status_code=status.HTTP_200_OK)
async def run_benchmark(
    body: BenchmarkRequest,
    user: AuthenticatedUser = Depends(require_permission("sandbox", "execute")),
) -> dict[str, Any]:
    """Run an agent against a standardised benchmark set."""
    result = await sandbox_service.run_benchmark(
        tenant_id=user.tenant_id,
        user=user,
        agent_id=body.agent_id,
        benchmark_set_id=body.benchmark_set_id,
    )
    return {
        "data": result.model_dump(mode="json"),
        "meta": _meta(),
    }
