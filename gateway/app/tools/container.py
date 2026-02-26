"""MCP container lifecycle manager (ToolHive-inspired pattern).

Containers are spun up on first invocation and shut down after an idle
timeout.  Docker SDK is required at runtime; when it is absent the module
degrades gracefully by raising a descriptive error.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from app.plugins.models import Plugin

logger = logging.getLogger(__name__)

# {plugin_name: {"endpoint": str, "container_id": str, "last_used": float}}
_running: dict[str, dict[str, Any]] = {}
_lock = asyncio.Lock()


async def get_or_start_container(plugin: Plugin) -> str:
    """Return a routable endpoint for the plugin's container, starting it if needed.

    Returns:
        HTTP base URL to the running container, e.g. ``http://localhost:32768``.

    Raises:
        RuntimeError: If Docker SDK is not installed or the container fails to start.
    """
    async with _lock:
        entry = _running.get(plugin.name)
        if entry:
            entry["last_used"] = time.monotonic()
            return entry["endpoint"]

        endpoint = await _start_container(plugin)
        _running[plugin.name] = {
            "endpoint": endpoint,
            "last_used": time.monotonic(),
        }

        # Schedule idle-timeout watcher
        if plugin.container:
            asyncio.create_task(
                _idle_watcher(plugin.name, plugin.container.idle_timeout),
                name=f"idle-watcher-{plugin.name}",
            )

        return endpoint


async def _start_container(plugin: Plugin) -> str:
    """Pull image and start the container via Docker SDK."""
    try:
        import docker  # type: ignore[import-untyped]
    except ImportError as exc:
        raise RuntimeError("docker SDK not installed. Install it with: pip install docker") from exc

    cfg = plugin.container
    if cfg is None:
        raise RuntimeError(f"Plugin '{plugin.name}' has no container config")

    logger.info("Starting container for plugin %s (image=%s)", plugin.name, cfg.image)

    loop = asyncio.get_event_loop()
    client = await loop.run_in_executor(None, docker.from_env)

    try:
        container = await loop.run_in_executor(
            None,
            lambda: client.containers.run(
                cfg.image,
                detach=True,
                ports={f"{cfg.port}/tcp": None},  # random host port
                environment=cfg.env,
                mem_limit=cfg.resources.memory,
                nano_cpus=int(float(cfg.resources.cpu) * 1e9),
                network_mode="bridge",
                remove=False,
            ),
        )
    except Exception as exc:
        raise RuntimeError(f"Failed to start container for plugin '{plugin.name}': {exc}") from exc

    # Wait for container to bind its port
    await asyncio.sleep(1.5)
    container.reload()
    ports = container.ports.get(f"{cfg.port}/tcp") or []
    if not ports:
        container.stop()
        container.remove()
        raise RuntimeError(f"Container for '{plugin.name}' did not bind port {cfg.port}")

    host_port = ports[0]["HostPort"]
    endpoint = f"http://localhost:{host_port}"
    logger.info("Container for %s started at %s", plugin.name, endpoint)

    # Store container ID for cleanup
    _running[plugin.name] = {
        "endpoint": endpoint,
        "container_id": container.id,
        "last_used": time.monotonic(),
    }
    return endpoint


async def _idle_watcher(plugin_name: str, idle_timeout: int) -> None:
    """Periodically check if the container has been idle and stop it."""
    while True:
        await asyncio.sleep(30)
        entry = _running.get(plugin_name)
        if entry is None:
            return

        idle_s = time.monotonic() - entry["last_used"]
        if idle_s >= idle_timeout:
            logger.info("Stopping idle container for plugin %s (idle=%.0fs)", plugin_name, idle_s)
            await _stop_container(plugin_name)
            return


async def _stop_container(plugin_name: str) -> None:
    """Stop and remove the container for *plugin_name*."""
    entry = _running.pop(plugin_name, None)
    if entry is None:
        return

    container_id = entry.get("container_id")
    if not container_id:
        return

    try:
        import docker  # type: ignore[import-untyped]

        loop = asyncio.get_event_loop()
        client = await loop.run_in_executor(None, docker.from_env)
        container = await loop.run_in_executor(None, client.containers.get, container_id)
        await loop.run_in_executor(None, container.stop)
        await loop.run_in_executor(None, container.remove)
        logger.info("Removed container %s for plugin %s", container_id[:12], plugin_name)
    except Exception as exc:
        logger.warning("Failed to stop container %s: %s", container_id, exc)
