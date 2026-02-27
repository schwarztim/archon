"""MCP Server Container management service — ToolHive pattern.

Manages Docker container lifecycle for MCP servers with graceful degradation
when Docker is unavailable (e.g. in test/CI environments).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config import settings
from app.logging_config import get_logger
from app.models.mcp_container import MCPServerContainer

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Docker availability check
# ---------------------------------------------------------------------------

_docker_available: bool | None = None  # None = not yet probed


async def _is_docker_available() -> bool:
    """Probe Docker availability once and cache the result."""
    global _docker_available
    if _docker_available is not None:
        return _docker_available

    try:
        import aiodocker  # type: ignore[import]

        docker = aiodocker.Docker(url=settings.DOCKER_HOST)
        await docker.version()
        await docker.close()
        _docker_available = True
        logger.info("docker_available", host=settings.DOCKER_HOST)
    except Exception as exc:
        _docker_available = False
        logger.warning("docker_unavailable", error=str(exc), host=settings.DOCKER_HOST)

    return _docker_available


def _reset_docker_probe() -> None:
    """Reset the cached Docker availability flag (useful in tests)."""
    global _docker_available
    _docker_available = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# MCPContainerService
# ---------------------------------------------------------------------------


class MCPContainerService:
    """Async service for MCP server container lifecycle management.

    All methods update the DB record first, then perform the Docker operation.
    When Docker is unavailable, mock responses are returned so the API still
    functions in development / test environments.
    """

    # ── Create ────────────────────────────────────────────────────────

    @staticmethod
    async def create_container(
        session: AsyncSession,
        *,
        name: str,
        image: str,
        tag: str = "latest",
        port_mappings: dict | None = None,
        env_vars: dict | None = None,
        volumes: dict | None = None,
        health_check_url: str | None = None,
        labels: dict | None = None,
        resource_limits: dict | None = None,
        restart_policy: str = "unless-stopped",
        network: str | None = None,
        tenant_id: str | None = None,
        auto_start: bool = False,
    ) -> MCPServerContainer:
        """Create a container record and optionally pull + start it."""
        record = MCPServerContainer(
            name=name,
            image=image,
            tag=tag,
            status="created",
            port_mappings=port_mappings,
            env_vars=env_vars,
            volumes=volumes,
            health_check_url=health_check_url,
            labels=labels,
            resource_limits=resource_limits,
            restart_policy=restart_policy,
            network=network or settings.MCP_CONTAINER_NETWORK,
            tenant_id=tenant_id,
        )
        session.add(record)
        await session.commit()
        await session.refresh(record)

        logger.info(
            "mcp_container_created",
            container_id=record.id,
            name=name,
            image=f"{image}:{tag}",
            tenant_id=tenant_id,
        )

        if auto_start:
            await MCPContainerService.pull_image(session, record.id)
            record = await MCPContainerService.start_container(session, record.id)

        return record

    # ── Pull ──────────────────────────────────────────────────────────

    @staticmethod
    async def pull_image(
        session: AsyncSession,
        container_id: str,
    ) -> MCPServerContainer:
        """Pull the Docker image for a container record."""
        record = await _get_or_404(session, container_id)
        record.status = "pulling"
        record.updated_at = _utcnow()
        session.add(record)
        await session.commit()
        await session.refresh(record)

        if not await _is_docker_available():
            logger.info("docker_unavailable_mock_pull", container_id=container_id)
            record.status = "created"
            record.updated_at = _utcnow()
            session.add(record)
            await session.commit()
            await session.refresh(record)
            return record

        try:
            import aiodocker  # type: ignore[import]

            docker = aiodocker.Docker(url=settings.DOCKER_HOST)
            try:
                image_ref = f"{record.image}:{record.tag}"
                await docker.images.pull(image_ref)
                record.status = "created"
                logger.info(
                    "mcp_image_pulled", container_id=container_id, image=image_ref
                )
            finally:
                await docker.close()
        except Exception as exc:
            record.status = "error"
            record.error_message = f"Image pull failed: {exc}"
            logger.error(
                "mcp_image_pull_failed",
                container_id=container_id,
                error=str(exc),
            )

        record.updated_at = _utcnow()
        session.add(record)
        await session.commit()
        await session.refresh(record)
        return record

    # ── Start ─────────────────────────────────────────────────────────

    @staticmethod
    async def start_container(
        session: AsyncSession,
        container_id: str,
    ) -> MCPServerContainer:
        """Start a container and record the Docker container ID."""
        record = await _get_or_404(session, container_id)

        if not await _is_docker_available():
            logger.info("docker_unavailable_mock_start", container_id=container_id)
            record.status = "running"
            record.container_id = f"mock-{container_id[:8]}"
            record.updated_at = _utcnow()
            session.add(record)
            await session.commit()
            await session.refresh(record)
            return record

        try:
            import aiodocker  # type: ignore[import]

            docker = aiodocker.Docker(url=settings.DOCKER_HOST)
            try:
                config = _build_container_config(record)
                container = await docker.containers.create_or_replace(
                    name=record.name,
                    config=config,
                )
                await container.start()
                record.container_id = container.id
                record.status = "running"
                logger.info(
                    "mcp_container_started",
                    container_id=container_id,
                    docker_id=container.id,
                )
            finally:
                await docker.close()
        except Exception as exc:
            record.status = "error"
            record.error_message = f"Start failed: {exc}"
            logger.error(
                "mcp_container_start_failed",
                container_id=container_id,
                error=str(exc),
            )

        record.updated_at = _utcnow()
        session.add(record)
        await session.commit()
        await session.refresh(record)
        return record

    # ── Stop ──────────────────────────────────────────────────────────

    @staticmethod
    async def stop_container(
        session: AsyncSession,
        container_id: str,
    ) -> MCPServerContainer:
        """Stop a running container."""
        record = await _get_or_404(session, container_id)

        if not await _is_docker_available():
            logger.info("docker_unavailable_mock_stop", container_id=container_id)
            record.status = "stopped"
            record.updated_at = _utcnow()
            session.add(record)
            await session.commit()
            await session.refresh(record)
            return record

        try:
            import aiodocker  # type: ignore[import]

            if record.container_id:
                docker = aiodocker.Docker(url=settings.DOCKER_HOST)
                try:
                    container = docker.containers.container(record.container_id)
                    await container.stop()
                    record.status = "stopped"
                    logger.info("mcp_container_stopped", container_id=container_id)
                finally:
                    await docker.close()
            else:
                record.status = "stopped"
        except Exception as exc:
            record.status = "error"
            record.error_message = f"Stop failed: {exc}"
            logger.error(
                "mcp_container_stop_failed",
                container_id=container_id,
                error=str(exc),
            )

        record.updated_at = _utcnow()
        session.add(record)
        await session.commit()
        await session.refresh(record)
        return record

    # ── Restart ───────────────────────────────────────────────────────

    @staticmethod
    async def restart_container(
        session: AsyncSession,
        container_id: str,
    ) -> MCPServerContainer:
        """Restart a container (stop → start)."""
        record = await _get_or_404(session, container_id)

        if not await _is_docker_available():
            logger.info("docker_unavailable_mock_restart", container_id=container_id)
            record.status = "running"
            record.updated_at = _utcnow()
            session.add(record)
            await session.commit()
            await session.refresh(record)
            return record

        try:
            import aiodocker  # type: ignore[import]

            if record.container_id:
                docker = aiodocker.Docker(url=settings.DOCKER_HOST)
                try:
                    container = docker.containers.container(record.container_id)
                    await container.restart()
                    record.status = "running"
                    logger.info("mcp_container_restarted", container_id=container_id)
                finally:
                    await docker.close()
            else:
                # No docker ID — do a full start cycle
                return await MCPContainerService.start_container(session, container_id)
        except Exception as exc:
            record.status = "error"
            record.error_message = f"Restart failed: {exc}"
            logger.error(
                "mcp_container_restart_failed",
                container_id=container_id,
                error=str(exc),
            )

        record.updated_at = _utcnow()
        session.add(record)
        await session.commit()
        await session.refresh(record)
        return record

    # ── Remove ────────────────────────────────────────────────────────

    @staticmethod
    async def remove_container(
        session: AsyncSession,
        container_id: str,
        force: bool = False,
    ) -> None:
        """Stop (if running) and remove a container, then delete the DB record."""
        record = await _get_or_404(session, container_id)

        if await _is_docker_available() and record.container_id:
            try:
                import aiodocker  # type: ignore[import]

                docker = aiodocker.Docker(url=settings.DOCKER_HOST)
                try:
                    container = docker.containers.container(record.container_id)
                    await container.delete(force=force)
                    logger.info("mcp_container_removed", container_id=container_id)
                finally:
                    await docker.close()
            except Exception as exc:
                logger.warning(
                    "mcp_container_remove_docker_failed",
                    container_id=container_id,
                    error=str(exc),
                )
        else:
            logger.info(
                "docker_unavailable_mock_remove",
                container_id=container_id,
            )

        await session.delete(record)
        await session.commit()

    # ── Logs ──────────────────────────────────────────────────────────

    @staticmethod
    async def get_logs(
        session: AsyncSession,
        container_id: str,
        tail: int = 100,
    ) -> list[str]:
        """Return the last N log lines from a running container."""
        record = await _get_or_404(session, container_id)

        if not await _is_docker_available():
            return [
                f"[mock] Container {record.name} log line {i}"
                for i in range(min(tail, 5))
            ]

        if not record.container_id:
            return []

        try:
            import aiodocker  # type: ignore[import]

            docker = aiodocker.Docker(url=settings.DOCKER_HOST)
            try:
                container = docker.containers.container(record.container_id)
                logs = await container.log(stdout=True, stderr=True, tail=tail)
                return logs if isinstance(logs, list) else [logs]
            finally:
                await docker.close()
        except Exception as exc:
            logger.error(
                "mcp_container_logs_failed", container_id=container_id, error=str(exc)
            )
            return [f"Error fetching logs: {exc}"]

    # ── Health Check ──────────────────────────────────────────────────

    @staticmethod
    async def check_health(
        session: AsyncSession,
        container_id: str,
    ) -> MCPServerContainer:
        """Perform an HTTP health check and update the record."""
        record = await _get_or_404(session, container_id)
        now = _utcnow()
        record.last_health_check = now

        if not record.health_check_url:
            record.health_status = "unknown"
            record.updated_at = now
            session.add(record)
            await session.commit()
            await session.refresh(record)
            return record

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(record.health_check_url)
            record.health_status = "healthy" if resp.is_success else "unhealthy"
        except Exception as exc:
            record.health_status = "unhealthy"
            logger.warning(
                "mcp_container_health_check_failed",
                container_id=container_id,
                url=record.health_check_url,
                error=str(exc),
            )

        record.updated_at = now
        session.add(record)
        await session.commit()
        await session.refresh(record)

        logger.info(
            "mcp_container_health_checked",
            container_id=container_id,
            health_status=record.health_status,
        )
        return record

    # ── List ──────────────────────────────────────────────────────────

    @staticmethod
    async def list_containers(
        session: AsyncSession,
        *,
        tenant_id: str | None = None,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[MCPServerContainer], int]:
        """Return a paginated list of container records with optional filters."""
        stmt = select(MCPServerContainer)
        if tenant_id is not None:
            stmt = stmt.where(MCPServerContainer.tenant_id == tenant_id)
        if status is not None:
            stmt = stmt.where(MCPServerContainer.status == status)

        # Count total
        from sqlalchemy import func
        from sqlmodel import select as sel

        count_stmt = sel(func.count()).select_from(MCPServerContainer)
        if tenant_id is not None:
            count_stmt = count_stmt.where(MCPServerContainer.tenant_id == tenant_id)
        if status is not None:
            count_stmt = count_stmt.where(MCPServerContainer.status == status)

        count_result = await session.exec(count_stmt)
        total = count_result.one()

        stmt = stmt.offset(offset).limit(limit)
        result = await session.exec(stmt)
        return list(result.all()), total

    # ── Get single ────────────────────────────────────────────────────

    @staticmethod
    async def get_container(
        session: AsyncSession,
        container_id: str,
    ) -> MCPServerContainer | None:
        """Return a single container record by ID, or None."""
        result = await session.exec(
            select(MCPServerContainer).where(MCPServerContainer.id == container_id)
        )
        return result.first()


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


async def _get_or_404(session: AsyncSession, container_id: str) -> MCPServerContainer:
    """Fetch a container record or raise ValueError if not found."""
    result = await session.exec(
        select(MCPServerContainer).where(MCPServerContainer.id == container_id)
    )
    record = result.first()
    if record is None:
        raise ValueError(f"Container {container_id} not found")
    return record


def _build_container_config(record: MCPServerContainer) -> dict[str, Any]:
    """Build an aiodocker container config dict from a MCPServerContainer record."""
    image_ref = f"{record.image}:{record.tag}"

    config: dict[str, Any] = {
        "Image": image_ref,
        "Labels": record.labels or {},
        "HostConfig": {
            "RestartPolicy": {"Name": record.restart_policy},
            "NetworkMode": record.network,
        },
    }

    # Environment variables
    if record.env_vars:
        config["Env"] = [f"{k}={v}" for k, v in record.env_vars.items()]

    # Port mappings: {"8080": "80"} → host_port: container_port
    if record.port_mappings:
        exposed: dict[str, dict] = {}
        bindings: dict[str, list[dict[str, str]]] = {}
        for host_port, container_port in record.port_mappings.items():
            key = f"{container_port}/tcp"
            exposed[key] = {}
            bindings[key] = [{"HostPort": str(host_port)}]
        config["ExposedPorts"] = exposed
        config["HostConfig"]["PortBindings"] = bindings

    # Volume mounts
    if record.volumes:
        config["HostConfig"]["Binds"] = [
            f"{host}:{container}" for host, container in record.volumes.items()
        ]

    # Resource limits (memory in bytes, cpu shares)
    if record.resource_limits:
        if "memory" in record.resource_limits:
            config["HostConfig"]["Memory"] = record.resource_limits["memory"]
        if "cpu_shares" in record.resource_limits:
            config["HostConfig"]["CpuShares"] = record.resource_limits["cpu_shares"]

    return config


__all__ = ["MCPContainerService"]
