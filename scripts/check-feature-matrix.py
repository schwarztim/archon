#!/usr/bin/env python3
"""Validate docs/feature-matrix.yaml against the codebase.

Hard mismatches (exit 1):
  - status_summary counts disagree with the actual entry counts.
  - A node executor file in backend/app/services/node_executors/ (other than
    __init__.py) has no entry in node_executors.
  - A node_type registered via @register(...) is missing from node_executors.

Soft warnings (exit 0, surfaced on stderr):
  - source_files entries that point at nonexistent files.
  - status=production entries with empty test_files.
  - Routes registered in main.py via app.include_router() whose router file
    is not referenced anywhere in rest_routes (we approximate this as: at
    least one rest_routes entry must reference the router's source file).

Usage:
  python3 scripts/check-feature-matrix.py
  python3 scripts/check-feature-matrix.py --strict   # warnings become errors
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    print(
        "FATAL: PyYAML is not installed. Install with: pip install pyyaml",
        file=sys.stderr,
    )
    sys.exit(2)


REPO_ROOT = Path(__file__).resolve().parent.parent
YAML_PATH = REPO_ROOT / "docs" / "feature-matrix.yaml"
EXECUTORS_DIR = REPO_ROOT / "backend" / "app" / "services" / "node_executors"
ROUTES_DIR = REPO_ROOT / "backend" / "app" / "routes"
MAIN_PY = REPO_ROOT / "backend" / "app" / "main.py"

VALID_STATUSES = {"production", "beta", "stub", "designed", "missing", "blocked"}

# Capture: @register("nodeType")
_REGISTER_RE = re.compile(r'@register\("([^"]+)"\)')

# Capture all import names that arrive from app.routes.X — used to know which
# router files are reachable from main.py.
_IMPORT_RE = re.compile(
    r"^\s*from\s+app\.routes\.([A-Za-z_][A-Za-z0-9_]*)\s+import",
    re.MULTILINE,
)


def _load_yaml() -> dict[str, Any]:
    if not YAML_PATH.exists():
        print(f"FATAL: {YAML_PATH} does not exist", file=sys.stderr)
        sys.exit(2)
    with YAML_PATH.open("r", encoding="utf-8") as fh:
        try:
            return yaml.safe_load(fh)
        except yaml.YAMLError as exc:
            print(f"FATAL: invalid YAML in {YAML_PATH}: {exc}", file=sys.stderr)
            sys.exit(2)


def _scan_executor_files() -> set[str]:
    """Return the set of executor file basenames (without .py), excluding __init__."""
    if not EXECUTORS_DIR.is_dir():
        return set()
    files: set[str] = set()
    for child in EXECUTORS_DIR.iterdir():
        if child.is_file() and child.suffix == ".py" and child.stem != "__init__":
            files.add(child.stem)
    return files


def _scan_registered_node_types() -> set[str]:
    """Return the set of canonical node_types registered via @register(...)."""
    if not EXECUTORS_DIR.is_dir():
        return set()
    types: set[str] = set()
    for child in EXECUTORS_DIR.glob("*.py"):
        if child.stem == "__init__":
            continue
        text = child.read_text(encoding="utf-8")
        for m in _REGISTER_RE.finditer(text):
            types.add(m.group(1))
    return types


def _scan_main_router_imports() -> set[str]:
    """Return the set of route module stems imported by main.py (e.g. {'agents','dlp',...})."""
    if not MAIN_PY.exists():
        return set()
    text = MAIN_PY.read_text(encoding="utf-8")
    return set(_IMPORT_RE.findall(text))


def _yaml_node_executor_ids(matrix: dict[str, Any]) -> set[str]:
    return {e["id"] for e in matrix["categories"]["node_executors"]}


def _yaml_route_source_basenames(matrix: dict[str, Any]) -> set[str]:
    """Return the set of route module stems referenced by rest_routes source_files."""
    stems: set[str] = set()
    for entry in matrix["categories"]["rest_routes"]:
        for src in entry.get("source_files", []) or []:
            p = Path(src)
            if "routes" in p.parts and p.suffix == ".py":
                stems.add(p.stem)
    return stems


def _yaml_status_counts(matrix: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {s: 0 for s in VALID_STATUSES}
    counts["total"] = 0
    for category in matrix["categories"].values():
        for entry in category:
            status = entry.get("status")
            if status not in VALID_STATUSES:
                # Defer reporting to validation step.
                continue
            counts[status] += 1
            counts["total"] += 1
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="treat soft warnings as hard failures",
    )
    args = parser.parse_args()

    matrix = _load_yaml()

    errors: list[str] = []
    warnings: list[str] = []

    # ---- Validate top-level shape -------------------------------------
    if not isinstance(matrix, dict) or "categories" not in matrix:
        errors.append("YAML missing top-level 'categories' key")
    else:
        for required_cat in (
            "node_executors",
            "rest_routes",
            "enterprise_capabilities",
            "orchestration_primitives",
            "observability",
            "infra_services",
        ):
            if required_cat not in matrix["categories"]:
                errors.append(f"YAML missing required category: {required_cat}")

    # ---- Validate every entry has required fields ---------------------
    for cat_name, entries in matrix.get("categories", {}).items():
        for i, entry in enumerate(entries or []):
            for required_field in ("id", "status"):
                if required_field not in entry:
                    errors.append(
                        f"{cat_name}[{i}]: missing required field '{required_field}'"
                    )
            if entry.get("status") not in VALID_STATUSES:
                errors.append(
                    f"{cat_name}[{i}] id={entry.get('id', '<unknown>')}: "
                    f"invalid status '{entry.get('status')}' "
                    f"(must be one of {sorted(VALID_STATUSES)})"
                )

    # ---- Cross-check status_summary ----------------------------------
    declared = matrix.get("status_summary", {})
    actual = _yaml_status_counts(matrix)
    for status in VALID_STATUSES:
        if declared.get(status, 0) != actual[status]:
            errors.append(
                f"status_summary.{status}={declared.get(status)} but actual entry count is {actual[status]}"
            )
    if declared.get("total", 0) != actual["total"]:
        errors.append(
            f"status_summary.total={declared.get('total')} but actual total is {actual['total']}"
        )

    # ---- Cross-check node executors ----------------------------------
    yaml_node_ids = _yaml_node_executor_ids(matrix)
    on_disk_files = _scan_executor_files()
    registered_types = _scan_registered_node_types()

    # Each on-disk file should produce at least one registered node_type
    # that appears in the YAML.
    missing_types = registered_types - yaml_node_ids
    if missing_types:
        errors.append(
            f"node_executors: registered node_types missing from YAML: {sorted(missing_types)}"
        )

    extra_types = yaml_node_ids - registered_types
    if extra_types:
        warnings.append(
            f"node_executors: YAML lists node_types not registered in code: {sorted(extra_types)}"
        )

    # Coverage check: every executor source file should be referenced by at
    # least one entry's source_files.
    referenced_basenames: set[str] = set()
    for entry in matrix["categories"]["node_executors"]:
        for src in entry.get("source_files", []) or []:
            p = Path(src)
            if "node_executors" in p.parts and p.suffix == ".py":
                referenced_basenames.add(p.stem)
    missing_files = on_disk_files - referenced_basenames
    if missing_files:
        errors.append(
            f"node_executors: executor files not referenced by any entry: {sorted(missing_files)}"
        )

    # ---- Cross-check route routers ------------------------------------
    yaml_route_stems = _yaml_route_source_basenames(matrix)
    main_imports = _scan_main_router_imports()
    missing_routers = main_imports - yaml_route_stems
    if missing_routers:
        warnings.append(
            f"rest_routes: routers imported in main.py but no rest_routes entry references "
            f"backend/app/routes/<name>.py: {sorted(missing_routers)}"
        )

    # ---- File existence / production has tests ------------------------
    for cat_name, entries in matrix["categories"].items():
        for entry in entries or []:
            for src in entry.get("source_files", []) or []:
                if not (REPO_ROOT / src).exists():
                    warnings.append(
                        f"{cat_name} id={entry.get('id')}: source_files entry does not exist: {src}"
                    )
            if entry.get("status") == "production" and not entry.get("test_files"):
                warnings.append(
                    f"{cat_name} id={entry.get('id')}: status=production but test_files is empty"
                )

    # ---- Report --------------------------------------------------------
    if warnings:
        print("[warnings]", file=sys.stderr)
        for w in warnings:
            print(f"  W: {w}", file=sys.stderr)

    if errors:
        print("[errors]", file=sys.stderr)
        for e in errors:
            print(f"  E: {e}", file=sys.stderr)
        return 1

    if args.strict and warnings:
        print(
            f"\nFAIL (strict mode): {len(warnings)} warning(s) treated as errors.",
            file=sys.stderr,
        )
        return 1

    print(
        f"OK: {actual['total']} entries validated "
        f"(production={actual['production']} beta={actual['beta']} "
        f"stub={actual['stub']} designed={actual['designed']} "
        f"missing={actual['missing']} blocked={actual['blocked']}); "
        f"{len(warnings)} warning(s)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
