#!/usr/bin/env python3
"""scripts/check-grafana-metric-parity.py — Phase 5 metric drift gate.

Walks every Grafana dashboard JSON under infra/grafana/dashboards/ and every
Prometheus alert YAML under infra/monitoring/ (alerts/*.yaml plus the
`additionalPrometheusRulesMap` block of prometheus-values.yaml), extracts the
metric names referenced in each PromQL expression, and verifies that every
reference is registered in docs/metrics-catalog.md or actually emitted by
backend/app/middleware/metrics_middleware.py.

Exits non-zero if any dashboard / alert references a metric that is not
declared in the catalog. The catalog is the source of truth for the
W5.1 ↔ Phase 5 contract.

Usage:
    python3 scripts/check-grafana-metric-parity.py
    python3 scripts/check-grafana-metric-parity.py --strict   # treat catalog-only metrics as missing-from-emitter

Exit codes:
    0   parity OK
    1   drift detected
    2   structural problem (missing files / parse errors)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent
DASHBOARDS_DIR = REPO_ROOT / "infra" / "grafana" / "dashboards"
ALERTS_DIR = REPO_ROOT / "infra" / "monitoring" / "alerts"
PROM_VALUES = REPO_ROOT / "infra" / "monitoring" / "prometheus-values.yaml"
CATALOG = REPO_ROOT / "docs" / "metrics-catalog.md"
EMITTER = REPO_ROOT / "backend" / "app" / "middleware" / "metrics_middleware.py"

# Metric naming convention: `archon_*` (project metrics).
# We also accept Prometheus / kube-state metrics that are not Archon-emitted —
# those are out of scope for the catalog, but we surface them for visibility.
METRIC_PREFIX = "archon_"

# Identifier-ish token that may be a metric name. Excludes Prom keywords.
_METRIC_TOKEN = re.compile(r"\b([a-zA-Z_:][a-zA-Z0-9_:]*)")

# Tokens that look like metric names but are PromQL keywords / functions.
_PROMQL_RESERVED = {
    "and", "or", "unless", "if", "by", "without", "on", "ignoring",
    "group_left", "group_right", "offset", "bool", "le", "method", "path",
    "status", "tenant_id", "provider", "model", "kind", "node_type",
    "reason", "from_provider", "to_provider", "severity", "pattern", "action",
    "namespace", "pod", "container", "persistentvolumeclaim", "job", "le",
    "worker_id", "pool",
}
_PROMQL_FUNCTIONS = {
    "rate", "irate", "sum", "avg", "min", "max", "count", "topk", "bottomk",
    "increase", "delta", "deriv", "histogram_quantile", "clamp_min",
    "clamp_max", "abs", "ceil", "floor", "round", "sqrt", "exp", "ln", "log2",
    "log10", "time", "vector", "scalar", "label_replace", "label_join",
    "absent", "absent_over_time", "changes", "resets", "sort", "sort_desc",
    "predict_linear", "holt_winters", "stddev", "stdvar", "quantile",
    "stddev_over_time", "stdvar_over_time", "avg_over_time", "min_over_time",
    "max_over_time", "sum_over_time", "count_over_time", "quantile_over_time",
    "last_over_time", "humanizePercentage", "humanize", "humanizeDuration",
    "label_values",
}


def extract_metrics_from_expr(expr: str) -> set[str]:
    """Return the set of metric names referenced in a PromQL expression."""
    metrics: set[str] = set()
    if not expr:
        return metrics
    # Strip string literals — labels values (e.g., status="failed") are not metrics.
    expr_no_strings = re.sub(r'"[^"]*"', "", expr)
    expr_no_strings = re.sub(r"'[^']*'", "", expr_no_strings)
    for match in _METRIC_TOKEN.finditer(expr_no_strings):
        token = match.group(1)
        if token in _PROMQL_RESERVED or token in _PROMQL_FUNCTIONS:
            continue
        # Numbers / pure digits never match the regex, but be defensive.
        if token.isdigit():
            continue
        # Heuristic: keep tokens that look like metric names — must contain
        # an underscore (Prometheus convention) or have the `archon_` prefix.
        if token.startswith(METRIC_PREFIX) or token.startswith("up"):
            metrics.add(token)
        elif "_" in token and (token.endswith("_total") or token.endswith("_seconds")
                                or token.endswith("_bucket") or token.endswith("_sum")
                                or token.endswith("_count") or token.endswith("_bytes")):
            metrics.add(token)
    return metrics


def normalize_metric(name: str) -> str:
    """Strip histogram suffixes — `_bucket`, `_sum`, `_count` collapse to base."""
    for suffix in ("_bucket", "_sum", "_count"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def collect_dashboard_metrics() -> dict[str, set[str]]:
    """Return {dashboard_path: {metric, ...}}."""
    if not DASHBOARDS_DIR.exists():
        sys.stderr.write(f"✗ Dashboards directory missing: {DASHBOARDS_DIR}\n")
        sys.exit(2)
    out: dict[str, set[str]] = {}
    for path in sorted(DASHBOARDS_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError as e:
            sys.stderr.write(f"✗ Cannot parse {path}: {e}\n")
            sys.exit(2)
        metrics: set[str] = set()
        for panel in data.get("panels", []) or []:
            for tgt in panel.get("targets", []) or []:
                expr = tgt.get("expr") or ""
                metrics |= extract_metrics_from_expr(expr)
        # Templating queries may reference label_values(<metric>, label).
        for tpl in (data.get("templating") or {}).get("list", []) or []:
            tpl_query = tpl.get("query")
            if isinstance(tpl_query, str):
                metrics |= extract_metrics_from_expr(tpl_query)
            elif isinstance(tpl_query, dict):
                metrics |= extract_metrics_from_expr(tpl_query.get("query", ""))
        out[str(path.relative_to(REPO_ROOT))] = metrics
    return out


def _load_yaml_text(text: str) -> dict | list:
    """Minimal YAML loader. Prefer PyYAML if available, else fallback."""
    try:
        import yaml  # type: ignore
        return yaml.safe_load(text)
    except ImportError:
        # Best-effort: extract `expr:` lines and synthesize a flat structure.
        # Sufficient because we only need expr strings for parity.
        rules: list[dict[str, str]] = []
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("expr:"):
                # Single-line expr.
                expr = stripped.split(":", 1)[1].strip()
                if expr.startswith("|"):
                    # Multiline — placeholder; will be re-stitched below.
                    expr = ""
                if expr:
                    rules.append({"expr": expr})
        # Re-stitch multiline `expr: |` blocks.
        lines = text.splitlines()
        i = 0
        while i < len(lines):
            line = lines[i]
            if line.strip().startswith("expr:") and line.strip().endswith("|"):
                indent = len(line) - len(line.lstrip())
                buf: list[str] = []
                j = i + 1
                while j < len(lines):
                    nxt = lines[j]
                    if not nxt.strip():
                        j += 1
                        continue
                    nxt_indent = len(nxt) - len(nxt.lstrip())
                    if nxt_indent <= indent:
                        break
                    buf.append(nxt.strip())
                    j += 1
                rules.append({"expr": " ".join(buf)})
                i = j
                continue
            i += 1
        return {"_fallback_rules": rules}


def collect_alert_metrics() -> dict[str, set[str]]:
    """Return {alert_path: {metric, ...}}."""
    out: dict[str, set[str]] = {}

    # 1) Standalone alerts/*.yaml
    if ALERTS_DIR.exists():
        for path in sorted(ALERTS_DIR.glob("*.yaml")):
            data = _load_yaml_text(path.read_text())
            metrics = _extract_alert_metrics(data)
            out[str(path.relative_to(REPO_ROOT))] = metrics

    # 2) prometheus-values.yaml additionalPrometheusRulesMap
    if PROM_VALUES.exists():
        data = _load_yaml_text(PROM_VALUES.read_text())
        metrics = _extract_alert_metrics(data)
        out[str(PROM_VALUES.relative_to(REPO_ROOT))] = metrics

    return out


def _extract_alert_metrics(data) -> set[str]:
    metrics: set[str] = set()
    if data is None:
        return metrics
    # Fallback path used when PyYAML is missing.
    if isinstance(data, dict) and "_fallback_rules" in data:
        for rule in data["_fallback_rules"]:
            metrics |= extract_metrics_from_expr(rule.get("expr", ""))
        return metrics
    # Walk the structure looking for `expr:` keys at any depth.
    def _walk(node) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "expr" and isinstance(v, str):
                    metrics.update(extract_metrics_from_expr(v))
                else:
                    _walk(v)
        elif isinstance(node, list):
            for item in node:
                _walk(item)
    _walk(data)
    return metrics


def load_catalog_metrics() -> set[str]:
    """Pull `archon_*` (and supporting) metric names out of metrics-catalog.md."""
    if not CATALOG.exists():
        sys.stderr.write(f"✗ Catalog missing: {CATALOG}\n")
        sys.exit(2)
    text = CATALOG.read_text()
    metrics: set[str] = set()
    # Catalog rows are markdown tables: | `metric_name` | type | labels | notes |
    for match in re.finditer(r"`(archon_[a-zA-Z0-9_]+)`", text):
        metrics.add(match.group(1))
    return metrics


def load_emitter_metrics() -> set[str]:
    """Best-effort scan of metrics_middleware.py for emitted metric names."""
    if not EMITTER.exists():
        return set()
    text = EMITTER.read_text()
    metrics: set[str] = set()
    for match in re.finditer(r'archon_[a-zA-Z0-9_]+', text):
        metrics.add(match.group(0))
    return metrics


def report(consumer_metrics: dict[str, set[str]], catalog: set[str],
           emitter: set[str], strict: bool) -> int:
    rc = 0
    catalog_normalized = {normalize_metric(m) for m in catalog}
    emitter_normalized = {normalize_metric(m) for m in emitter}
    all_consumer: set[str] = set()
    print("Metric parity check")
    print("=" * 60)
    for source, metrics in consumer_metrics.items():
        if not metrics:
            continue
        archon = sorted(m for m in metrics if m.startswith(METRIC_PREFIX))
        if not archon:
            print(f"  {source}: (no archon_* metrics)")
            continue
        print(f"\n  {source}:")
        for m in archon:
            base = normalize_metric(m)
            in_catalog = base in catalog_normalized
            in_emitter = base in emitter_normalized
            mark = "OK" if in_catalog else "DRIFT"
            note = "" if in_catalog else " ← NOT IN CATALOG"
            if in_catalog and not in_emitter:
                note = " (catalog-only — W5.1 to wire emitter)"
                if strict:
                    mark = "DRIFT"
                    rc = 1
            print(f"    [{mark}] {m}{note}")
            if not in_catalog:
                rc = 1
        all_consumer |= set(archon)

    # Reverse check — anything emitted but unused (informational only).
    base_consumer = {normalize_metric(m) for m in all_consumer}
    unused = sorted(emitter_normalized - base_consumer)
    if unused:
        print("\n  Emitted but not used by any dashboard/alert (informational):")
        for m in unused:
            print(f"    [INFO] {m}")

    print("\n" + "=" * 60)
    if rc == 0:
        print("Parity OK — 0 DRIFT.")
    else:
        print("Parity FAILED — see DRIFT lines above.")
    return rc


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--strict", action="store_true",
                        help="Treat catalog-only metrics (not yet emitted) as DRIFT.")
    args = parser.parse_args(list(argv) if argv is not None else None)

    catalog = load_catalog_metrics()
    emitter = load_emitter_metrics()
    consumer = {**collect_dashboard_metrics(), **collect_alert_metrics()}
    return report(consumer, catalog, emitter, strict=args.strict)


if __name__ == "__main__":
    sys.exit(main())
