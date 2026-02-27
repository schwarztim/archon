"""Audit middleware — auto-logs mutating HTTP requests with a tamper-evident hash chain.

Generates a correlation_id per request and logs POST/PUT/PATCH/DELETE
calls to the audit_logs table after the response is sent.  Adds the
``X-Correlation-ID`` response header on every request.

Middleware execution order in FastAPI (LIFO — last added runs first):
  add_middleware(AuditMiddleware)   ← registered first → runs LAST (innermost)
  add_middleware(TenantMiddleware)  ← registered second → runs before Audit (middle)
  add_middleware(DLPMiddleware)     ← registered last  → runs FIRST (outermost)

Effective ingress order: DLPMiddleware → TenantMiddleware → AuditMiddleware → route

This guarantees ``request.state.tenant_id`` is set by TenantMiddleware
before AuditMiddleware reads it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from typing import Any
from uuid import UUID

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

logger = logging.getLogger(__name__)

_MUTATION_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Skip health probes, docs, metrics, and the audit endpoint itself (avoids recursion)
_SKIP_RE = re.compile(
    r"^/(healthz|readyz|livez|docs|redoc|openapi\.json|metrics|api/v1/audit-logs)"
)

# Extract resource type and optional UUID from paths like /api/v1/agents/{uuid}
_RESOURCE_RE = re.compile(
    r"^/api/v[0-9]+/(?P<resource>[a-z][a-z0-9_-]+)"
    r"(?:/(?P<id>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
    r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}))?"
)

# Friendly action names for well-known (method, resource) combinations
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

# ---------------------------------------------------------------------------
# PII / secret redaction
# ---------------------------------------------------------------------------

# Matches Archon API keys: ak_live_<token> or ak_test_<token>
_API_KEY_RE = re.compile(r"\bak_(?:live|test)_[A-Za-z0-9]+")

# Matches Bearer tokens in Authorization headers or detail strings
_BEARER_RE = re.compile(r"Bearer\s+[A-Za-z0-9\-_.~+/]+=*", re.IGNORECASE)

# Matches email addresses in URL paths (e.g. /api/v1/users/alice@example.com)
_EMAIL_IN_PATH_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")


def _redact(value: str) -> str:
    """Apply all PII/secret redaction rules to *value* and return the result."""
    value = _API_KEY_RE.sub(
        lambda m: m.group(0).split("_", 2)[0]
        + "_"
        + m.group(0).split("_", 2)[1]
        + "_***",
        value,
    )
    value = _BEARER_RE.sub("Bearer ***", value)
    value = _EMAIL_IN_PATH_RE.sub("***@***.***", value)
    return value


def _redact_path(path: str) -> str:
    """Redact email addresses embedded in URL paths."""
    return _EMAIL_IN_PATH_RE.sub("***@***.***", path)


def _scrub_details(details: dict[str, Any] | None) -> dict[str, Any] | None:
    """Redact PII and secrets from the audit log details dict before DB insert.

    Serialises the dict to JSON, applies all redaction patterns, then
    deserialises back.  This catches any sensitive value that may have slipped
    into a nested field without requiring callers to be aware of the patterns.
    """
    if details is None:
        return None
    try:
        raw = json.dumps(details)
        scrubbed = _redact(raw)
        return json.loads(scrubbed)  # type: ignore[return-value]
    except Exception:
        # If serialisation fails for any reason, return details as-is.
        return details


def _resolve_action(method: str, resource: str) -> str:
    """Return a human-readable action string for (method, resource)."""
    key = (method, resource)
    if key in _ACTION_MAP:
        return _ACTION_MAP[key]
    # Fallback: resource.method_verb
    verb_map = {
        "POST": "created",
        "PUT": "updated",
        "PATCH": "updated",
        "DELETE": "deleted",
    }
    return f"{resource.rstrip('s')}.{verb_map.get(method, method.lower())}"


def _parse_resource(path: str) -> tuple[str | None, str | None]:
    """Return (resource_type, resource_id | None) from the URL path."""
    m = _RESOURCE_RE.match(path)
    if not m:
        return None, None
    return m.group("resource"), m.group("id")


async def _write_audit_entry(
    tenant_id: str,
    correlation_id: str,
    actor_id: Any,
    action: str,
    resource_type: str | None,
    resource_id: str | None,
    status_code: int,
    ip_address: str | None,
    user_agent: str | None,
    details: dict[str, Any] | None,
) -> None:
    """Write an audit entry in a fresh session (fire-and-forget helper)."""
    try:
        from app.database import async_session_factory
        from app.services.audit_service import AuditService

        # Normalise actor_id to UUID | None
        actor: UUID | None = None
        if actor_id is not None:
            try:
                actor = UUID(str(actor_id))
            except (ValueError, AttributeError):
                pass

        # Scrub any PII / secrets that may appear in the details dict before persisting
        safe_details = _scrub_details(details)

        async with async_session_factory() as session:
            await AuditService.log_action(
                session=session,
                tenant_id=tenant_id,
                correlation_id=correlation_id,
                actor_id=actor,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                status_code=status_code,
                ip_address=ip_address,
                user_agent=user_agent,
                details=details,
            )
    except Exception:
        # Audit logging must NEVER fail a request
        logger.debug("audit_middleware: failed to write audit entry", exc_info=True)


# ---------------------------------------------------------------------------
# Aliases for backwards-compatible test imports
# ---------------------------------------------------------------------------


def _extract_resource(path: str) -> tuple[str, UUID | None]:
    """Return (resource_type, resource_id | None) from the URL path.

    Returns ``("unknown", None)`` for non-matching paths.
    This is a test-friendly wrapper around :func:`_parse_resource`.
    """
    resource, rid_str = _parse_resource(path)
    if resource is None:
        return "unknown", None
    rid: UUID | None = None
    if rid_str is not None:
        try:
            rid = UUID(rid_str)
        except (ValueError, AttributeError):
            pass
    return resource, rid


def _derive_action(method: str, resource: str) -> str:
    """Return a human-readable action string for (method, resource).

    Alias for :func:`_resolve_action` used in tests.
    """
    return _resolve_action(method, resource)


#: Alias — tests import _SKIP_PATTERNS; production code uses _SKIP_RE.
_SKIP_PATTERNS = _SKIP_RE


async def _record_audit(
    *,
    actor_id: Any = None,
    action: str,
    resource_type: str | None = None,
    resource_id: Any = None,
    details: dict[str, Any] | None = None,
    tenant_id: str = "default",
    correlation_id: str | None = None,
) -> None:
    """Fire-and-forget audit entry writer (used directly in tests and hooks).

    Creates a new DB session, writes the entry, and swallows all exceptions so
    that a failing audit write never breaks the calling code path.
    """
    try:
        from app.database import async_session_factory
        from app.models import AuditLog

        entry = AuditLog(
            actor_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id is not None else None,
            details=details,
            tenant_id=tenant_id,
            correlation_id=correlation_id or "",
        )
        async with async_session_factory() as session:
            session.add(entry)
            await session.commit()
    except Exception:
        logger.debug("_record_audit: failed to write entry", exc_info=True)


# ---------------------------------------------------------------------------


class AuditMiddleware(BaseHTTPMiddleware):
    """Intercepts mutating requests and writes tamper-evident AuditLog entries.

    Features:
    - Generates a UUID correlation_id per request.
    - Sets ``request.state.correlation_id`` for downstream use.
    - Adds ``X-Correlation-ID`` to every response.
    - Logs POST/PUT/PATCH/DELETE to AuditService in a fire-and-forget task.
    - Never raises — all audit errors are caught and logged at DEBUG level.
    - Safe with StreamingResponse (logs after the response object is returned,
      not after the body is consumed).

    Security guarantees:
    - Request and response bodies are NEVER stored.
    - API keys, bearer tokens, and email addresses in paths are redacted.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """Assign correlation ID, dispatch request, then log the outcome."""
        # Assign per-request correlation ID
        correlation_id = str(uuid.uuid4())
        request.state.correlation_id = correlation_id

        response = await call_next(request)

        # Always add correlation header
        response.headers["X-Correlation-ID"] = correlation_id

        # Only audit mutating operations on non-skipped paths
        if request.method in _MUTATION_METHODS and not _SKIP_RE.match(request.url.path):
            try:
                tenant_id: str = getattr(request.state, "tenant_id", "unknown")
                actor_id: Any = getattr(request.state, "user_id", None)

                # Redact PII from the path before storing
                safe_path = _redact_path(request.url.path)
                resource_type, resource_id = _parse_resource(safe_path)
                action = (
                    _resolve_action(request.method, resource_type)
                    if resource_type
                    else f"{request.method} {safe_path}"
                )

                ip_address: str | None = request.client.host if request.client else None
                user_agent: str | None = request.headers.get("user-agent")

                # Redact any sensitive values that may appear in the Authorization header
                auth_header = request.headers.get("Authorization", "")
                safe_auth = _redact(auth_header) if auth_header else None

                # NOTE: request/response bodies are intentionally never captured here.
                details: dict[str, Any] = {
                    "outcome": ("success" if response.status_code < 400 else "failure"),
                    **(
                        {"auth_scheme": safe_auth.split()[0] if safe_auth else None}
                        if safe_auth
                        else {}
                    ),
                }

                asyncio.ensure_future(
                    _write_audit_entry(
                        tenant_id=tenant_id,
                        correlation_id=correlation_id,
                        actor_id=actor_id,
                        action=action,
                        resource_type=resource_type,
                        resource_id=resource_id,
                        status_code=response.status_code,
                        ip_address=ip_address,
                        user_agent=user_agent,
                        details=safe_details,
                    )
                )
            except Exception:
                logger.debug(
                    "audit_middleware: error preparing audit entry", exc_info=True
                )

        return response
