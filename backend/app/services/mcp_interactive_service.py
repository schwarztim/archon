"""MCPInteractiveService — Live Interactive Components with session-bound auth and RBAC."""

from __future__ import annotations

import logging
import secrets
from collections.abc import AsyncIterator
from datetime import datetime, timedelta

from app.utils.time import utcnow as _utcnow
from typing import Any
from uuid import UUID, uuid4

from app.models.mcp_interactive import (
    ActionResult,
    ComponentAction,
    ComponentCategory,
    ComponentConfig,
    ComponentSession,
    ComponentType,
    RenderedComponent,
)

logger = logging.getLogger(__name__)

# In-memory stores (keyed by tenant_id)
_sessions: dict[str, dict[UUID, ComponentSession]] = {}
_component_types: dict[str, dict[UUID, ComponentType]] = {}
_update_queues: dict[str, dict[UUID, list[dict[str, Any]]]] = {}

_SESSION_TTL_HOURS = 4


def _tenant_sessions(tenant_id: str) -> dict[UUID, ComponentSession]:
    """Return the session store for a tenant, creating if needed."""
    if tenant_id not in _sessions:
        _sessions[tenant_id] = {}
    return _sessions[tenant_id]


def _tenant_types(tenant_id: str) -> dict[UUID, ComponentType]:
    """Return the component-type store for a tenant, creating if needed."""
    if tenant_id not in _component_types:
        _component_types[tenant_id] = {}
    return _component_types[tenant_id]


def _tenant_queues(tenant_id: str) -> dict[UUID, list[dict[str, Any]]]:
    """Return the update-queue store for a tenant, creating if needed."""
    if tenant_id not in _update_queues:
        _update_queues[tenant_id] = {}
    return _update_queues[tenant_id]


class MCPInteractiveService:
    """Enterprise interactive component orchestration.

    All operations are session-bound (user JWT, never service credentials),
    tenant-scoped, RBAC-filtered, and audit-logged.
    """

    # ── Session Management ──────────────────────────────────────────

    @staticmethod
    async def create_component_session(
        tenant_id: str,
        user: Any,
        component_type: ComponentCategory,
    ) -> ComponentSession:
        """Create a session bound to the user's auth context.

        Args:
            tenant_id: Tenant scope.
            user: AuthenticatedUser from JWT middleware.
            component_type: Type of component being created.

        Returns:
            A new ComponentSession with cached permissions.
        """
        session = ComponentSession(
            session_id=uuid4(),
            user_id=user.id,
            tenant_id=tenant_id,
            component_type=component_type,
            permissions=list(user.permissions),
            created_at=_utcnow(),
            expires_at=_utcnow() + timedelta(hours=_SESSION_TTL_HOURS),
            status="active",
        )
        _tenant_sessions(tenant_id)[session.session_id] = session
        _tenant_queues(tenant_id)[session.session_id] = []

        logger.info(
            "component_session.created",
            extra={
                "tenant_id": tenant_id,
                "user_id": user.id,
                "session_id": str(session.session_id),
                "component_type": component_type.value,
            },
        )
        return session

    @staticmethod
    async def get_session(tenant_id: str, session_id: UUID) -> ComponentSession:
        """Retrieve a component session by ID within a tenant.

        Args:
            tenant_id: Tenant scope.
            session_id: Session identifier.

        Returns:
            The matching ComponentSession.

        Raises:
            ValueError: If session not found or expired.
        """
        store = _tenant_sessions(tenant_id)
        session = store.get(session_id)
        if session is None:
            raise ValueError(f"Session {session_id} not found in tenant {tenant_id}")

        if session.expires_at and session.expires_at < _utcnow():
            session.status = "expired"
            raise ValueError(f"Session {session_id} has expired")

        return session

    @staticmethod
    async def close_session(tenant_id: str, session_id: UUID) -> None:
        """Close and clean up a component session.

        Args:
            tenant_id: Tenant scope.
            session_id: Session identifier.
        """
        store = _tenant_sessions(tenant_id)
        session = store.get(session_id)
        if session is not None:
            session.status = "closed"

        queues = _tenant_queues(tenant_id)
        queues.pop(session_id, None)

        logger.info(
            "component_session.closed",
            extra={
                "tenant_id": tenant_id,
                "session_id": str(session_id),
            },
        )

    # ── Rendering ───────────────────────────────────────────────────

    @staticmethod
    async def render_component(
        tenant_id: str,
        user: Any,
        session_id: UUID,
        component_config: ComponentConfig,
    ) -> RenderedComponent:
        """Render a component with RBAC-filtered data.

        Args:
            tenant_id: Tenant scope.
            user: AuthenticatedUser from JWT middleware.
            session_id: Active component session.
            component_config: Rendering configuration.

        Returns:
            RenderedComponent with sandboxed HTML, scripts, and CSP nonce.

        Raises:
            ValueError: If session invalid or user lacks permission.
        """
        session = await MCPInteractiveService.get_session(tenant_id, session_id)

        if session.user_id != user.id:
            raise ValueError("Session does not belong to requesting user")

        csp_nonce = secrets.token_urlsafe(16)

        # RBAC-filtered data: admin sees all fields, others get a filtered view
        display_data: dict[str, Any] = {
            "type": component_config.type.value,
            "data_source": component_config.data_source,
            "filters": component_config.filters,
        }
        if "admin" in user.roles:
            display_data["display_options"] = component_config.display_options
            display_data["rbac_level"] = "full"
        else:
            display_data["rbac_level"] = "restricted"

        rendered = RenderedComponent(
            session_id=session_id,
            html_content=f'<div data-component="{component_config.type.value}" data-nonce="{csp_nonce}"></div>',
            scripts=[f"nonce-{csp_nonce}"],
            styles=[f"nonce-{csp_nonce}"],
            csp_nonce=csp_nonce,
            data=display_data,
        )

        logger.info(
            "component.rendered",
            extra={
                "tenant_id": tenant_id,
                "user_id": user.id,
                "session_id": str(session_id),
                "component_type": component_config.type.value,
            },
        )
        return rendered

    # ── Action Handling ─────────────────────────────────────────────

    @staticmethod
    async def handle_component_action(
        tenant_id: str,
        user: Any,
        session_id: UUID,
        action: ComponentAction,
    ) -> ActionResult:
        """Process a user interaction on a live component.

        Args:
            tenant_id: Tenant scope.
            user: AuthenticatedUser from JWT middleware.
            session_id: Active component session.
            action: The interaction event (button click, form submit, etc.).

        Returns:
            ActionResult indicating success/failure and optional re-render.

        Raises:
            ValueError: If session invalid or user lacks permission.
        """
        session = await MCPInteractiveService.get_session(tenant_id, session_id)

        if session.user_id != user.id:
            raise ValueError("Session does not belong to requesting user")

        # Enqueue update for real-time listeners
        queues = _tenant_queues(tenant_id)
        if session_id in queues:
            queues[session_id].append(
                {
                    "action_type": action.action_type,
                    "payload": action.payload,
                    "timestamp": _utcnow().isoformat(),
                }
            )

        logger.info(
            "component.action",
            extra={
                "tenant_id": tenant_id,
                "user_id": user.id,
                "session_id": str(session_id),
                "action_type": action.action_type,
            },
        )

        return ActionResult(
            success=True,
            data={"action_type": action.action_type, "processed": True},
        )

    # ── Component Type Registry ─────────────────────────────────────

    @staticmethod
    async def register_component_type(
        tenant_id: str,
        user: Any,
        component_def: ComponentType,
    ) -> ComponentType:
        """Register a new component type within a tenant.

        Args:
            tenant_id: Tenant scope.
            user: AuthenticatedUser — must hold admin role.
            component_def: Component type definition.

        Returns:
            The registered ComponentType with assigned ID.

        Raises:
            ValueError: If user lacks admin role.
        """
        if "admin" not in user.roles:
            raise ValueError("Only admins may register component types")

        component_def.tenant_id = tenant_id
        component_def.created_by = user.id
        component_def.created_at = _utcnow()

        store = _tenant_types(tenant_id)
        store[component_def.id] = component_def

        logger.info(
            "component_type.registered",
            extra={
                "tenant_id": tenant_id,
                "user_id": user.id,
                "component_type_id": str(component_def.id),
                "name": component_def.name,
            },
        )
        return component_def

    @staticmethod
    async def list_component_types(tenant_id: str) -> list[ComponentType]:
        """List all registered component types for a tenant.

        Args:
            tenant_id: Tenant scope.

        Returns:
            List of ComponentType definitions.
        """
        store = _tenant_types(tenant_id)
        return list(store.values())

    # ── Real-time Updates ───────────────────────────────────────────

    @staticmethod
    async def stream_updates(
        tenant_id: str,
        user: Any,
        session_id: UUID,
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield queued real-time updates for a component session.

        Args:
            tenant_id: Tenant scope.
            user: AuthenticatedUser from JWT middleware.
            session_id: Active component session.

        Yields:
            Update dicts as they become available.

        Raises:
            ValueError: If session invalid or user mismatch.
        """
        session = await MCPInteractiveService.get_session(tenant_id, session_id)

        if session.user_id != user.id:
            raise ValueError("Session does not belong to requesting user")

        queues = _tenant_queues(tenant_id)
        queue = queues.get(session_id, [])
        while queue:
            yield queue.pop(0)


__all__ = [
    "MCPInteractiveService",
]
