#!/usr/bin/env python3
"""Frontend↔backend node-schema parity gate.

Phase 3, WS15. Walks the backend node executor registry and the frontend
``NodeKind`` discriminated union, compares them, and reports drift.

Inputs:
  - ``backend/app/services/node_executors/__init__.py`` —
    parsed for ``@register("xxxNode")`` decorators.
  - ``backend/app/services/node_executors/status_registry.py`` —
    parsed for the ``NODE_STATUS`` dict's keys.
  - ``frontend/src/types/nodes.ts`` —
    parsed for the ``NodeKind`` union and the per-kind ``Config`` interfaces.

Output: human-readable report. Exit code:
  - 0 if no DRIFT (warnings about missing config interfaces are allowed)
  - 1 if any DRIFT (a node registered backend missing frontend, or vice
    versa)

This is a CI gate — it is the structural enforcement that closes the
"canvas can ship a node config the backend rejects" failure mode. It is
intentionally simple regex-based parsing; adding ``@register`` or
``NodeKind`` requires updating *both* sides, and the gate runs in
``scripts/verify-contracts.sh``.
"""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_REGISTRY = (
    REPO_ROOT
    / "backend"
    / "app"
    / "services"
    / "node_executors"
    / "__init__.py"
)
BACKEND_STATUS = (
    REPO_ROOT
    / "backend"
    / "app"
    / "services"
    / "node_executors"
    / "status_registry.py"
)
BACKEND_EXECUTOR_DIR = (
    REPO_ROOT / "backend" / "app" / "services" / "node_executors"
)
FRONTEND_NODES = REPO_ROOT / "frontend" / "src" / "types" / "nodes.ts"


# ── Backend extractors ────────────────────────────────────────────────


_REGISTER_RE = re.compile(r'@register\(\s*"([A-Za-z0-9_]+)"\s*\)')


def extract_backend_node_types() -> set[str]:
    """Walk every ``.py`` file under the executor dir for ``@register("...")``.

    Walking the directory (rather than only ``__init__.py``) catches
    decorator-style registrations regardless of which module owns them —
    that's how the backend registry is actually populated.
    """
    if not BACKEND_EXECUTOR_DIR.is_dir():
        log.error("backend executor dir not found: %s", BACKEND_EXECUTOR_DIR)
        sys.exit(2)

    found: set[str] = set()
    for py in sorted(BACKEND_EXECUTOR_DIR.glob("*.py")):
        if py.name.startswith("_"):
            continue
        text = py.read_text(encoding="utf-8")
        for match in _REGISTER_RE.finditer(text):
            found.add(match.group(1))
    return found


_STATUS_LINE_RE = re.compile(
    r'^\s*"([A-Za-z0-9_]+)"\s*:\s*NodeStatus\.([A-Z_]+)\s*,\s*$',
)


def extract_backend_status_map() -> dict[str, str]:
    """Parse ``NODE_STATUS`` dict literal in ``status_registry.py``.

    Returns ``{node_type: "production"|"beta"|"stub"|"blocked"|"designed"}``.
    """
    if not BACKEND_STATUS.is_file():
        log.warning("backend status registry not found: %s", BACKEND_STATUS)
        return {}

    out: dict[str, str] = {}
    in_dict = False
    for line in BACKEND_STATUS.read_text(encoding="utf-8").splitlines():
        if "NODE_STATUS:" in line and "=" in line:
            in_dict = True
            continue
        if in_dict:
            stripped = line.strip()
            if stripped.startswith("}"):
                in_dict = False
                continue
            m = _STATUS_LINE_RE.match(line)
            if m:
                out[m.group(1)] = m.group(2).lower()
    return out


# ── Frontend extractors ───────────────────────────────────────────────


_NODE_KIND_BLOCK_RE = re.compile(
    r"export\s+type\s+NodeKind\s*=([\s\S]*?);",
    re.MULTILINE,
)
_NODE_KIND_VALUE_RE = re.compile(r'"([A-Za-z0-9_]+)"')


def extract_frontend_node_kinds() -> set[str]:
    """Parse the ``NodeKind`` union literal from ``frontend/src/types/nodes.ts``."""
    if not FRONTEND_NODES.is_file():
        log.error("frontend nodes.ts not found: %s", FRONTEND_NODES)
        sys.exit(2)

    text = FRONTEND_NODES.read_text(encoding="utf-8")
    block_match = _NODE_KIND_BLOCK_RE.search(text)
    if not block_match:
        log.error("could not locate ``export type NodeKind`` in %s", FRONTEND_NODES)
        sys.exit(2)

    block = block_match.group(1)
    return set(_NODE_KIND_VALUE_RE.findall(block))


# Capture both ``interface FooNodeConfig`` and ``type FooNodeConfig``.
# We use a permissive regex — exact form matters less than presence.
_CONFIG_NAME_RE = re.compile(
    r"\b(?:export\s+)?(?:interface|type)\s+([A-Z][A-Za-z0-9_]*)NodeConfig\b",
)


def extract_frontend_config_interfaces() -> set[str]:
    """Return the set of node_types that have a specific config interface.

    A config interface for ``llmNode`` is any declaration named
    ``LLMNodeConfig`` / ``LlmNodeConfig`` etc. We normalise by lower-casing
    the first letter and checking against the kind set passed in.
    """
    text = FRONTEND_NODES.read_text(encoding="utf-8")
    raw_names: set[str] = set()
    for match in _CONFIG_NAME_RE.finditer(text):
        raw_names.add(match.group(1) + "Node")

    # Lower the first character so ``LLMNodeConfig`` -> ``lLMNode``,
    # which is *not* what we want. Instead, build a lookup via case-insensitive
    # match against backend kinds.
    return raw_names


# ── Main parity diff ──────────────────────────────────────────────────


def main() -> int:
    backend_kinds = extract_backend_node_types()
    backend_status = extract_backend_status_map()
    frontend_kinds = extract_frontend_node_kinds()
    frontend_config_classes = extract_frontend_config_interfaces()

    log.info("=" * 70)
    log.info("Frontend↔backend node schema parity")
    log.info("=" * 70)
    log.info("Backend  registered (@register): %d nodes", len(backend_kinds))
    log.info("Frontend NodeKind union members: %d nodes", len(frontend_kinds))
    log.info("Backend  status_registry rows  : %d nodes", len(backend_status))
    log.info("")

    drift: list[str] = []
    warnings: list[str] = []

    # 1) Nodes registered backend but missing frontend NodeKind.
    backend_only = backend_kinds - frontend_kinds
    if backend_only:
        for name in sorted(backend_only):
            drift.append(
                f"DRIFT: backend registered '{name}' but frontend NodeKind "
                f"does not include it"
            )

    # 2) Nodes in frontend NodeKind but not registered backend.
    frontend_only = frontend_kinds - backend_kinds
    if frontend_only:
        for name in sorted(frontend_only):
            drift.append(
                f"DRIFT: frontend NodeKind includes '{name}' but backend "
                f"@register does not"
            )

    # 3) Production nodes without a specific Config interface (warning only).
    #
    # Build a case-insensitive lookup for frontend Config interfaces so that
    # ``LLMNodeConfig`` matches ``llmNode``, ``HTTPRequestNodeConfig`` matches
    # ``httpRequestNode``, etc.
    config_lookup_lower = {n.lower() for n in frontend_config_classes}
    for kind in sorted(backend_kinds & frontend_kinds):
        if backend_status.get(kind) == "production":
            if kind.lower() not in config_lookup_lower:
                warnings.append(
                    f"WARN: '{kind}' is backend status='production' but "
                    f"frontend has no specific *NodeConfig interface"
                )

    # ── Report ──────────────────────────────────────────────────────
    if drift:
        log.error("─" * 70)
        log.error("DRIFT (%d)", len(drift))
        log.error("─" * 70)
        for line in drift:
            log.error("  %s", line)

    if warnings:
        log.warning("─" * 70)
        log.warning("WARNINGS (%d) — non-fatal", len(warnings))
        log.warning("─" * 70)
        for line in warnings:
            log.warning("  %s", line)

    log.info("─" * 70)
    if drift:
        log.error("FAIL: %d DRIFT, %d warnings", len(drift), len(warnings))
        return 1

    log.info("OK: 0 DRIFT, %d warnings", len(warnings))
    return 0


if __name__ == "__main__":
    sys.exit(main())
