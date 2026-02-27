"""API routes for MCP Server Container management (ToolHive pattern).

Prefix: /api/v1/mcp/containers
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from app.database import get_session
from app.services.mcp_container_service import MCPContainerService

router = APIRouter(prefix="/mcp/containers", tags=["mcp-containers"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class ContainerCreate(BaseModel):
    """Payload for creating an MCP server container."""

    name: str
    image: str
    tag: str = "latest"
    port_mappings: dict | None = None
    env_vars: dict | None = None
    volumes: dict | None = None
    health_check_url: str | None = None
    labels: dict | None = None
    resource_limits: dict | None = None
    restart_policy: str = "unless-stopped"
    network: str | None = None
    tenant_id: str | None = None
    auto_start: bool = False


class ContainerResponse(BaseModel):
    """Serialised MCPServerContainer for API responses."""

    id: str
    name: str
    image: str
    tag: str
    status: str
    container_id: str | None
    port_mappings: dict | None
    env_vars: dict | None
    volumes: dict | None
    health_check_url: str | None
    labels: dict | None
    resource_limits: dict | None
    restart_policy: str
    network: str
    tenant_id: str | None
    created_at: datetime
    updated_at: datetime
    last_health_check: datetime | None
    health_status: str | None
    error_message: str | None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _meta(*, request_id: str | None = None, **extra: Any) -> dict[str, Any]:
    """Build standard response envelope meta block."""
    return {
        "request_id": request_id or str(uuid4()),
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        **extra,
    }


def _not_found(container_id: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"Container {container_id} not found")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/", status_code=201)
async def create_container(
    body: ContainerCreate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Create an MCP server container (pull image + create + optionally start)."""
    try:
        record = await MCPContainerService.create_container(
            session,
            name=body.name,
            image=body.image,
            tag=body.tag,
            port_mappings=body.port_mappings,
            env_vars=body.env_vars,
            volumes=body.volumes,
            health_check_url=body.health_check_url,
            labels=body.labels,
            resource_limits=body.resource_limits,
            restart_policy=body.restart_policy,
            network=body.network,
            tenant_id=body.tenant_id,
            auto_start=body.auto_start,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {
        "data": ContainerResponse.model_validate(record).model_dump(mode="json"),
        "meta": _meta(),
    }


@router.get("/")
async def list_containers(
    tenant_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List MCP server containers with optional filtering."""
    containers, total = await MCPContainerService.list_containers(
        session,
        tenant_id=tenant_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    return {
        "data": [
            ContainerResponse.model_validate(c).model_dump(mode="json")
            for c in containers
        ],
        "meta": _meta(pagination={"total": total, "limit": limit, "offset": offset}),
    }


@router.get("/{container_id}")
async def get_container(
    container_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get details for a single MCP server container."""
    record = await MCPContainerService.get_container(session, container_id)
    if record is None:
        raise _not_found(container_id)
    return {
        "data": ContainerResponse.model_validate(record).model_dump(mode="json"),
        "meta": _meta(),
    }


@router.post("/{container_id}/start")
async def start_container(
    container_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Start a stopped or created MCP server container."""
    try:
        record = await MCPContainerService.start_container(session, container_id)
    except ValueError:
        raise _not_found(container_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {
        "data": ContainerResponse.model_validate(record).model_dump(mode="json"),
        "meta": _meta(),
    }


@router.post("/{container_id}/stop")
async def stop_container(
    container_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Stop a running MCP server container."""
    try:
        record = await MCPContainerService.stop_container(session, container_id)
    except ValueError:
        raise _not_found(container_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {
        "data": ContainerResponse.model_validate(record).model_dump(mode="json"),
        "meta": _meta(),
    }


@router.post("/{container_id}/restart")
async def restart_container(
    container_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Restart an MCP server container."""
    try:
        record = await MCPContainerService.restart_container(session, container_id)
    except ValueError:
        raise _not_found(container_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {
        "data": ContainerResponse.model_validate(record).model_dump(mode="json"),
        "meta": _meta(),
    }


@router.delete("/{container_id}", status_code=204, response_class=Response)
async def remove_container(
    container_id: str,
    force: bool = Query(default=False),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Remove an MCP server container (stops it first if running)."""
    try:
        await MCPContainerService.remove_container(session, container_id, force=force)
    except ValueError:
        raise _not_found(container_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return Response(status_code=204)


@router.get("/{container_id}/logs")
async def get_container_logs(
    container_id: str,
    tail: int = Query(default=100, ge=1, le=10000),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get the last N log lines from an MCP server container."""
    try:
        lines = await MCPContainerService.get_logs(session, container_id, tail=tail)
    except ValueError:
        raise _not_found(container_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {
        "data": {"container_id": container_id, "lines": lines, "tail": tail},
        "meta": _meta(),
    }


@router.get("/{container_id}/health")
async def check_container_health(
    container_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Force an immediate health check on an MCP server container."""
    try:
        record = await MCPContainerService.check_health(session, container_id)
    except ValueError:
        raise _not_found(container_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {
        "data": ContainerResponse.model_validate(record).model_dump(mode="json"),
        "meta": _meta(),
    }
