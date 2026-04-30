# Archived Documentation (Historical)

The files in this directory are agent-generated self-reports and outdated work-in-progress documents from prior implementation cycles. They are retained for git history continuity. **Do not treat them as authoritative.**

For current project state, read in this order:

1. [`/README.md`](../../README.md) — surface description.
2. [`/ROADMAP.md`](../../ROADMAP.md) — phase ledger A–I with verifier sign-off.
3. [`/PHASE_0_3_EXECUTION_REPORT.md`](../../PHASE_0_3_EXECUTION_REPORT.md) — most recent closing report (kernel + node honesty cycle).
4. [`/RE_EVALUATION_CYCLE_REPORT.md`](../../RE_EVALUATION_CYCLE_REPORT.md) — prior closing report (re-evaluation cycle).
5. [`/RE_EVALUATION_REPORT.md`](../../RE_EVALUATION_REPORT.md) — ground-truth audit that triggered the rebuild.
6. [`/docs/ARCHITECTURE.md`](../ARCHITECTURE.md), [`/docs/STATE_MACHINE.md`](../STATE_MACHINE.md), [`/docs/PRODUCTION_CONFIG.md`](../PRODUCTION_CONFIG.md), [`/docs/FEATURE_MAPPING.md`](../FEATURE_MAPPING.md), [`/docs/GAP_ANALYSIS.md`](../GAP_ANALYSIS.md), [`/docs/DEPLOYMENT_GUIDE.md`](../DEPLOYMENT_GUIDE.md), [`/docs/CONTRIBUTING.md`](../CONTRIBUTING.md).

## Archived overclaim documents (Feb 2026)

These claimed "PRODUCTION READY" status that was demonstrably false at the time of writing — see `/RE_EVALUATION_REPORT.md` (2026-04-28) for ground truth.

| File | Original location | Reason archived |
|---|---|---|
| `COMPLETION_SUMMARY.txt` | repo root | Claims "PRODUCTION READY" — contradicted by ARCHON_OVERHAUL_PROMPT.md |
| `FINAL_REPORT.md` | repo root | Self-approved by "Automated Verification System" — no human review |
| `FIXES_SUMMARY.txt` | repo root | Documents 2 fixes; not a comprehensive state report |
| `CRITICAL_STUBS_FIXED.md` | repo root | "All critical stubs fixed" — 33 stub tests still existed per overhaul prompt |
| `WIZARD_TEMPLATES_EXAMPLES.md` | repo root | Template examples; superseded by frontend wizard implementation |
| `VERIFICATION_CHECKLIST.md` | repo root | All checkboxes blank; no agent ever filled it in |
| `DOCUMENTATION_INDEX.md` | repo root | Index of overclaim docs |
| `FINAL_SUMMARY.md` | docs/ | Workstream completion claims contradicted by same doc's "incomplete" disclosures |
| `HEALTH_REPORT.md` | docs/ | Test results disagree with INTEGRATION_TEST_REPORT |
| `INTEGRATION_TEST_REPORT.md` | docs/ | Different failure counts than HEALTH_REPORT |

## Archived workstream cycle reports (pre-2026-04-29 cycle)

These workstream reports (WS1–WS8) document a prior agent cycle's work. Their findings were partially superseded and partially retained — the durable parts (real services, AWS Terraform, Vault Helm chart) are documented in the current `docs/feature-matrix.yaml` and `docs/ARCHITECTURE.md`. The reports themselves are retained here for trace.

| File | Reason archived |
|---|---|
| `WS1_ROUTE_FIXES_REPORT.md` | Pre-Phase-0 work; superseded by canonical run substrate. |
| `WS2_DB_MIGRATION_REPORT.md` | Pre-Phase-0 migration work; current schema is at migration 0010, post-Phase-0. |
| `WS3_FRONTEND_REPORT.md` | Pre-Phase-3 frontend work; superseded by Phase 3's frontend ↔ backend type parity gate. |
| `WS4_AUTH_SECURITY_REPORT.md` | Pre-Phase-4 auth work; superseded by [`docs/adr/011-auth-flows.md`](../adr/011-auth-flows.md). |
| `WS5_MODEL_ROUTER_REPORT.md` | Pre-Phase-1 routing work; current router_service.py described in `docs/FEATURE_MAPPING.md`. |
| `WS6_GATEWAY_REPORT.md` | Pre-Phase-4 gateway work; security bypass closed in re-evaluation cycle (see `/RE_EVALUATION_CYCLE_REPORT.md`). |
| `WS7_REPORT.md` | Pre-Phase-7 UX work; superseded by Phase 7 builder live stream. |
| `WS8_REPORT.md` | Pre-Phase-8 deploy work; superseded by current `docs/DEPLOYMENT_GUIDE.md`. |
| `WS8_CROSSCUTTING_REPORT.md` | Pre-Phase-8 cross-cutting work; same. |

## Archived stale design / instruction documents

| File | Reason archived |
|---|---|
| `BUILD_CORRECTNESS.md` | "10 build-correctness strategies" mostly subsumed by current verify gates and Phase 0 ADRs. |
| `SELF_VERIFICATION_CHECKLIST.md` | Replaced by [`docs/CONTRIBUTING.md`](../CONTRIBUTING.md) Definition of Done. |
| `DESIGN_DOCUMENT.md` | Pre-Phase-0 blueprint; superseded by current ARCHITECTURE.md + ADRs. |
| `azure_openai_integration.md` | Provider-specific design doc; superseded by `docs/ADR/004-orchestration-engine.md` and the live `router_service.py`. |
| `azure-integration-build.md` | Same; build-time notes for the Azure provider integration. |
| `QUICK_REFERENCE.md` | Provider-specific signature-verification quick reference; superseded by the live versioning service tests. |
