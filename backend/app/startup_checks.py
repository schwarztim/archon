"""Production startup assertions — ADR-005 enforcement layer.

These checks run on FastAPI app startup BEFORE the HTTP listener binds. They
guarantee that a process classified as production / staging cannot serve
traffic with unsafe defaults: dev JWT secrets, sqlite databases, in-memory
checkpointers, AUTH_DEV_MODE, etc.

Failures aggregate into a single :class:`StartupCheckFailed` exception which
the caller converts to ``SystemExit(1)`` so the process exits non-zero before
binding the listener.

Test environments (``ARCHON_ENV in {dev, test}`` or unset) are unaffected —
production-only checks become no-ops.
"""

from __future__ import annotations

import logging
import os
from typing import Iterable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Environment classification
# ---------------------------------------------------------------------------

_DURABLE_ENVS: frozenset[str] = frozenset({"production", "staging"})

# Known dev/test JWT secrets that must never appear in production. Compared
# case-insensitively. Anything matching these (or starting with "dev-" /
# "test-" / "change") is rejected.
_DEV_JWT_SECRETS: frozenset[str] = frozenset(
    {
        "dev-secret",
        "changeme",
        "change-me",
        "change-me-in-production",
        "test-secret",
        "secret",
        "default",
        "insecure",
    }
)


def _archon_env() -> str:
    return os.getenv("ARCHON_ENV", "dev").lower().strip()


def _is_durable_env() -> bool:
    return _archon_env() in _DURABLE_ENVS


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class StartupCheckFailed(RuntimeError):
    """Aggregate startup-check failure.

    Raised when one or more production-mode checks fail. The caller logs the
    error and exits the process with non-zero status before the API listener
    binds.
    """

    def __init__(self, failures: list[str]) -> None:
        self.failures = failures
        msg = (
            f"Startup checks failed ({len(failures)} issue"
            f"{'s' if len(failures) != 1 else ''}):\n  - "
            + "\n  - ".join(failures)
        )
        super().__init__(msg)


# ---------------------------------------------------------------------------
# Individual checks (each returns failure-string or None)
# ---------------------------------------------------------------------------


def _check_jwt_secret() -> str | None:
    """Reject dev JWT secrets in durable environments."""
    if not _is_durable_env():
        return None
    secret = (
        os.getenv("ARCHON_JWT_SECRET")
        or os.getenv("JWT_SECRET")
        or ""
    ).strip()

    if not secret:
        # Pull from settings if env not set.
        try:
            from app.config import settings  # noqa: PLC0415

            secret = (settings.JWT_SECRET or "").strip()
        except Exception as exc:  # noqa: BLE001
            logger.debug("could not read settings.JWT_SECRET: %s", exc)
            secret = ""

    if not secret:
        return "JWT_SECRET is empty in production — set ARCHON_JWT_SECRET to a strong random value"

    lower = secret.lower()
    if lower in _DEV_JWT_SECRETS:
        return (
            f"JWT_SECRET is a known development default ('{secret}') — "
            "set ARCHON_JWT_SECRET to a strong random value"
        )
    if lower.startswith(("dev-", "test-", "change", "insecure", "default")):
        return (
            f"JWT_SECRET starts with a development prefix ('{secret[:16]}...') — "
            "set ARCHON_JWT_SECRET to a strong random value"
        )
    if len(secret) < 32:
        return (
            f"JWT_SECRET is too short ({len(secret)} chars) — "
            "use at least 32 characters of random entropy in production"
        )
    return None


def _check_auth_dev_mode() -> str | None:
    """AUTH_DEV_MODE must not be true in durable environments."""
    if not _is_durable_env():
        return None
    raw = (os.getenv("ARCHON_AUTH_DEV_MODE") or os.getenv("AUTH_DEV_MODE") or "").strip().lower()
    truthy = {"1", "true", "yes", "on"}
    if raw in truthy:
        return (
            "AUTH_DEV_MODE=true in production — disable ARCHON_AUTH_DEV_MODE before "
            "serving traffic (Keycloak/OIDC must be the auth source)"
        )
    # Also consult settings as a fallback.
    if not raw:
        try:
            from app.config import settings  # noqa: PLC0415

            if getattr(settings, "AUTH_DEV_MODE", False):
                return (
                    "AUTH_DEV_MODE=true (from settings) in production — disable it before "
                    "serving traffic"
                )
        except Exception as exc:  # noqa: BLE001
            logger.debug("could not read settings.AUTH_DEV_MODE: %s", exc)
    return None


def _check_langgraph_checkpointing() -> str | None:
    """Reject LANGGRAPH_CHECKPOINTING=memory (or disabled) in durable envs."""
    if not _is_durable_env():
        return None
    raw = (os.getenv("LANGGRAPH_CHECKPOINTING") or "").strip().lower()
    if raw == "memory":
        return (
            "LANGGRAPH_CHECKPOINTING=memory in production — Postgres checkpointing "
            "is mandatory (ADR-005). Unset or set to 'postgres'."
        )
    if raw in {"false", "0", "off", "none", "disabled"}:
        return (
            f"LANGGRAPH_CHECKPOINTING={raw} in production — checkpointing cannot be "
            "disabled. Unset or set to 'postgres'."
        )
    return None


def _check_tenant_context_active() -> str | None:
    """Reject ARCHON_ENTERPRISE_STRICT_TENANT=false in durable environments.

    Phase 4 / WS12. Strict tenant enforcement must be on in production /
    staging. In ``dev`` / ``test`` environments the flag is optional —
    the absence of the env var resolves to "strict in durable, lax
    elsewhere" inside ``tenant_middleware._strict_enabled`` — but an
    explicit ``false`` overrides that and is unsafe.
    """
    if not _is_durable_env():
        return None
    raw = os.getenv("ARCHON_ENTERPRISE_STRICT_TENANT", "").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return (
            "ARCHON_ENTERPRISE_STRICT_TENANT is disabled in production — "
            "tenant isolation requires strict mode (default-tenant / "
            "zero-UUID fallback must be rejected)."
        )
    return None


def _check_database_url() -> str | None:
    """Verify DATABASE_URL is present and not sqlite (durable env only)."""
    url = (
        os.getenv("ARCHON_DATABASE_URL")
        or os.getenv("DATABASE_URL")
        or ""
    ).strip()
    if not url:
        try:
            from app.config import settings  # noqa: PLC0415

            url = (settings.DATABASE_URL or "").strip()
        except Exception as exc:  # noqa: BLE001
            logger.debug("could not read settings.DATABASE_URL: %s", exc)
            url = ""

    if not url:
        return "DATABASE_URL is not configured — set ARCHON_DATABASE_URL"

    if not _is_durable_env():
        return None

    lower = url.lower()
    if lower.startswith("sqlite"):
        return (
            f"DATABASE_URL uses sqlite ({url}) in production — "
            "PostgreSQL is required for durability."
        )
    return None


async def _check_checkpointer_is_postgres() -> str | None:
    """Initialise the checkpointer and verify it is the Postgres backend.

    In durable environments this MUST return an instance of the
    AsyncPostgresSaver class. MemorySaver is rejected because it is
    non-durable and ADR-005 forbids it.
    """
    if not _is_durable_env():
        return None
    try:
        from app.langgraph.checkpointer import (  # noqa: PLC0415
            CheckpointerDurabilityFailed,
            get_checkpointer,
        )

        try:
            saver = await get_checkpointer()
        except CheckpointerDurabilityFailed as exc:
            return f"checkpointer initialisation failed: {exc}"

        if saver is None:
            return (
                "checkpointer returned None in production — durability requires "
                "a Postgres saver"
            )

        cls_name = type(saver).__name__
        # Reject anything other than the Postgres saver.
        if "Postgres" not in cls_name:
            return (
                f"checkpointer returned {cls_name}, expected AsyncPostgresSaver — "
                "production must use a durable Postgres backend"
            )
    except Exception as exc:  # noqa: BLE001
        return f"checkpointer verification raised {type(exc).__name__}: {exc}"
    return None


# ---------------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------------


def _collect_sync_failures() -> list[str]:
    """Run all synchronous checks and collect non-None failures."""
    checks: Iterable = (
        _check_database_url,
        _check_jwt_secret,
        _check_auth_dev_mode,
        _check_langgraph_checkpointing,
        _check_tenant_context_active,
    )
    failures: list[str] = []
    for check in checks:
        result = check()
        if result:
            failures.append(result)
    return failures


async def run_startup_checks() -> None:
    """Execute startup assertions and raise on failure.

    This MUST run before the API listener binds. On any failure a structured
    CRITICAL log line is emitted and :class:`StartupCheckFailed` is raised.
    The caller (``app.main``) wraps the call so the FastAPI lifespan exits
    with a non-zero status code instead of serving traffic with bad config.
    """
    failures = _collect_sync_failures()

    # Async check: actually exercise the checkpointer factory and verify
    # the backend is Postgres. Skipped outside durable envs.
    ckpt_failure = await _check_checkpointer_is_postgres()
    if ckpt_failure:
        failures.append(ckpt_failure)

    if not failures:
        if _is_durable_env():
            logger.info("startup_checks: passed (env=%s)", _archon_env())
        return

    logger.critical(
        "startup_checks_failed",
        extra={
            "event": "startup_checks_failed",
            "archon_env": _archon_env(),
            "failure_count": len(failures),
            "failures": failures,
        },
    )
    raise StartupCheckFailed(failures)
