"""Context-var-backed tenant scoping for the Archon enterprise stack.

Phase 4 / WS12 — DB-level tenant isolation.

Tenant identity is propagated through async call chains via a
``contextvars.ContextVar``. Middleware writes the value at the request
boundary; services and database helpers read it without taking it as a
parameter on every call.

The legacy "default-tenant" string and the zero-UUID fallback used by older
code paths are explicitly rejected by :func:`require_tenant`. Operations
that need a tenant must run inside a real tenant context.

Concurrency model
-----------------
``ContextVar`` is the asyncio-aware primitive: each task launched via
``asyncio.create_task`` (or ``asyncio.gather``) inherits a snapshot of the
current context at creation time, so concurrent tasks do not see each
other's mutations. This makes the variable safe for use inside FastAPI
request handlers and background workers.

Usage
-----
::

    # Middleware boundary
    token = set_current_tenant(uuid)
    try:
        await call_next(request)
    finally:
        reset_tenant(token)

    # Service code
    tid = require_tenant()
    rows = await session.exec(select(Workflow).where(Workflow.tenant_id == tid))

    # Tests
    async with tenant_scope(tenant_id_a):
        ...
"""

from __future__ import annotations

import contextlib
import contextvars
from collections.abc import AsyncIterator
from typing import Final
from uuid import UUID

# ── Sentinels ──────────────────────────────────────────────────────────

#: Zero-UUID — emitted by legacy code paths that constructed
#: ``UUID(int=0)`` when no tenant was resolved. Treated as missing.
_ZERO_UUID: Final[UUID] = UUID("00000000-0000-0000-0000-000000000000")

#: Legacy fallback strings used by ``tenant_middleware.py`` and
#: ``tenant.py``. Treated as missing in strict mode.
_LEGACY_FALLBACK_STRINGS: Final[frozenset[str]] = frozenset(
    {
        "default",
        "default-tenant",
        "00000000-0000-0000-0000-000000000000",
        "",
    }
)

# ── Context variables ─────────────────────────────────────────────────

#: The active tenant for the current asyncio task. ``None`` means no
#: tenant has been resolved (unauthenticated request, background work
#: that has not been scoped yet, etc.).
_TENANT_VAR: contextvars.ContextVar[UUID | None] = contextvars.ContextVar(
    "archon_tenant_id", default=None,
)

#: The active end-user for the current asyncio task. Optional —
#: middleware may or may not propagate this.
_USER_VAR: contextvars.ContextVar[UUID | None] = contextvars.ContextVar(
    "archon_user_id", default=None,
)


# ── Errors ────────────────────────────────────────────────────────────


class TenantContextRequired(RuntimeError):
    """Raised when a tenant-scoped operation runs without a tenant context.

    The dispatcher, services, and database helpers raise this instead of
    silently falling back to the zero-UUID. Application code should
    surface it as HTTP 401/403 at the request boundary.
    """


# ── Read accessors ────────────────────────────────────────────────────


def get_current_tenant() -> UUID | None:
    """Return the current tenant UUID or ``None`` if unset."""
    return _TENANT_VAR.get()


def get_current_user() -> UUID | None:
    """Return the current end-user UUID or ``None`` if unset."""
    return _USER_VAR.get()


def _coerce_tenant(value: UUID | str | None) -> UUID | None:
    """Normalise any accepted tenant representation to ``UUID`` or ``None``.

    Accepts ``UUID`` instances, hex strings, and legacy fallback strings.
    Legacy fallback strings and zero-UUID resolve to ``None`` so callers
    cannot smuggle them past :func:`require_tenant`.
    """
    if value is None:
        return None
    if isinstance(value, UUID):
        return None if value == _ZERO_UUID else value
    if isinstance(value, str):
        cleaned = value.strip().lower()
        if cleaned in _LEGACY_FALLBACK_STRINGS:
            return None
        try:
            uid = UUID(cleaned)
        except (ValueError, AttributeError) as exc:
            raise ValueError(
                f"set_current_tenant: not a valid UUID: {value!r}"
            ) from exc
        return None if uid == _ZERO_UUID else uid
    raise TypeError(
        f"set_current_tenant: expected UUID|str|None, got {type(value).__name__}"
    )


# ── Mutators ──────────────────────────────────────────────────────────


def set_current_tenant(tenant_id: UUID | str | None) -> contextvars.Token:
    """Bind ``tenant_id`` to the current asyncio task.

    Returns a token that the caller must pass to :func:`reset_tenant`
    when the scope ends. Legacy fallback strings and the zero-UUID are
    coerced to ``None`` rather than rejected outright — middleware sets
    the variable on every request, including unauthenticated probes,
    and the rejection happens later at :func:`require_tenant`.
    """
    coerced = _coerce_tenant(tenant_id)
    return _TENANT_VAR.set(coerced)


def set_current_user(user_id: UUID | str | None) -> contextvars.Token:
    """Bind ``user_id`` to the current asyncio task."""
    if user_id is None or isinstance(user_id, UUID):
        return _USER_VAR.set(user_id)
    if isinstance(user_id, str):
        cleaned = user_id.strip()
        if not cleaned or cleaned in _LEGACY_FALLBACK_STRINGS:
            return _USER_VAR.set(None)
        try:
            return _USER_VAR.set(UUID(cleaned))
        except ValueError as exc:
            raise ValueError(
                f"set_current_user: not a valid UUID: {user_id!r}"
            ) from exc
    raise TypeError(
        f"set_current_user: expected UUID|str|None, got {type(user_id).__name__}"
    )


def reset_tenant(token: contextvars.Token) -> None:
    """Restore the previous tenant binding from ``token``."""
    _TENANT_VAR.reset(token)


def reset_user(token: contextvars.Token) -> None:
    """Restore the previous user binding from ``token``."""
    _USER_VAR.reset(token)


# ── Strict-mode guard ─────────────────────────────────────────────────


def require_tenant() -> UUID:
    """Return the current tenant or raise :class:`TenantContextRequired`.

    This is the structural enforcement point for the no-default-tenant
    rule. Any service or query that must run scoped to a tenant should
    call this at the top.

    Raises:
        TenantContextRequired: if no tenant context is active, or if the
            active tenant is the legacy zero-UUID sentinel.
    """
    tid = _TENANT_VAR.get()
    if tid is None or tid == _ZERO_UUID:
        raise TenantContextRequired(
            "Operation requires an authenticated tenant context. "
            "The legacy zero-UUID / 'default-tenant' fallback is rejected "
            "in enterprise mode. Authenticate via Keycloak/OIDC or wrap "
            "the call in `tenant_scope(<tenant_id>)`."
        )
    return tid


# ── Async context manager helper ──────────────────────────────────────


@contextlib.asynccontextmanager
async def tenant_scope(
    tenant_id: UUID | str | None,
    *,
    user_id: UUID | str | None = None,
) -> AsyncIterator[UUID | None]:
    """Bind ``tenant_id`` (and optionally ``user_id``) for the duration.

    Yields the resolved tenant UUID — or ``None`` if a legacy/zero
    sentinel was passed in so callers can choose to skip work cleanly.
    The previous bindings are restored on exit, even if the body raises.

    Example::

        async with tenant_scope(tenant_a):
            await do_tenant_scoped_work()
    """
    tenant_token = set_current_tenant(tenant_id)
    user_token = set_current_user(user_id)
    try:
        yield _TENANT_VAR.get()
    finally:
        reset_user(user_token)
        reset_tenant(tenant_token)


__all__ = [
    "TenantContextRequired",
    "get_current_tenant",
    "get_current_user",
    "require_tenant",
    "reset_tenant",
    "reset_user",
    "set_current_tenant",
    "set_current_user",
    "tenant_scope",
]
