"""MCP Host Gateway — FastAPI application factory.

Entry point:
    uvicorn app.main:app --host 0.0.0.0 --port 8080
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.plugins.loader import plugin_loader


@asynccontextmanager
async def _lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Load plugins on startup; clean up on shutdown."""
    settings = get_settings()

    loaded = plugin_loader.load_all(settings.plugins_dir)
    application.state.plugin_registry = plugin_loader  # backward-compat alias
    application.state.loaded_plugins = loaded

    # Start hot-reload watcher if watchfiles is available
    await plugin_loader.start_watcher()

    yield

    # Graceful teardown
    await plugin_loader.stop_watcher()


def create_app() -> FastAPI:
    """Build and return the configured FastAPI application."""
    settings = get_settings()

    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        debug=settings.debug,
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=_lifespan,
    )

    # ── CORS ─────────────────────────────────────────────────────────
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Routers ──────────────────────────────────────────────────────
    # Import here to avoid circular imports at module load time
    from app.routes.capabilities import router as capabilities_router  # noqa: PLC0415
    from app.routes.health import router as health_router  # noqa: PLC0415
    from app.routes.invoke import router as invoke_router  # noqa: PLC0415
    from app.routes.plugins import router as plugins_router  # noqa: PLC0415

    application.include_router(health_router)
    application.include_router(capabilities_router, prefix="/api/v1")
    application.include_router(invoke_router, prefix="/api/v1")
    application.include_router(plugins_router, prefix="/api/v1")

    return application


app = create_app()
