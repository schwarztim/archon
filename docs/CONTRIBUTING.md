# Contributing to Archon

**Status:** Pre-1.0. Contributions land via PR with passing verification gates.

> Archon is built agentically (a coordinated swarm of AI agents writes most code) but the engineering discipline is the same as any production project: every change has tests, every claim is evidence-backed, every commit is reviewable.

## 1. Branch strategy

| Branch | Purpose |
|--------|---------|
| `main` | The integration branch. CI runs `verify-unit`, `verify-integration`, `verify-frontend`, `verify-contracts`, `verify-slice`, `feature-matrix-validate`, plus lint and security-scan. PRs cannot merge with red gates. |
| `feature/<gap-id>-<slug>` | Single-PR feature branch. Reference the gap ID from [`docs/GAP_ANALYSIS.md`](GAP_ANALYSIS.md) in the branch name (e.g., `feature/G01-cost-gate-fail-closed`). |
| `fix/<short-description>` | Bug fixes that don't map to a gap. |
| `docs/<short-description>` | Doc-only changes. |

No long-lived branches. No `develop`. Rebase on `main` before PR; squash on merge.

## 2. PR template requirements

Every PR description must include:

```markdown
## What

(one sentence summarizing what the PR does)

## Why

(reference: gap ID from GAP_ANALYSIS.md, ADR section, or operator request)

## Acceptance commands

```bash
make verify           # MUST pass
make test-slice       # MUST pass for any execution-path change
LLM_STUB_MODE=true PYTHONPATH=backend python3 -m pytest backend/tests/test_<area>.py -v
# any other commands needed to demonstrate the change works
```

## Evidence

- [ ] Tests added / extended (count and file paths):
- [ ] Feature matrix updated (`docs/feature-matrix.yaml` entries flipped):
- [ ] Docs updated (which files):
- [ ] ADR added / updated (if applicable):
- [ ] Migration added (if schema change):

## Risk

(blast radius — what other behavior could break? what's the rollback story?)
```

A PR without an "Acceptance commands" block that the reviewer can paste and run will be sent back.

## 3. Definition of done

A change is **done** when **all** of the following hold:

| # | Criterion | Verifier |
|:-:|---|---|
| 1 | `make verify` exits 0 locally and in CI. | CI |
| 2 | New behavior has tests that fail without the change and pass with it. | Reviewer reads diff |
| 3 | If schema changed, an Alembic migration applies cleanly on SQLite (test) and Postgres (real DB). | `make migrate-up` + `make migrate-down` round-trip |
| 4 | If a node executor was added or status flipped, [`docs/feature-matrix.yaml`](feature-matrix.yaml) is updated and `python3 scripts/check-feature-matrix.py` exits 0. | `verify-contracts` |
| 5 | If a metric was added, [`docs/metrics-catalog.md`](metrics-catalog.md) is updated and `scripts/check-grafana-metric-parity.py` exits 0. | `verify-contracts` |
| 6 | If a frontend / backend type changed, `scripts/check-frontend-backend-parity.py` exits 0. | `verify-contracts` |
| 7 | Documentation referenced by the change (README, ARCHITECTURE, PRODUCTION_CONFIG, STATE_MACHINE, FEATURE_MAPPING, GAP_ANALYSIS, ADRs) is updated **in the same PR**. | Reviewer |
| 8 | If a status was changed in `feature-matrix.yaml` from `stub`/`beta` to `production`, the corresponding [`docs/GAP_ANALYSIS.md`](GAP_ANALYSIS.md) row is closed in the same PR. | Reviewer |
| 9 | No prior tests broken outside the PR's scope. | CI |
| 10 | No new runtime warnings introduced. | CI lint + reviewer |

A PR that says "production ready" without satisfying #1–#10 is rejected. The phrase appears in zero current documents and zero current PRs by deliberate policy.

## 4. Test discipline

### 4.1 Always run

```bash
make verify-fast    # unit + frontend; quick local iteration
```

### 4.2 Before pushing

```bash
make verify         # full 5-gate pipeline
```

### 4.3 If you touched the execution path

```bash
make slice-up       # bring up postgres + redis
make test-slice     # vertical-slice REST canary
make slice-down     # tear down
```

### 4.4 Test layout

| Layer | Location | Naming | What goes here |
|-------|----------|--------|----------------|
| Unit | `backend/tests/test_<area>.py` | `test_<behavior>` | Pure logic, mocked dependencies. |
| Node executor | `backend/tests/test_node_executors/test_<node>.py` | `test_<scenario>` | One file per executor type. |
| Integration | `tests/integration/test_<area>.py` | `test_<workflow>` | Live Postgres + Redis. |
| Vertical slice | `tests/integration/test_vertical_slice.py` | `test_<scenario>` | The REST heartbeat. Keep this small. |
| Frontend | `frontend/src/tests/<Component>.test.tsx` | `<behavior>` | Vitest + Testing Library. |
| Load | `backend/tests/test_load/test_<profile>.py` | `test_<profile>` | Run via `make load`. |
| Chaos | `backend/tests/test_chaos/` | `test_<scenario>` | Run via `make chaos`. |

### 4.5 Stub mode

`LLM_STUB_MODE=true` is **default for tests**. It produces deterministic 30-token responses without API keys. Tests that require a real provider must:

1. Set `LLM_STUB_MODE=false` explicitly.
2. Be marked with `@pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="...")`.
3. Live in `backend/tests/test_real_llm/` (CI runs this only when the secret is present).

## 5. Commit message format

```
<type>(<scope>): <subject>

<body — explain WHY, not what; the diff shows what>

<footer — references>
```

| Type | Use |
|------|-----|
| `feat` | New behavior. |
| `fix` | Bug fix. |
| `docs` | Documentation only. |
| `refactor` | Code change that neither adds behavior nor fixes a bug. |
| `test` | Test-only changes. |
| `chore` | Dependency bumps, infra. |
| `perf` | Performance change with measured before/after. |

Examples:

```
feat(dispatcher): emit step.retry event on retriable failure

Closes G05 partially — the retry event was being recorded internally
but not emitted to the run event log, so frontend replay missed it.

Refs: docs/STATE_MACHINE.md §6
```

```
fix(cost-gate): fail closed when tenant context missing

In enterprise mode the cost gate now returns step.failed instead of
silently passing. Three fail-open paths identified in GAP_ANALYSIS G01:
no threshold, no tenant context, query exception.

Closes: G01
```

The first line is ≤ 72 chars. No emoji. No "Co-authored-by" trailers (per project policy).

## 6. ADR ownership

Architectural decisions live in [`docs/adr/orchestration/`](adr/orchestration/) (run-substrate ADRs 001–007) and [`docs/adr/`](adr/) (cross-cutting ADRs).

Add a new ADR when:

- The decision changes a public schema (DB column, API contract, event type).
- The decision is non-obvious and a future reader would re-derive it incorrectly.
- The decision was contested and the resolution should be durable.

Don't add an ADR for:

- Refactoring of internal modules.
- Bug fixes.
- Tests.

Format: `ADR-NNN-kebab-case-title.md`. Status flow: `PROPOSED` → `ACCEPTED` → (optional) `SUPERSEDED BY <ADR>`. Once `ACCEPTED` an ADR is immutable except for the status header.

## 7. Reviewer responsibilities

The reviewer:

1. Runs the PR's "Acceptance commands" block locally (or in a clean container) before approving.
2. Reads every file in the diff.
3. Verifies the Definition of Done table is satisfied.
4. Rejects PRs whose claims (commit message, PR description) don't match the diff.
5. Does not approve "PRODUCTION READY" rhetoric. Approves passing tests + closed gaps.

A reviewer who waves through a PR without running the acceptance commands violates the project's evidence discipline.

## 8. Reporting issues

- Bug reports: include reproduction steps, environment (`docker compose ps` output, `ARCHON_ENV`), expected vs actual.
- Feature requests: link to the gap ID in [`docs/GAP_ANALYSIS.md`](GAP_ANALYSIS.md) if one exists, or propose a new gap.
- Security: there is no `SECURITY.md` in the repo today; report security issues by emailing the maintainers privately. (A formal `SECURITY.md` is a P3 item — see [`docs/GAP_ANALYSIS.md`](GAP_ANALYSIS.md).)

## 9. Code style

| Language | Style |
|----------|-------|
| Python | PEP 8, type hints required on all function signatures, formatted with `ruff format`. Linted with `ruff check`. |
| TypeScript | Strict mode, ESLint + Prettier, no `any`. |

`make lint` runs ruff. `make typecheck` runs pyright (if installed). The frontend equivalent runs as part of `verify-frontend`.

## 10. License

Apache 2.0. By contributing, you agree your contributions are licensed under the same terms. See [`LICENSE`](../LICENSE).

## 11. Cross-references

- [`README.md`](../README.md) — surface description and quickstart.
- [`docs/ARCHITECTURE.md`](ARCHITECTURE.md) — bounded contexts.
- [`docs/STATE_MACHINE.md`](STATE_MACHINE.md) — `WorkflowRun` lifecycle.
- [`docs/PRODUCTION_CONFIG.md`](PRODUCTION_CONFIG.md) — env vars.
- [`docs/DEPLOYMENT_GUIDE.md`](DEPLOYMENT_GUIDE.md) — deploy.
- [`docs/FEATURE_MAPPING.md`](FEATURE_MAPPING.md) — feature → code → tests.
- [`docs/GAP_ANALYSIS.md`](GAP_ANALYSIS.md) — residual ledger.
- [`docs/adr/orchestration/`](adr/orchestration/) — binding ADRs.
