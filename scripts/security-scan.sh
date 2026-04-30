#!/usr/bin/env bash
# scripts/security-scan.sh — runs `safety check` with severity threshold gating.
#
# Exit non-zero on findings AT OR ABOVE the configured severity that are NOT
# in .github/security-allowlist.json. Exit 0 on lower-severity findings or
# allowlisted findings (logged as warnings).
#
# Usage:
#   bash scripts/security-scan.sh [--threshold high|critical]
#   bash scripts/security-scan.sh --threshold high
#
# Environment:
#   SCAN_REQUIREMENTS  Path to requirements.txt (default: backend/requirements.txt)
#
# Exit codes:
#   0 — no findings at/above threshold (or all allowlisted)
#   1 — findings at/above threshold not in allowlist
#   2 — tool not installed or scan output unparseable

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd -P)"
cd "$REPO_ROOT"

# Argument parsing — accept `--threshold X` or positional `X`.
THRESHOLD="high"
if [ "${1:-}" = "--threshold" ] && [ -n "${2:-}" ]; then
  THRESHOLD="$2"
elif [ -n "${1:-}" ] && [ "${1:0:2}" != "--" ]; then
  THRESHOLD="$1"
fi

ALLOWLIST=".github/security-allowlist.json"
REQ_FILE="${SCAN_REQUIREMENTS:-backend/requirements.txt}"

if ! command -v safety >/dev/null 2>&1; then
  echo "ERROR: 'safety' not installed. Run: pip install safety" >&2
  exit 2
fi

if [ ! -f "$REQ_FILE" ]; then
  echo "ERROR: requirements file not found: $REQ_FILE" >&2
  exit 2
fi

# Run scan, capture JSON. `safety check` exits non-zero when it finds vulns —
# that's expected; we parse the JSON ourselves to apply severity gating.
TMP=$(mktemp)
trap 'rm -f "$TMP"' EXIT

# Run safety. Trap non-zero so the script doesn't exit prematurely; we read
# the JSON regardless of exit code.
set +e
safety check --file "$REQ_FILE" --output json > "$TMP" 2>/dev/null
set -e

# Parse: count findings >= threshold not in allowlist.
#
# safety 3.x emits a deprecation banner before AND after the JSON object on
# stdout. We use json.JSONDecoder().raw_decode() to extract the first JSON
# object and ignore surrounding text. The 2.x format (a bare list) is also
# supported via fallback.
python3 - <<PYEOF
import json
import sys

threshold = "$THRESHOLD".lower()
levels = {"low": 1, "medium": 2, "high": 3, "critical": 4}
need = levels.get(threshold, 3)

with open("$TMP") as f:
    raw = f.read()

if not raw.strip():
    print(f"TOTAL=0 HARD=0 ALLOWLISTED=0 THRESHOLD={threshold}")
    print("(safety produced no output — assuming clean scan)")
    sys.exit(0)

# Strip leading non-JSON text (banner) and decode the first JSON object.
start = raw.find("{")
if start < 0:
    start = raw.find("[")
if start < 0:
    print(f"SCAN_OUTPUT_UNPARSEABLE: no JSON object/array found", file=sys.stderr)
    sys.exit(2)

try:
    decoder = json.JSONDecoder()
    data, _ = decoder.raw_decode(raw[start:])
except json.JSONDecodeError as e:
    print(f"SCAN_OUTPUT_UNPARSEABLE: {e}", file=sys.stderr)
    sys.exit(2)

allow = set()
try:
    with open("$ALLOWLIST") as f:
        allowdata = json.load(f)
        allow = set(allowdata.get("cve_ids", []))
except FileNotFoundError:
    pass
except json.JSONDecodeError as e:
    print(f"WARNING: $ALLOWLIST is invalid JSON: {e}", file=sys.stderr)

# Normalize across safety output versions:
#   - 2.x: top-level is a list of vulnerability dicts
#   - 3.x: top-level is a dict with vulnerabilities list +
#          affected_packages dict + report_meta summary
if isinstance(data, list):
    vulns = data
elif isinstance(data, dict):
    vulns = list(data.get("vulnerabilities") or [])
    # If the flat list is empty but affected_packages dict has entries,
    # flatten its per-package vulnerability arrays into the same shape.
    if not vulns:
        affected = data.get("affected_packages") or {}
        if isinstance(affected, dict):
            for pkg_name, pkg_data in affected.items():
                pkg_vulns = (pkg_data or {}).get("vulnerabilities", [])
                for v in pkg_vulns:
                    if "package_name" not in v:
                        v["package_name"] = pkg_name
                    vulns.append(v)
else:
    vulns = []

def vuln_severity(v):
    sev = v.get("severity")
    if isinstance(sev, dict):
        sev = sev.get("source") or sev.get("cvssv3", {}).get("base_severity") or ""
    return (sev or v.get("cvssv3_severity") or "").lower()

def vuln_id(v):
    return v.get("vulnerability_id") or v.get("cve") or v.get("id") or ""

allowlisted = [v for v in vulns if vuln_id(v) in allow]
hard = [
    v for v in vulns
    if levels.get(vuln_severity(v), 0) >= need
    and vuln_id(v) not in allow
]

print(
    f"TOTAL={len(vulns)} HARD={len(hard)} "
    f"ALLOWLISTED={len(allowlisted)} THRESHOLD={threshold}"
)

# Surface report_meta summary for traceability when present (safety 3.x).
if isinstance(data, dict):
    meta = data.get("report_meta") or {}
    if meta:
        found = meta.get("vulnerabilities_found")
        ignored = meta.get("vulnerabilities_ignored")
        if found is not None or ignored is not None:
            print(f"  (report_meta: vulnerabilities_found={found} vulnerabilities_ignored={ignored})")

if allowlisted:
    print()
    print(f"  Allowlisted findings ({len(allowlisted)} — re-review every 90 days):")
    for v in allowlisted[:10]:
        adv = (v.get("advisory") or v.get("description") or "")[:100]
        print(f"    ALLOWED: {v.get('package_name', '?')} {vuln_id(v)} ({vuln_severity(v) or 'unknown'}): {adv}")

if hard:
    print()
    print(f"  Hard findings ({len(hard)} — at/above threshold={threshold}):")
    for v in hard[:10]:
        adv = (v.get("advisory") or v.get("description") or "")[:120]
        print(f"    HARD: {v.get('package_name', '?')} {vuln_id(v)} ({vuln_severity(v)}): {adv}")
    sys.exit(1)

sys.exit(0)
PYEOF

RC=$?
if [ "$RC" != 0 ]; then
  echo "x security-scan FAILED (RC=$RC) — see findings above."
  echo "  Add CVE/vulnerability IDs to $ALLOWLIST with rationale + review_date to allowlist."
  exit 1
fi
echo "+ security-scan passed at threshold=$THRESHOLD"
