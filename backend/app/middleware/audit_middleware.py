"""Audit middleware — auto-logs mutating HTTP requests in the background."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any
from uuid import UUID, uuid4

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

logger = logging.getLogger(__name__)

_MUTATION_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# Paths to skip (health, docs, audit-logs itself to avoid recursion)
_SKIP_PATTERNS = re.compile(
    r"^/(healthz|readyz|livez|docs|redoc|openapi\.json|api/v1/audit-logs)"
)

# Extract resource type and optional resource ID from API paths like /api/v1/agents/{id}
_RESOURCE_RE = re.compile(
    r"^/api/v1/(?P<resource>[a-z][a-z0-9_-]+)"
    r"(?:/(?P<id>[0-9a-fA-F-]{36}))?"
)

# Map (method, resource_prefix) → human-readable action
_ACTION_MAP: dict[tuple[str, str], str] = {
    ("POST", "agents"): "agent.created",
    ("PUT", "agents"): "agent.updated",
    ("PATCH", "agents"): "agent.updated",
    ("DELETE", "agents"): "agent.deleted",
    ("POST", "users"): "user.invited",
    ("PUT", "users"): "user.updated",
    ("PATCH", "users"): "user.updated",
    ("DELETE", "users"): "user.removed",
    ("POST", "secrets"): "secret.created",
    ("PUT", "secrets"): "secret.rotated",
    ("PATCH", "secrets"): "secret.rotated",
    ("POST", "policies"): "policy.created",
    ("PUT", "policies"): "policy.updated",
    ("PATCH", "policies"): "policy.updated",
    ("POST", "deployments"): "deployment.created",
    ("PUT", "deployments"): "deployment.promoted",
    ("PATCH", "deployments"): "deployment.promoted",
    ("POST", "connectors"): "connector.created",
    ("POST", "budgets"): "budget.created",
    ("POST", "templates"): "template.instantiated",
    ("POST", "workflows"): "workflow.created",
    ("POST", "approvals"): "approval.submitted",
    ("PUT", "approvals"): "approval.approved",
    ("PATCH", "approvals"): "approval.approved",
    ("POST", "auth"): "login.success",
    ("POST", "sso"): "sso.configured",
}


def _derive_action(method: str, resource: str) -> str:
    """Derive a human-readable action name from HTTP method and resource."""
    key = (method, resource)
    if key in _ACTION_MAP:
        return _ACTION_MAP[key]
    # Fallback: resource.method_verb
    verb_map = {"POST": "created", "PUT": "updated", "PATCH": "updated", "DELETE": "deleted"}
    return f"{resource.rstrip('s')}.{verb_map.get(method, method.lower())}"


def _extract_resource(path: str) -> tuple[str, UUID | None]:
    """Return (resource_type, resource_id | None) from the URL path."""
    m = _RESOURCE_RE.match(path)
    if not m:
        return "unknown", None
    resource = m.group("resource")
    raw_id = m.group("id")
    rid: UUID | None = None
    if raw_id:
        try:
            rid = UUID(raw_id)
        except ValueError:
            pass
    return resource, rid


async def _record_audit(
    actor_id: UUID,
    action: str,
    resource_type: str,
    resource_id: UUID,
    details: dict[str, Any] | None = None,
) -> None:
    """Persist an audit log entry in a fresh session (non-blocking helper)."""
    try:
        from app.database import async_session_factory
        from app.models import AuditLog

        entry = AuditLog(
            actor_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
        )
        async with async_session_factory() as session:
            session.add(entry)
            await session.commit()
    except Exception:
        logger.debug("audit_middleware: failed to record audit entry", exc_info=True)


class AuditMiddleware(BaseHTTPMiddleware):
    """Intercepts mutating requests and creates AuditLog entries after response."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """Process the request and log audit entries for mutations."""
        # Only audit mutations
        if request.method not in _MUTATION_METHODS:
            return await call_next(request)

        # Skip paths that shouldn't be audited
        if _SKIP_PATTERNS.match(request.url.path):
            return await call_next(request)

        response = await call_next(request)

        # Fire-and-forget audit logging — never block the response
        try:
            actor_id: UUID | None = getattr(request.state, "user_id", None)
            if actor_id is None:
                # Fallback: use a sentinel UUID for unauthenticated / system calls
                actor_id = UUID("00000000-0000-0000-0000-000000000000")

            resource_type, resource_id = _extract_resource(request.url.path)
            action = _derive_action(request.method, resource_type)
            if resource_id is None:
                resource_id = uuid4()

            outcome = "success" if response.status_code < 400 else "failure"
            ip_address = request.client.host if request.client else None

            details: dict[str, Any] = {
                "status_code": response.status_code,
                "outcome": outcome,
                "ip_address": ip_address,
                "request_id": str(uuid4()),
            }

            asyncio.ensure_future(
                _record_audit(
                    actor_id=actor_id,
                    action=action,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    details=details,
                )
            )
        except Exception:
            logger.debug("audit_middleware: error preparing audit entry", exc_info=True)

        return response
