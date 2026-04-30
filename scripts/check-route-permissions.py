#!/usr/bin/env python3
"""scripts/check-route-permissions.py — Phase 4 / WS13 route permission audit.

Walks ``app.routes`` on the live FastAPI app and classifies every route as:

  * authenticated   — route's dependency tree contains a known auth dependency
  * allowlisted     — route + method are present in the public allowlist file
  * UNAUTHENTICATED — neither of the above (drift!)

Exit codes
----------
0  — every route is authenticated or allowlisted.
1  — at least one route is unauthenticated and not on the allowlist (drift).
2  — a route in the allowlist does NOT exist in the app (stale allowlist).

The script is fail-closed: any introspection error exits non-zero with a
diagnostic message.  Set ``ARCHON_AUTH_DEV_MODE=true`` so the live app boots
without an external Keycloak / Vault.

Usage
-----
    python3 scripts/check-route-permissions.py

The allowlist lives at ``scripts/route-permissions-allowlist.txt``.  Each
line is ``<METHOD> <path>`` (lines starting with ``#`` are comments).
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

# Make the live app importable.
REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

# Bootstrap the app without external dependencies.
os.environ.setdefault("ARCHON_AUTH_DEV_MODE", "true")
os.environ.setdefault("ARCHON_RATE_LIMIT_ENABLED", "false")

ALLOWLIST_PATH = REPO_ROOT / "scripts" / "route-permissions-allowlist.txt"

# Names of dependency callables that count as authentication gates.  Any
# route whose dependency tree contains one of these is considered protected.
AUTH_DEPENDENCY_NAMES: frozenset[str] = frozenset(
    {
        "get_current_user",
        "require_auth",
        "require_mfa",
        "require_admin",
        "require_role",
        "require_permission",
        "require_active_user",
        "verify_api_key",
        "require_api_key",
    }
)


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


def load_allowlist(path: Path) -> set[tuple[str, str]]:
    """Parse the allowlist file → set of ``(METHOD, path)`` tuples."""
    if not path.is_file():
        sys.stderr.write(f"error: allowlist not found at {path}\n")
        sys.exit(2)

    entries: set[tuple[str, str]] = set()
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            sys.stderr.write(
                f"error: malformed allowlist line: {raw!r} (expected '<METHOD> <path>')\n"
            )
            sys.exit(2)
        method, route_path = parts
        entries.add((method.upper(), route_path))
    return entries


def discover_routes() -> list[tuple[str, str, object]]:
    """Return ``[(method, path, dependant), ...]`` for every route in the app."""
    try:
        from app.main import app
        from fastapi.routing import APIRoute
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"error: could not import live app: {exc}\n")
        sys.exit(2)

    routes: list[tuple[str, str, object]] = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        methods = (route.methods or set()) - {"HEAD"}
        for method in methods:
            routes.append((method, route.path, route.dependant))
    return routes


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def has_auth_dependency(dependant: object) -> bool:
    """Walk the dependency tree to find any auth-gate dependency.

    The dependant graph is recursive; sub-dependencies are themselves
    ``Dependant`` objects.  Anything in :data:`AUTH_DEPENDENCY_NAMES`
    counts as a gate.
    """
    if dependant is None:
        return False

    call = getattr(dependant, "call", None)
    name = getattr(call, "__name__", None) if call is not None else None
    if name in AUTH_DEPENDENCY_NAMES:
        return True

    for sub in getattr(dependant, "dependencies", []) or []:
        if has_auth_dependency(sub):
            return True

    # Security schemes (oauth2_scheme et al.) are wrapped as security_requirements.
    for sec in getattr(dependant, "security_requirements", []) or []:
        scheme = getattr(sec, "security_scheme", None)
        sec_name = getattr(scheme, "scheme_name", None) or getattr(
            scheme, "__class__", type(scheme)
        ).__name__
        # An OAuth2/HTTP-Bearer scheme by itself does not enforce auth (the
        # underlying dependency does), so we ignore these here.  Names left
        # for documentation.
        _ = sec_name

    return False


@dataclass
class Report:
    authenticated: list[tuple[str, str]]
    allowlisted: list[tuple[str, str]]
    drift: list[tuple[str, str]]
    stale_allowlist: list[tuple[str, str]]

    @property
    def total(self) -> int:
        return (
            len(self.authenticated) + len(self.allowlisted) + len(self.drift)
        )


def classify(
    routes: list[tuple[str, str, object]],
    allowlist: set[tuple[str, str]],
) -> Report:
    """Classify every route as authenticated / allowlisted / drift."""
    authenticated: list[tuple[str, str]] = []
    allowlisted: list[tuple[str, str]] = []
    drift: list[tuple[str, str]] = []

    actual: set[tuple[str, str]] = set()
    for method, path, dep in routes:
        actual.add((method, path))
        if has_auth_dependency(dep):
            authenticated.append((method, path))
        elif (method, path) in allowlist:
            allowlisted.append((method, path))
        else:
            drift.append((method, path))

    stale = sorted(allowlist - actual)
    return Report(
        authenticated=sorted(authenticated),
        allowlisted=sorted(allowlisted),
        drift=sorted(drift),
        stale_allowlist=stale,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    routes = discover_routes()
    allowlist = load_allowlist(ALLOWLIST_PATH)
    report = classify(routes, allowlist)

    print(
        f"check-route-permissions: total={report.total} "
        f"auth={len(report.authenticated)} "
        f"allowlisted={len(report.allowlisted)} "
        f"drift={len(report.drift)} "
        f"stale_allowlist={len(report.stale_allowlist)}"
    )

    if report.stale_allowlist:
        print()
        print(
            "STALE ALLOWLIST — these entries do not match any registered route:"
        )
        for method, path in report.stale_allowlist:
            print(f"  {method:6s} {path}")

    if report.drift:
        print()
        print(
            "PUBLIC-BUT-NOT-ALLOWLISTED — routes lack auth and aren't in the allowlist:"
        )
        for method, path in report.drift:
            print(f"  {method:6s} {path}")

    if report.drift:
        return 1
    if report.stale_allowlist:
        return 2
    print("OK")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
