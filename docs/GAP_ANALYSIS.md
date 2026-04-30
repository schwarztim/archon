# Archon — Gap Analysis

**Status:** Pre-1.0. Residual ledger maintained against the Phase A–H verification gates.
**Last updated:** 2026-04-29
**Authority:** [`PHASE_0_3_EXECUTION_REPORT.md`](../PHASE_0_3_EXECUTION_REPORT.md), [`RE_EVALUATION_CYCLE_REPORT.md`](../RE_EVALUATION_CYCLE_REPORT.md), [`docs/feature-matrix.yaml`](feature-matrix.yaml).

> The previous version of this document was a competitive-parity analysis ("20 strategic improvements to match commercial platforms") most of which were aspirational. This rewrite is the residual implementation ledger — what's still missing relative to the seven-phase plan, ranked by priority and dependency.

## 1. Priority ranking

| Priority | Definition |
|:---:|---|
| **P0** | Blocks shipping a 1.0. Failure to close means production is unsafe or core invariants leak. |
| **P1** | Required for full enterprise mode. Failure means a documented degraded mode the operator must accept. |
| **P2** | Quality-of-life / completeness. Improves operator UX or feature surface. |
| **P3** | Optional / community / future. |

## 2. P0 — Production safety gaps

| ID | Gap | Impact | Effort | Dependencies | Owner |
|:--:|---|---|:---:|---|:---:|
| **G01** | Cost gate fails open (3 paths in `costGateNode`: no threshold, no tenant context, query exception). Enterprise mode must fail closed on each. | Quota / budget enforcement bypassed; cost runaway possible. | M | — | Phase I-1 |
| **G02** | Postgres RLS not enforced. Tenant filtering is application-layer only (`middleware/tenant.py`); a query that bypasses the middleware (raw SQL, ORM session without filter) leaks. | Multi-tenant isolation has a structural gap. | M | Postgres test infra | Phase I-1 |
| **G03** | `routes/router.py` does not yet filter visual rules by `tenant_id`. The migration adding the column landed; the route handler change did not. | Visual routing rules leak across tenants. | S | — | Phase I-1 |
| **G04** | `VisualRule.tenant_id` is `nullable=True`. Should be backfilled and promoted to `NOT NULL`. | Same isolation gap as G03; data quality. | S | G03 | Phase I-1 |
| **G05** | Real LLM smoke test absent. All execution tests run with `LLM_STUB_MODE=true`; no CI job exercises a real provider. | A regression in `litellm` integration would not be caught until production. | S | `OPENAI_API_KEY`-gated CI secret | Phase I-2 |

## 3. P1 — Enterprise governance gaps

| ID | Gap | Impact | Effort | Dependencies | Owner |
|:--:|---|---|:---:|---|:---:|
| **G06** | OPA policy engine integration. Currently only RBAC roles + ABAC in code; no externalised policy authoring. | Enterprises that require policy-as-code cannot author rules outside Archon. | L | OPA bundle distribution | Phase I-3 |
| **G07** | SCIM 2.0 user / group provisioning. Routes exist but provisioning end-to-end is incomplete. | Cannot fully integrate with enterprise IdPs (Okta, Azure AD) for user lifecycle. | M | — | Phase I-3 |
| **G08** | Audit hash chain verify endpoint covers `workflow_run_events`; the separate `audit_logs` table verify endpoint is partial. | Tampering on the audit table is not detected by the same depth as run events. | M | — | Phase I-3 |
| **G09** | 12 stub-blocked node executors. They are honestly blocked in production by `_stub_block.py`, but operators want them implemented: `loopNode`, `humanInputNode`, `mcpToolNode`, `toolNode`, `databaseQueryNode`, `functionCallNode`, `embeddingNode`, `vectorSearchNode`, `documentLoaderNode`, `visionNode`, `structuredOutputNode`, `streamOutputNode`. | Visual builder cannot draw RAG, tool-using agents, or structured-output workflows. | XL | varies per node | Phase I-2 |

## 4. P2 — Completeness & quality

| ID | Gap | Impact | Effort | Dependencies | Owner |
|:--:|---|---|:---:|---|:---:|
| **G10** | Frontend bundle is 1.6 MB monolithic. No code-splitting or lazy loading. | Slow first paint; bandwidth waste. | M | — | Phase I-4 |
| **G11** | `dispatch_run` vs `Execution`/`WorkflowRun` legacy shim. `execution_service.run_execution` is a delegating compatibility shim under the `ARCHON_ENABLE_LEGACY_EXECUTION` flag. | Code duplication; two shapes returned by `/api/v1/executions`. | M | All callers migrated to ADR-006 projection | Phase I-1 |
| **G12** | v1/v2 service duplicates (`router.py` vs `router_service.py`, plus 5 others). | Code rot; unclear which version is canonical. | M | ~20 cross-references | Phase I-4 |
| **G13** | Pyright path-resolution noise (`app.services.node_executors` LSP errors). Cosmetic. | Editor experience. Runtime fine. | S | — | Phase I-4 |
| **G14** | `tenant_id` index path in `TenantFilter` silently skips when applied to models without the column. | Queries on those models leak across tenants if the developer forgets a filter. | S | Per-model audit | Phase I-1 |
| **G15** | Connector framework: only 5 reference connectors. Operators commonly request: SharePoint, Snowflake, GitHub, Salesforce, ServiceNow, Confluence. | Catalog perceived as thin. | XL | varies per connector | Phase I-5 |
| **G16** | Frontend approval UX shows pending approvals and grant/deny but lacks: bulk-approve, decision audit trail surfaced inline, approval delegation. | Approver experience for high-volume tenants is rough. | M | — | Phase I-4 |
| **G17** | Mobile builder / router / DLP screens are 3-screen stubs. | Mobile is not a product. | XL | — | Out of scope for 1.0 |

## 5. P3 — Optional / future

| ID | Gap | Impact | Effort | Owner |
|:--:|---|---|:---:|:---:|
| **G18** | Multi-cloud Terraform parity. AWS module is full; Azure and GCP modules are scaffolds. | Operators on Azure / GCP must hand-roll. | XL | Phase I-6 |
| **G19** | ArgoCD application sync. Helm release works manually; CD is straight `helm upgrade`. | No GitOps round-trip for the platform itself. | M | Phase I-6 |
| **G20** | Federated agent mesh, edge runtime with sync, marketplace. | Aspirational; no production demand from current operators. | XL+ | Out of scope for 1.0 |
| **G21** | Helm umbrella `archon-platform` HPA / PDB templates. `values.yaml` declares enabled; templates need finishing. | Auto-scaling not declarative-only. | S | Phase I-6 |
| **G22** | OpenTelemetry distributed tracing per step. Metrics + logs are wired; traces are next. | Cross-step latency attribution is harder than it should be. | M | Phase I-3 |

## 6. Dependency graph

```
G01 (cost-gate fail-closed)        ── independent
G02 (Postgres RLS) ──┬─→ G03 (router filter)
                     └─→ G04 (NOT NULL promotion)
G05 (real LLM smoke test)           ── independent
G06 (OPA)            ── independent
G07 (SCIM)           ── independent
G08 (audit verify)   ── builds on G02 (RLS strengthens auditability)
G09 (12 stub nodes)  ── parallelisable; each independent
G10 (code-splitting) ── independent
G11 (legacy shim)    ── after all callers migrated
G12 (v1/v2 dedup)    ── after G11
G13 (pyright)        ── independent
G14 (tenant filter)  ── G02 first
G15 (connectors)     ── parallelisable
G16 (approval UX)    ── independent
G18 (multi-cloud)    ── independent
G19 (ArgoCD)         ── after G21
G21 (HPA / PDB)      ── independent
G22 (OTel traces)    ── independent
```

## 7. Estimate of remaining work

Rough sizing (not commitments). XS=hours, S=1 day, M=2-5 days, L=1-2 weeks, XL=>2 weeks.

| Priority bucket | Sum |
|---|---|
| P0 (G01–G05) | 1 × M, 1 × M, 2 × S, 1 × S → ~2-3 weeks single-engineer |
| P1 (G06–G09) | 1 × L, 1 × M, 1 × M, 1 × XL (12 nodes) → ~6-8 weeks single-engineer |
| P2 (G10–G16) | mixed → ~4-6 weeks single-engineer |
| P3 (G18–G22) | mostly XL → indefinite |

## 8. What is NOT a gap

The following items appear in older docs but are explicit non-goals for 1.0:

| Item | Decision rationale |
|------|-------------------|
| 50+ connectors | Five reference connectors are sufficient. The pre-1.0 priority is making the kernel honest, not catalog growth. |
| 200+ node types | The 28 registered are sufficient; 12 are honestly blocked, 14 are beta with documented gaps. The priority is implementing the 12 stubs (G09), not adding more. |
| Full RAG pipeline | The previous "RAG engine" was zero-vector embed + first-N retrieval. It has been removed. Real RAG depends on G09 (`embeddingNode`, `vectorSearchNode`, `documentLoaderNode`). |
| New frameworks (`.sdd`, `.claude-flow`, `.swarm`) | Tried in prior cycles; Claude Flow V3 ran zero tasks. The decision is: ship code, not frameworks. |
| Mobile app | 3-screen stub. Not in scope for 1.0; deferred indefinitely. |

## 9. How to close a gap

1. Pick a row from the table above.
2. Reference the gap ID (`G01`...) in the plan and PR.
3. Write a plan that satisfies the [Phase I plan template](../docs/CONTRIBUTING.md#definition-of-done).
4. Land tests that fail without the change and pass with it.
5. Update [`docs/feature-matrix.yaml`](feature-matrix.yaml) to flip the affected entries from `beta` / `stub` to `production`.
6. Run `make verify` — the contract gate enforces the matrix.
7. Strike the gap from this document in the same PR.

## 10. Cross-references

- [`ROADMAP.md`](../ROADMAP.md) — phase ledger; Phase I owns most P0/P1.
- [`docs/feature-matrix.yaml`](feature-matrix.yaml) — canonical inventory.
- [`docs/FEATURE_MAPPING.md`](FEATURE_MAPPING.md) — feature → code → tests.
- [`docs/ARCHITECTURE.md`](ARCHITECTURE.md) — bounded contexts.
- [`docs/PRODUCTION_CONFIG.md`](PRODUCTION_CONFIG.md) — env-var + startup-gate map.
- [`docs/CONTRIBUTING.md`](CONTRIBUTING.md) — definition of done.
