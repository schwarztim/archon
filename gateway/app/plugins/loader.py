"""Plugin loader — discovers, validates and hot-reloads YAML plugin definitions."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from app.plugins.models import Plugin, ToolSchema

logger = logging.getLogger(__name__)


class PluginLoader:
    """Hot-loadable registry of :class:`Plugin` instances.

    On startup, :meth:`load_all` scans the configured directory for ``*.yaml``
    files.  If *watchfiles* is installed, :meth:`start_watcher` kicks off a
    background task that reloads changed files automatically.
    """

    def __init__(self) -> None:
        self._plugins: dict[str, Plugin] = {}
        self._tool_index: dict[str, tuple[Plugin, ToolSchema]] = {}
        self._watcher_task: asyncio.Task[None] | None = None
        self._plugins_dir: Path | None = None

    # ── Loading ────────────────────────────────────────────────────────

    def load_all(self, plugins_dir: str | Path) -> list[Plugin]:
        """Scan *plugins_dir* for ``*.yaml`` files and load each one.

        Files that fail validation are skipped with a warning.
        Returns the list of successfully loaded plugins.
        """
        directory = Path(plugins_dir)
        self._plugins_dir = directory

        if not directory.is_dir():
            logger.warning("Plugins directory %s does not exist — skipping", directory)
            return []

        self._plugins.clear()
        self._tool_index.clear()

        loaded: list[Plugin] = []
        for yaml_path in sorted(directory.glob("*.yaml")):
            plugin = self._load_file(yaml_path)
            if plugin is not None:
                self._register(plugin)
                loaded.append(plugin)

        logger.info("Loaded %d plugin(s) from %s", len(loaded), directory)
        return loaded

    def _load_file(self, path: Path) -> Plugin | None:
        """Parse and validate a single YAML plugin file.

        Returns ``None`` on any error so the registry continues loading.
        """
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not read plugin file %s: %s", path, exc)
            return None

        if not isinstance(raw, dict):
            logger.warning("Plugin file %s is not a YAML mapping — skipping", path)
            return None

        try:
            plugin = Plugin.model_validate(raw)
        except ValidationError as exc:
            logger.warning("Plugin file %s failed validation: %s", path, exc)
            return None

        if not plugin.enabled:
            logger.debug("Plugin %s is disabled — skipping", plugin.name)
            return None

        logger.debug("Loaded plugin: %s (%s)", plugin.name, plugin.version)
        return plugin

    def _register(self, plugin: Plugin) -> None:
        """Add plugin and index its tools."""
        self._plugins[plugin.name] = plugin
        for tool in plugin.tools:
            self._tool_index[tool.id] = (plugin, tool)

    # ── Query helpers ──────────────────────────────────────────────────

    def get_plugin(self, name: str) -> Plugin | None:
        """Return plugin by name slug."""
        return self._plugins.get(name)

    def get_plugins(self) -> list[Plugin]:
        """Return all loaded enabled plugins."""
        return list(self._plugins.values())

    def get_tool(self, tool_id: str) -> ToolSchema | None:
        """Return a tool schema by its ID, or None if not found."""
        entry = self._tool_index.get(tool_id)
        return entry[1] if entry else None

    def get_tool_plugin(self, tool_id: str) -> tuple[Plugin, ToolSchema] | None:
        """Return (plugin, tool) pair for a tool_id, or None."""
        return self._tool_index.get(tool_id)

    def __len__(self) -> int:
        return len(self._plugins)

    # ── Hot-reload watcher ─────────────────────────────────────────────

    async def start_watcher(self) -> None:
        """Start background file watcher if *watchfiles* is available."""
        if self._plugins_dir is None:
            return
        try:
            from watchfiles import awatch  # type: ignore[import-untyped]
        except ImportError:
            logger.info("watchfiles not installed — hot-reload disabled")
            return

        self._watcher_task = asyncio.create_task(self._watch_loop(awatch), name="plugin-watcher")
        logger.info("Plugin hot-reload watcher started for %s", self._plugins_dir)

    async def _watch_loop(self, awatch: Any) -> None:  # noqa: ANN401
        """Reload changed plugin files as they change on disk."""
        assert self._plugins_dir is not None  # noqa: S101
        async for changes in awatch(str(self._plugins_dir)):
            paths = {Path(path) for _, path in changes if path.endswith(".yaml")}
            for path in paths:
                logger.info("Plugin file changed: %s — reloading", path)
                plugin = self._load_file(path)
                if plugin is not None:
                    # Remove old tool index entries for this plugin (by name)
                    stale_tools = [
                        tid for tid, (p, _) in self._tool_index.items() if p.name == plugin.name
                    ]
                    for tid in stale_tools:
                        del self._tool_index[tid]
                    self._register(plugin)

    async def stop_watcher(self) -> None:
        """Cancel the watcher task if running."""
        if self._watcher_task is not None and not self._watcher_task.done():
            self._watcher_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._watcher_task


# Module-level singleton used by routes and middleware
plugin_loader = PluginLoader()


# Legacy PluginRegistry alias kept for backward compatibility with existing routes
PluginRegistry = PluginLoader
