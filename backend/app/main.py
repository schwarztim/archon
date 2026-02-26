"""Archon backend — FastAPI application entry point.

Enterprise-hardened application factory with request ID middleware,
structured logging, health probes, and structured error responses.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.health import router as health_router
from app.logging_config import get_logger, request_id_ctx, setup_logging

# Phase 1 routers
from app.routes.agents import router as agents_router
from app.routes.agent_versions import router as agent_versions_router
from app.routes.audit_logs import router as audit_logs_router
from app.routes.connectors import router as connectors_router
from app.routes.connectors import enterprise as connectors_enterprise
from app.routes.executions import router as executions_router
from app.routes.models import router as models_router
from app.routes.models import router_api as router_api_router
from app.routes.sandbox import router as sandbox_router
from app.routes.templates import router as templates_router
from app.routes.versioning import router as versioning_router
from app.routes.wizard import router as wizard_router
from app.websocket.routes import router as ws_router

# Phase 2 routers
from app.routes.router import router as router_router
from app.routes.lifecycle import router as lifecycle_router
from app.routes.lifecycle import lifecycle_v1_router
from app.routes.cost import router as cost_router
from app.routes.tenancy import router as tenancy_router

# Phase 3 routers
from app.routes.dlp import router as dlp_router
from app.routes.governance import router as governance_router
from app.routes.sentinelscan import (
    router as sentinelscan_router,
    scan_router as sentinelscan_scan_router,
    enterprise_router as sentinelscan_enterprise_router,
)
from app.routes.mcp_security import router as mcp_security_router

# Workflow routers
from app.routes.workflows import router as workflows_router

# Phase 4 routers
from app.routes.a2a import router as a2a_router
from app.routes.a2a import federation_router as a2a_federation_router

# Phase 5 routers
from app.routes.mcp import router as mcp_router
from app.routes.marketplace import router as marketplace_router

# Phase 6 routers
from app.routes.mesh import router as mesh_router
from app.routes.edge import router as edge_router

# DocForge routers
from app.routes.docforge import router as docforge_router
from app.routes.docforge import collections_router as docforge_collections_router

# Enterprise SSO & SCIM routers
from app.routes.saml import router as saml_router
from app.routes.scim import router as scim_router
from app.routes.auth_routes import router as auth_router
from app.routes.sso import router as sso_router
from app.routes.sso_config import router as sso_config_router
from app.routes.totp import router as totp_router

# Additional routers (self-prefixed with /api/v1)
from app.routes.secrets import router as secrets_router
from app.routes.deployment import router as deployment_router
from app.routes.redteam import router as redteam_router
from app.routes.tenants import router as tenants_router
from app.routes.mobile import router as mobile_router
from app.routes.mcp_interactive import router as mcp_interactive_router
from app.routes.security_proxy import router as security_proxy_router
from app.routes.admin import router as admin_router
from app.routes.settings import router as settings_router
from app.routes.rbac import router as rbac_router

# Metrics
from app.metrics import router as metrics_router

logger = get_logger(__name__)


# ------------------------------------------------------------------
# Application factory
# ------------------------------------------------------------------


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Returns a fully wired app with middleware, routers, exception
    handlers, and health endpoints.
    """
    setup_logging(log_level=settings.log_level)

    application = FastAPI(
        title="Archon",
        description="Enterprise AI Orchestration Platform",
        version="0.1.0",
        debug=False,
        redirect_slashes=True,
    )

    # -- CORS (never wildcard in production) --------------------------
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # -- Request ID middleware ----------------------------------------
    @application.middleware("http")
    async def request_id_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
        """Generate a UUID per request, set context var, add response header."""
        rid = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request_id_ctx.set(rid)
        request.state.request_id = rid
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response

    # -- Metrics middleware (outermost to capture all requests) ----------
    from app.middleware.metrics_middleware import MetricsMiddleware

    application.add_middleware(MetricsMiddleware)

    # -- Audit middleware (registered first so it runs LAST/innermost after Tenant)
    # FastAPI applies middleware in LIFO order: last registered = outermost = runs first.
    # TenantMiddleware must set request.state.tenant_id before AuditMiddleware reads it.
    # Effective ingress order: DLPMiddleware → TenantMiddleware → AuditMiddleware → route
    from app.middleware.audit_middleware import AuditMiddleware

    application.add_middleware(AuditMiddleware)

    # -- Tenant middleware (extracts tenant_id from JWT; runs before Audit) --
    from app.middleware.tenant_middleware import TenantMiddleware

    application.add_middleware(TenantMiddleware)

    # -- DLP middleware (reads tenant_id set by TenantMiddleware) -----------
    from app.middleware.dlp_middleware import DLPMiddleware

    application.add_middleware(DLPMiddleware)

    # -- Rate limiting middleware (outermost after CORS so all requests are counted) --
    from app.middleware.rate_limit import RateLimitMiddleware

    application.add_middleware(RateLimitMiddleware)

    # -- Health probes (unauthenticated) ------------------------------
    application.include_router(health_router)

    # -- Phase 1 routers ----------------------------------------------
    application.include_router(agents_router, prefix=settings.API_PREFIX)
    application.include_router(agent_versions_router, prefix=settings.API_PREFIX)
    application.include_router(audit_logs_router, prefix=settings.API_PREFIX)
    application.include_router(connectors_router, prefix=settings.API_PREFIX)
    application.include_router(connectors_enterprise, prefix=settings.API_PREFIX)
    application.include_router(executions_router, prefix=settings.API_PREFIX)
    application.include_router(models_router, prefix=settings.API_PREFIX)
    application.include_router(router_api_router, prefix=settings.API_PREFIX)
    application.include_router(sandbox_router, prefix=settings.API_PREFIX)
    application.include_router(templates_router, prefix=settings.API_PREFIX)
    application.include_router(versioning_router, prefix=settings.API_PREFIX)
    application.include_router(wizard_router, prefix=settings.API_PREFIX)
    application.include_router(ws_router)

    # -- Phase 2 routers ----------------------------------------------
    application.include_router(router_router, prefix=settings.API_PREFIX)
    application.include_router(lifecycle_router, prefix=settings.API_PREFIX)
    application.include_router(lifecycle_v1_router, prefix=settings.API_PREFIX)
    application.include_router(cost_router, prefix=settings.API_PREFIX)
    application.include_router(tenancy_router, prefix=settings.API_PREFIX)

    # -- Phase 3 routers ----------------------------------------------
    application.include_router(dlp_router, prefix=settings.API_PREFIX)
    application.include_router(governance_router, prefix=settings.API_PREFIX)
    application.include_router(sentinelscan_router, prefix=settings.API_PREFIX)
    application.include_router(sentinelscan_scan_router, prefix=settings.API_PREFIX)
    application.include_router(
        sentinelscan_enterprise_router, prefix=settings.API_PREFIX
    )
    application.include_router(mcp_security_router, prefix=settings.API_PREFIX)

    # -- Workflow routers ---------------------------------------------
    application.include_router(workflows_router, prefix=settings.API_PREFIX)

    # -- Phase 4 routers ----------------------------------------------
    application.include_router(a2a_router, prefix=settings.API_PREFIX)
    application.include_router(a2a_federation_router, prefix=settings.API_PREFIX)

    # -- Phase 5 routers ----------------------------------------------
    application.include_router(mcp_router, prefix=settings.API_PREFIX)
    application.include_router(marketplace_router, prefix=settings.API_PREFIX)

    # -- Phase 6 routers ----------------------------------------------
    application.include_router(mesh_router, prefix=settings.API_PREFIX)
    application.include_router(edge_router, prefix=settings.API_PREFIX)

    # -- DocForge routers ---------------------------------------------
    application.include_router(
        docforge_router, prefix=settings.API_PREFIX + "/docforge"
    )
    application.include_router(docforge_collections_router, prefix=settings.API_PREFIX)

    # -- Enterprise SSO & SCIM ----------------------------------------
    application.include_router(saml_router)
    application.include_router(scim_router)

    # -- Auth (dev login, /me, /logout) --------------------------------
    application.include_router(auth_router)

    # -- TOTP (dedicated non-OIDC MFA fallback) -------------------------
    application.include_router(totp_router)

    # -- SSO configuration (CRUD, test-connection, RBAC matrix) --------------
    application.include_router(sso_router)
    application.include_router(sso_config_router)

    # -- Additional routers (self-prefixed) ----------------------------
    application.include_router(secrets_router)
    application.include_router(deployment_router)
    application.include_router(redteam_router)
    application.include_router(tenants_router)
    application.include_router(mobile_router)
    application.include_router(mcp_interactive_router)
    application.include_router(security_proxy_router)
    application.include_router(admin_router, prefix=settings.API_PREFIX)

    # -- Settings Platform -------------------------------------------
    application.include_router(settings_router, prefix=settings.API_PREFIX)

    # -- RBAC CRUD (custom roles + group mappings) -------------------
    application.include_router(rbac_router, prefix=settings.API_PREFIX)

    # -- Metrics (Prometheus-compatible) ------------------------------
    application.include_router(metrics_router)

    # -- Startup event ------------------------------------------------
    @application.on_event("startup")
    async def on_startup() -> None:
        """Create database tables on startup and seed default user."""
        from app.database import create_db_and_tables, async_session_factory

        await create_db_and_tables()
        async with async_session_factory() as session:
            from app.models import User
            from sqlmodel import select

            result = await session.exec(select(User).limit(1))
            if result.first() is None:
                from uuid import UUID

                default_user = User(
                    id=UUID("00000000-0000-0000-0000-000000000001"),
                    email="system@archon.local",
                    name="System",
                    role="admin",
                )
                session.add(default_user)
                await session.commit()
        logger.info("application_started")

    # -- Exception handlers -------------------------------------------
    @application.exception_handler(Exception)
    async def global_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        """Return structured JSON errors with request_id."""
        rid = getattr(request.state, "request_id", "")
        logger.error(
            "unhandled_exception",
            error=str(exc),
            error_type=type(exc).__name__,
            request_id=rid,
        )
        return JSONResponse(
            status_code=500,
            content={
                "errors": [
                    {
                        "code": "INTERNAL_SERVER_ERROR",
                        "message": "An unexpected error occurred.",
                    }
                ],
                "meta": {
                    "request_id": rid,
                    "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                },
            },
        )

    return application


# Module-level app instance (used by uvicorn: ``app.main:app``)
app = create_app()
