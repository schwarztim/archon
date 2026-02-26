"""Tests for auth middleware helper functions in app.services.auth."""

from __future__ import annotations

from uuid import UUID

import pytest

from app.interfaces.models import UserClaims
from app.services.auth import (
    build_audit_context,
    extract_actor_id,
    require_any_role,
    require_owner_or_role,
    require_role,
)


# ── Fixed UUIDs ─────────────────────────────────────────────────────

_USER_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
_RESOURCE_OWNER_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


def _claims(
    *,
    user_id: str = _USER_ID,
    email: str = "alice@example.com",
    roles: list[str] | None = None,
) -> UserClaims:
    """Build a UserClaims instance for testing."""
    return UserClaims(
        user_id=user_id,
        email=email,
        roles=roles or [],
    )


# ── require_role ────────────────────────────────────────────────────


def test_require_role_passes_when_role_present() -> None:
    """No error raised when the user holds the required role."""
    require_role(_claims(roles=["admin"]), "admin")


def test_require_role_raises_when_role_missing() -> None:
    """ValueError raised when the user does not hold the required role."""
    with pytest.raises(ValueError, match="Missing required role"):
        require_role(_claims(roles=["developer"]), "admin")


def test_require_role_raises_on_empty_roles() -> None:
    """ValueError raised when the user has no roles at all."""
    with pytest.raises(ValueError, match="Missing required role"):
        require_role(_claims(roles=[]), "admin")


# ── require_any_role ────────────────────────────────────────────────


def test_require_any_role_passes_with_one_match() -> None:
    """No error when at least one of the required roles is present."""
    require_any_role(_claims(roles=["viewer"]), ["admin", "viewer"])


def test_require_any_role_raises_with_no_match() -> None:
    """ValueError raised when none of the required roles are present."""
    with pytest.raises(ValueError, match="Requires one of roles"):
        require_any_role(_claims(roles=["viewer"]), ["admin", "superadmin"])


def test_require_any_role_raises_on_empty_roles() -> None:
    """ValueError raised when user roles are empty."""
    with pytest.raises(ValueError, match="Requires one of roles"):
        require_any_role(_claims(roles=[]), ["admin"])


# ── require_owner_or_role ───────────────────────────────────────────


def test_require_owner_or_role_passes_when_owner() -> None:
    """No error when user is the resource owner."""
    owner_id = UUID(_USER_ID)
    require_owner_or_role(_claims(), owner_id, "admin")


def test_require_owner_or_role_passes_when_has_role() -> None:
    """No error when user holds the required role (not owner)."""
    require_owner_or_role(
        _claims(roles=["admin"]),
        _RESOURCE_OWNER_ID,
        "admin",
    )


def test_require_owner_or_role_raises_when_neither() -> None:
    """ValueError when user is neither owner nor has the role."""
    with pytest.raises(ValueError, match="Access denied"):
        require_owner_or_role(
            _claims(roles=["viewer"]),
            _RESOURCE_OWNER_ID,
            "admin",
        )


# ── extract_actor_id ────────────────────────────────────────────────


def test_extract_actor_id_returns_uuid() -> None:
    """extract_actor_id returns a UUID parsed from claims.user_id."""
    result = extract_actor_id(_claims())
    assert isinstance(result, UUID)
    assert result == UUID(_USER_ID)


# ── build_audit_context ─────────────────────────────────────────────


def test_build_audit_context_returns_dict() -> None:
    """build_audit_context returns a dict with email and roles."""
    ctx = build_audit_context(_claims(email="bob@example.com", roles=["admin"]))
    assert ctx["actor_email"] == "bob@example.com"
    assert ctx["actor_roles"] == ["admin"]


def test_build_audit_context_empty_roles() -> None:
    """build_audit_context handles empty roles list."""
    ctx = build_audit_context(_claims(roles=[]))
    assert ctx["actor_roles"] == []
