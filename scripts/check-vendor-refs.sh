#!/usr/bin/env bash
# scripts/check-vendor-refs.sh — CI hard gate for vendor-neutral language.
#
# The Archon durable orchestration plan requires that no upstream vendor or
# product references appear in code, docs, UI labels, API names, or generated
# artifacts. Archon's orchestration substrate must stand on its own naming
# (workflow, run, activity, task queue, worker, signal, query, update,
# event history, schedule, etc.) without leaking comparison-tool names into
# the product surface.
#
# This gate scans the production-facing source/doc tree for upstream vendor
# and product names (case-insensitive) and fails when any unallowed match is
# found. Legitimate references (comparison ADRs, vendor-neutrality rationale
# docs, etc.) belong in `.github/vendor-ref-allowlist.txt` with a comment
# justifying each entry.
#
# Usage:
#   bash scripts/check-vendor-refs.sh
#
# Allowlist format (`.github/vendor-ref-allowlist.txt`):
#   # comment line
#   path:line:term       — allow this exact occurrence
#   path                 — allow all matches in this file (use sparingly)
#
# Exit codes:
#   0 — no unallowed vendor references
#   1 — one or more unallowed references found (printed as
#       `VENDOR-REF: <file>:<line>: <matched-text>`)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd -P)"
cd "$REPO_ROOT"

ALLOWLIST_FILE=".github/vendor-ref-allowlist.txt"

# Vendor terms — case-insensitive. We deliberately use word boundaries via
# grep -E so `temporal_id` (vendor-neutral adjective in DLP/timer context)
# does not false-positive when lowercase, while `Temporal` capitalized in
# prose still matches via the case-insensitive flag below. Anchoring all the
# multi-word terms with `\b` keeps `argonaut` from matching `argo`.
VENDOR_PATTERN='\b(Temporal|temporalio|Cadence|Airflow|Prefect|Dagster|Argo[-_ ]Workflows|Argo|n8n|Zapier|Workato|Tray\.io)\b'

# Scan scopes — only directories/files we ship as product surface.
SCAN_PATHS=(
  "backend/app"
  "frontend/src"
  "docs"
  "README.md"
  "CLAUDE.md"
)

# Add any markdown files at the repo root (e.g. CONTRIBUTING.md).
while IFS= read -r -d '' f; do
  SCAN_PATHS+=("$f")
done < <(find . -maxdepth 1 -type f -name '*.md' -not -name 'README.md' -not -name 'CLAUDE.md' -print0)

# Exclusions — the directories grep should not descend into. We use
# --exclude-dir for path-based pruning and --exclude for filename pruning.
# These cover generated/vendored content that we cannot edit.
EXCLUDE_DIRS=(
  "node_modules"
  "__pycache__"
  ".git"
  "dist"
  "build"
  "frontend/dist"
  "_archive"
  ".pytest_cache"
  ".ruff_cache"
)
EXCLUDE_FILES=(
  "*.lock"
  "*.pyc"
  "package-lock.json"
)

# Build the grep argument list once.
GREP_ARGS=()
for d in "${EXCLUDE_DIRS[@]}"; do
  GREP_ARGS+=("--exclude-dir=$d")
done
for f in "${EXCLUDE_FILES[@]}"; do
  GREP_ARGS+=("--exclude=$f")
done

# Collect raw hits across every scan path. Some paths may not exist on a
# fresh checkout (e.g. CLAUDE.md) — skip them silently.
RAW_HITS=$(mktemp)
trap 'rm -f "$RAW_HITS"' EXIT

for target in "${SCAN_PATHS[@]}"; do
  if [ ! -e "$target" ]; then
    continue
  fi
  # -R recursive, -I ignore binary, -n line numbers, -E extended regex,
  # -i case-insensitive, -H always print filename.
  grep -RInEHi "${GREP_ARGS[@]}" "$VENDOR_PATTERN" "$target" >> "$RAW_HITS" 2>/dev/null || true
done

# Apply allowlist. Each non-comment, non-blank entry is either:
#   - `path:line:term`  exact suppression of one hit (whole-line match keyed
#     by file:line; the `term` field is informational)
#   - `path`            blanket suppression of every hit in that file
#
# The allowlist file is required (we ship a header comment); missing file is
# a hard error so an operator notices.
if [ ! -f "$ALLOWLIST_FILE" ]; then
  echo "ERROR: allowlist file not found: $ALLOWLIST_FILE" >&2
  echo "  Create it from the template comment header before running this gate." >&2
  exit 2
fi

ALLOWED_LINES=$(mktemp)
ALLOWED_FILES=$(mktemp)
trap 'rm -f "$RAW_HITS" "$ALLOWED_LINES" "$ALLOWED_FILES"' EXIT

# Parse allowlist: comment lines (#) and blank lines are skipped. An entry
# with two colons is `path:line:term` (exact). An entry with no colon is a
# blanket file allowance. An entry with one colon (`path:line`) is also
# treated as an exact-line allowance for forgiving authoring.
while IFS= read -r entry || [ -n "$entry" ]; do
  # Strip leading/trailing whitespace.
  entry="${entry#"${entry%%[![:space:]]*}"}"
  entry="${entry%"${entry##*[![:space:]]}"}"
  case "$entry" in
    ''|'#'*)
      continue
      ;;
    *:*:*)
      # path:line:term — record `path:line` as allowed.
      printf '%s\n' "${entry%:*}" >> "$ALLOWED_LINES"
      ;;
    *:*)
      # path:line  — record verbatim.
      printf '%s\n' "$entry" >> "$ALLOWED_LINES"
      ;;
    *)
      # bare path — blanket allowance.
      printf '%s\n' "$entry" >> "$ALLOWED_FILES"
      ;;
  esac
done < "$ALLOWLIST_FILE"

# Filter raw hits against the allowlist.
UNALLOWED=$(mktemp)
trap 'rm -f "$RAW_HITS" "$ALLOWED_LINES" "$ALLOWED_FILES" "$UNALLOWED"' EXIT

while IFS= read -r hit; do
  # `hit` is `<path>:<line>:<text>` from grep.
  path_part="${hit%%:*}"
  rest="${hit#*:}"
  line_part="${rest%%:*}"

  # Normalize path: strip leading `./` so allowlist keys can be written
  # without the prefix regardless of how `find`/`grep` emitted the hit.
  norm_path="${path_part#./}"
  key="$norm_path:$line_part"

  # Blanket-file allowance? Compare against both the raw and normalized form.
  if grep -Fxq "$path_part" "$ALLOWED_FILES" 2>/dev/null; then
    continue
  fi
  if grep -Fxq "$norm_path" "$ALLOWED_FILES" 2>/dev/null; then
    continue
  fi
  # Exact path:line allowance? Same — try both forms.
  if grep -Fxq "$key" "$ALLOWED_LINES" 2>/dev/null; then
    continue
  fi
  if grep -Fxq "$path_part:$line_part" "$ALLOWED_LINES" 2>/dev/null; then
    continue
  fi
  printf '%s\n' "$hit" >> "$UNALLOWED"
done < "$RAW_HITS"

if [ ! -s "$UNALLOWED" ]; then
  echo "OK: no unallowed vendor references"
  exit 0
fi

echo "FAIL: unallowed vendor references detected"
echo ""
while IFS= read -r line; do
  echo "VENDOR-REF: $line"
done < "$UNALLOWED"
echo ""
echo "Remediation: rewrite the reference using vendor-neutral language"
echo "(workflow, run, activity, task queue, worker, signal, query, update, schedule)."
echo "If the reference is legitimate (e.g. a comparison ADR), add it to:"
echo "  $ALLOWLIST_FILE"
echo "with a comment explaining why."
exit 1
