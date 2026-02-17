# Agent-05: Sandbox, Arena Mode & Benchmark Suite (Enterprise)

> **Phase**: 1 | **Dependencies**: Agent-01 (Core Backend) | **Priority**: HIGH
> **The safety net. No agent reaches production without proving itself here. Sandbox isolation, A/B testing, and benchmarking ensure only battle-tested agents get promoted.**

---

## Identity

You are Agent-05: the Sandbox, Arena Mode & Benchmark Master. You build isolated execution environments with Kubernetes namespace isolation, a competitive Arena Mode for A/B testing agent variants, and a comprehensive Benchmark Suite for standardized agent evaluation — all with strict credential isolation, cost guardrails, and full audit trails.

## Mission

Build a production-grade sandbox and testing infrastructure that:
1. Runs every agent in an isolated K8s namespace with network policies, resource quotas, and auto-cleanup after TTL
2. Provisions temporary credentials via dynamic Vault secrets — sandboxes can NEVER access production secrets
3. Provides Arena Mode for running 2+ agent versions side-by-side with statistical significance testing and auto-promotion
4. Ships a Benchmark Suite with pre-built benchmark sets and custom benchmark creation with tenant-scoped leaderboards
5. Enforces per-sandbox cost guardrails with execution abort on budget overrun and cost breakdown per graph node
6. Logs every sandbox execution with full input/output for reproducibility, with exportable results

## Requirements

### Isolated Auth Contexts

**Dynamic Vault Secrets for Sandboxes**
- Each sandbox gets its own temporary credentials provisioned via Vault's dynamic secrets engine:
  ```python
  class SandboxCredentialProvider:
      """Provisions ephemeral, sandbox-scoped credentials."""
      
      async def provision(self, sandbox_id: uuid.UUID, 
                          credential_requirements: list[CredentialRequirement],
                          ttl_seconds: int = 3600) -> SandboxCredentials:
          credentials = {}
          for req in credential_requirements:
              # Generate dynamic credential via Vault
              dynamic_secret = await self.vault_client.generate_dynamic_secret(
                  mount=f"archon/sandbox/{sandbox_id}",
                  role=req.connector_type,
                  ttl=f"{ttl_seconds}s",
                  max_ttl=f"{ttl_seconds * 2}s",
                  # Sandbox credentials have restricted permissions
                  policy=self.sandbox_policy(req)
              )
              credentials[req.connector_type] = SandboxCredential(
                  vault_path=f"archon/sandbox/{sandbox_id}/{req.connector_type}",
                  lease_id=dynamic_secret.lease_id,
                  expires_at=datetime.utcnow() + timedelta(seconds=ttl_seconds),
                  restricted=True  # Read-only where possible
              )
          
          return SandboxCredentials(
              sandbox_id=sandbox_id,
              credentials=credentials,
              expires_at=datetime.utcnow() + timedelta(seconds=ttl_seconds)
          )
      
      async def revoke(self, sandbox_id: uuid.UUID):
          """Revoke all dynamic secrets for a sandbox."""
          await self.vault_client.revoke_prefix(f"archon/sandbox/{sandbox_id}")
  ```
- Production/staging secrets are NEVER accessible from sandbox contexts
- Sandbox API keys: auto-generated with `oai_sandbox_<32-char>` prefix, auto-expire with sandbox TTL
- Credential injection at runtime: secrets injected into sandbox container environment, never persisted in sandbox definition

**Secrets Injection Configuration**
```python
class SandboxSecretsConfig(BaseModel):
    """Defines which Vault paths the sandboxed agent can access."""
    allowed_vault_paths: list[str]             # Vault paths this sandbox can read
    denied_vault_paths: list[str] = []         # Explicit denials (override allows)
    inject_as: Literal["env", "file", "api"] = "env"  # How credentials are injected
    rotation_policy: Literal["none", "on_access", "periodic"] = "none"
    max_secret_ttl_seconds: int = 3600         # Max TTL for any secret in this sandbox
```

### Kubernetes Namespace Isolation

**Ephemeral K8s Namespace per Sandbox**
```python
class SandboxNamespace(BaseModel):
    """Kubernetes namespace configuration for an isolated sandbox."""
    namespace: str                             # "sandbox-{sandbox_id[:8]}"
    sandbox_id: uuid.UUID
    tenant_id: uuid.UUID
    
    # Resource quotas
    cpu_limit: str = "2"                       # CPU cores
    memory_limit: str = "4Gi"                  # Memory
    ephemeral_storage_limit: str = "10Gi"      # Disk
    max_pods: int = 5                          # Max concurrent pods
    
    # Network policies
    egress_allowlist: list[str] = []           # Allowed external endpoints (CIDRs or FQDNs)
    ingress_enabled: bool = False              # No inbound traffic by default
    dns_policy: Literal["default", "none"] = "default"
    
    # Lifecycle
    ttl_seconds: int = 3600                    # Auto-cleanup after TTL
    created_at: datetime
    expires_at: datetime
    cleanup_status: Literal["active", "cleaning", "cleaned"] = "active"
```

- Network policies:
  ```yaml
  # infra/k8s/sandbox/network-policy.yaml
  apiVersion: networking.k8s.io/v1
  kind: NetworkPolicy
  metadata:
    name: sandbox-isolation
    namespace: "{{ namespace }}"
  spec:
    podSelector: {}
    policyTypes:
      - Ingress
      - Egress
    ingress: []  # No inbound traffic
    egress:
      - to:
          - namespaceSelector:
              matchLabels:
                kubernetes.io/metadata.name: kube-system
        ports:
          - protocol: UDP
            port: 53  # DNS only
      - to: {{ egress_rules }}  # Whitelisted API endpoints only
  ```
- Resource quotas:
  ```yaml
  # infra/k8s/sandbox/resource-quota.yaml
  apiVersion: v1
  kind: ResourceQuota
  metadata:
    name: sandbox-quota
    namespace: "{{ namespace }}"
  spec:
    hard:
      requests.cpu: "{{ cpu_limit }}"
      requests.memory: "{{ memory_limit }}"
      limits.cpu: "{{ cpu_limit }}"
      limits.memory: "{{ memory_limit }}"
      requests.ephemeral-storage: "{{ ephemeral_storage_limit }}"
      pods: "{{ max_pods }}"
  ```
- Auto-cleanup:
  ```python
  class SandboxCleanupService:
      """Cleans up expired sandbox namespaces and all associated resources."""
      
      async def cleanup_expired(self):
          """Runs on a 60-second interval via APScheduler."""
          expired = await self.repo.get_expired_sandboxes()
          for sandbox in expired:
              await self.cleanup(sandbox)
      
      async def cleanup(self, sandbox: Sandbox):
          # 1. Revoke all dynamic Vault secrets
          await self.credential_provider.revoke(sandbox.id)
          
          # 2. Archive execution logs to S3/MinIO
          await self.archive_logs(sandbox)
          
          # 3. Delete K8s namespace (cascades to all pods, services, etc.)
          await self.k8s_client.delete_namespace(sandbox.namespace)
          
          # 4. Update sandbox status
          sandbox.cleanup_status = "cleaned"
          sandbox.cleaned_at = datetime.utcnow()
          await self.repo.update(sandbox)
  ```

### Core Data Models

**Sandbox Model**
```python
class Sandbox(SQLModel, table=True):
    """An isolated execution environment for testing agents."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(max_length=255)
    description: str | None
    
    # Agent reference
    agent_id: uuid.UUID = Field(foreign_key="agents.id")
    agent_version_id: uuid.UUID | None = Field(foreign_key="agent_versions.id")
    
    # Auth context
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    workspace_id: uuid.UUID = Field(foreign_key="workspaces.id")
    created_by: uuid.UUID = Field(foreign_key="users.id")
    
    # Isolation configuration
    namespace: str | None                      # K8s namespace name
    secrets_config: SandboxSecretsConfig
    resource_config: SandboxResourceConfig
    network_config: SandboxNetworkConfig
    
    # Cost guardrails
    budget_limit_usd: float = 1.0              # Max spend for this sandbox
    budget_spent_usd: float = 0.0
    budget_alert_threshold: float = 0.8        # Alert at 80% of budget
    
    # Lifecycle
    status: Literal["provisioning", "ready", "running", "paused", 
                     "completed", "failed", "expired", "cleaned"] = "provisioning"
    ttl_seconds: int = 3600
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: datetime | None
    expires_at: datetime | None
    cleaned_at: datetime | None
    
    # Execution tracking
    execution_count: int = 0
    last_execution_id: uuid.UUID | None
    
    # Tags for organization
    tags: list[str] = Field(default_factory=list)

class SandboxExecution(SQLModel, table=True):
    """A single execution run within a sandbox — fully logged for reproducibility."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    sandbox_id: uuid.UUID = Field(foreign_key="sandboxes.id")
    
    # Input/Output (full capture for reproducibility)
    inputs: dict                               # Exact inputs provided
    outputs: dict | None                       # Full output captured
    error: dict | None                         # Error details if failed
    
    # Execution metrics
    status: Literal["queued", "running", "completed", "failed", 
                     "cancelled", "timed_out", "budget_exceeded"] = "queued"
    started_at: datetime | None
    completed_at: datetime | None
    duration_ms: int | None
    
    # Cost tracking (per-node breakdown)
    total_cost_usd: float = 0.0
    cost_breakdown: dict = Field(default_factory=dict)  # {node_id: cost}
    total_tokens: int = 0
    token_breakdown: dict = Field(default_factory=dict)  # {node_id: {input: n, output: n}}
    models_used: list[str] = Field(default_factory=list)
    
    # Quality metrics
    quality_score: float | None                # LLM-as-judge score (0.0-1.0)
    quality_reasoning: str | None              # Judge's reasoning
    
    # Trace
    trace_id: str | None                       # OpenTelemetry trace ID
    node_execution_log: list[dict] = Field(default_factory=list)  # Per-node timing & status
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

### Arena Mode (A/B Testing)

**Arena Configuration**
```python
class Arena(SQLModel, table=True):
    """An A/B testing arena for comparing agent variants."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str
    description: str | None
    
    # Variants
    variants: list[ArenaVariant]               # 2+ agent variants to compare
    
    # Test configuration
    test_inputs: list[dict]                    # Input set to run against all variants
    test_count: int                            # Number of test runs per variant
    parallel: bool = True                      # Run variants in parallel
    
    # Evaluation criteria
    evaluation_method: Literal["llm_judge", "human_judge", "metric_based", "hybrid"] = "llm_judge"
    judge_model: str = "gpt-4o"               # LLM-as-judge model
    judge_prompt: str | None                   # Custom judge prompt
    evaluation_criteria: list[EvaluationCriterion]
    
    # Statistical configuration
    significance_level: float = 0.05           # p-value threshold (default: 95% confidence)
    minimum_sample_size: int = 30              # Minimum runs before declaring winner
    
    # Auto-promotion
    auto_promote: bool = False                 # Auto-promote winner to next environment
    promotion_target: Literal["staging", "production"] = "staging"
    promotion_requires_approval: bool = True
    
    # Auth context
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    workspace_id: uuid.UUID = Field(foreign_key="workspaces.id")
    created_by: uuid.UUID = Field(foreign_key="users.id")
    
    # Status
    status: Literal["configuring", "running", "completed", "cancelled"] = "configuring"
    winner_variant_id: uuid.UUID | None
    winner_confidence: float | None
    
    # Budget
    budget_limit_usd: float = 10.0
    budget_spent_usd: float = 0.0
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None

class ArenaVariant(SQLModel, table=True):
    """A single variant (agent version) in an arena competition."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    arena_id: uuid.UUID = Field(foreign_key="arenas.id")
    name: str                                  # "Variant A", "v2.1", etc.
    agent_id: uuid.UUID = Field(foreign_key="agents.id")
    agent_version_id: uuid.UUID = Field(foreign_key="agent_versions.id")
    
    # Aggregated results
    total_runs: int = 0
    successful_runs: int = 0
    avg_latency_ms: float | None
    avg_cost_usd: float | None
    avg_quality_score: float | None
    avg_accuracy: float | None
    total_tokens: int = 0
    user_preference_count: int = 0             # How many times users preferred this variant
    
    # Statistical results
    p_value: float | None                      # Statistical significance vs other variants
    effect_size: float | None                  # Cohen's d
    confidence_interval: tuple[float, float] | None
    is_winner: bool = False

class EvaluationCriterion(BaseModel):
    """A single evaluation criterion for arena judging."""
    name: str                                  # "accuracy", "helpfulness", "safety"
    description: str
    weight: float = 1.0                        # Weight in composite score
    scoring: Literal["binary", "likert_5", "likert_10", "numeric"] = "likert_5"
    rubric: str | None                         # Detailed rubric for judges
```

**Arena Execution Engine**
```python
class ArenaEngine:
    """Runs arena competitions with statistical rigor."""
    
    async def run_arena(self, arena: Arena) -> ArenaResult:
        results = {v.id: [] for v in arena.variants}
        
        for test_input in arena.test_inputs:
            for _ in range(arena.test_count):
                # Run all variants with identical input
                variant_tasks = [
                    self.run_variant(variant, test_input, arena)
                    for variant in arena.variants
                ]
                
                if arena.parallel:
                    variant_results = await asyncio.gather(*variant_tasks)
                else:
                    variant_results = [await t for t in variant_tasks]
                
                # Evaluate: LLM-as-judge or metric-based
                evaluations = await self.evaluate(
                    variant_results, arena.evaluation_criteria, arena.evaluation_method
                )
                
                for variant, result, evaluation in zip(
                    arena.variants, variant_results, evaluations
                ):
                    results[variant.id].append(ArenaRunResult(
                        variant_id=variant.id,
                        input=test_input,
                        output=result.output,
                        latency_ms=result.duration_ms,
                        cost_usd=result.total_cost_usd,
                        quality_score=evaluation.score,
                        accuracy=evaluation.accuracy,
                        tokens=result.total_tokens
                    ))
        
        # Statistical analysis
        winner = await self.statistical_analysis(results, arena)
        
        # Auto-promote if configured
        if arena.auto_promote and winner and winner.confidence >= (1 - arena.significance_level):
            await self.promote_winner(winner, arena)
        
        return ArenaResult(arena_id=arena.id, winner=winner, results=results)
    
    async def statistical_analysis(self, results: dict, arena: Arena) -> ArenaWinner | None:
        """Run statistical significance tests on arena results."""
        variants = list(results.keys())
        if len(variants) < 2:
            return None
        
        # Pairwise comparisons
        for i, v1 in enumerate(variants):
            for v2 in variants[i+1:]:
                scores_1 = [r.quality_score for r in results[v1]]
                scores_2 = [r.quality_score for r in results[v2]]
                
                # t-test for continuous metrics
                t_stat, p_value = scipy.stats.ttest_ind(scores_1, scores_2)
                
                # Chi-squared for categorical outcomes (pass/fail)
                pass_1 = sum(1 for r in results[v1] if r.quality_score >= 0.7)
                pass_2 = sum(1 for r in results[v2] if r.quality_score >= 0.7)
                chi2, chi_p = scipy.stats.chisquare([pass_1, pass_2])
                
                # Effect size (Cohen's d)
                effect_size = self.cohens_d(scores_1, scores_2)
        
        # Determine winner
        best_variant = max(variants, key=lambda v: np.mean([r.quality_score for r in results[v]]))
        return ArenaWinner(variant_id=best_variant, p_value=p_value, effect_size=effect_size)
```

### Benchmark Suite

**Pre-Built Benchmark Sets**
```python
class BenchmarkSuite(SQLModel, table=True):
    """A collection of benchmark test cases for standardized evaluation."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str
    description: str
    category: Literal["reasoning", "coding", "summarization", "classification",
                       "extraction", "conversation", "tool_use", "custom"]
    
    # Test cases
    test_cases: list[BenchmarkTestCase]
    total_cases: int
    
    # Scoring
    scoring_method: Literal["exact_match", "fuzzy_match", "llm_judge", 
                            "metric_based", "human_eval"] = "llm_judge"
    scoring_config: dict = Field(default_factory=dict)
    
    # Baseline
    baseline_scores: dict = Field(default_factory=dict)  # {model: score} for comparison
    
    # Scoping
    visibility: Literal["platform", "tenant", "workspace"] = "platform"
    tenant_id: uuid.UUID | None
    created_by: uuid.UUID = Field(foreign_key="users.id")
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime | None

class BenchmarkTestCase(BaseModel):
    """A single test case within a benchmark suite."""
    case_id: str
    input: dict                                # Input to the agent
    expected_output: dict | None               # Ground truth (for exact/fuzzy match)
    evaluation_rubric: str | None              # For LLM-as-judge
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    tags: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)

class BenchmarkRun(SQLModel, table=True):
    """A benchmark run — evaluating one agent against one suite."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    suite_id: uuid.UUID = Field(foreign_key="benchmark_suites.id")
    agent_id: uuid.UUID = Field(foreign_key="agents.id")
    agent_version_id: uuid.UUID = Field(foreign_key="agent_versions.id")
    
    # Results
    total_cases: int
    passed_cases: int
    failed_cases: int
    skipped_cases: int = 0
    overall_score: float                       # 0.0-1.0 composite score
    per_case_results: list[dict]               # Detailed per-case results
    
    # Metrics
    avg_latency_ms: float
    total_cost_usd: float
    total_tokens: int
    
    # Comparison
    baseline_delta: float | None               # Score difference vs baseline
    previous_run_delta: float | None           # Score difference vs last run
    
    # Status
    status: Literal["running", "completed", "failed", "cancelled"] = "running"
    
    # Auth
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    run_by: uuid.UUID = Field(foreign_key="users.id")
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None

class BenchmarkLeaderboard(SQLModel, table=True):
    """Per-tenant leaderboard for benchmark results."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    suite_id: uuid.UUID = Field(foreign_key="benchmark_suites.id")
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    
    # Ranked entries
    entries: list[LeaderboardEntry]
    last_updated: datetime
    
class LeaderboardEntry(BaseModel):
    rank: int
    agent_id: uuid.UUID
    agent_name: str
    agent_version: str
    score: float
    latency_ms: float
    cost_usd: float
    run_id: uuid.UUID
    submitted_at: datetime
```

- Built-in benchmark categories:
  - **Reasoning**: logic puzzles, math problems, multi-step reasoning chains
  - **Coding**: code generation, debugging, refactoring, test writing
  - **Summarization**: document summarization, key point extraction, abstractive/extractive
  - **Classification**: sentiment analysis, intent detection, topic classification
  - **Extraction**: entity extraction, relation extraction, structured data parsing
  - **Conversation**: multi-turn dialogue, context retention, persona consistency
  - **Tool Use**: correct tool selection, parameter extraction, multi-tool orchestration
- Custom benchmark creation via API or UI
- Leaderboard per tenant: compare your agents against each other and against baseline

### Cost Guardrails

**Per-Sandbox Budget Enforcement**
```python
class CostGuardrailService:
    """Enforces cost limits at the sandbox and execution level."""
    
    async def check_budget(self, sandbox: Sandbox, estimated_cost: float) -> BudgetCheck:
        remaining = sandbox.budget_limit_usd - sandbox.budget_spent_usd
        
        if remaining <= 0:
            return BudgetCheck(allowed=False, reason="Budget exhausted",
                             remaining=0, estimated_cost=estimated_cost)
        
        if estimated_cost > remaining:
            return BudgetCheck(allowed=False, reason="Estimated cost exceeds remaining budget",
                             remaining=remaining, estimated_cost=estimated_cost)
        
        if sandbox.budget_spent_usd / sandbox.budget_limit_usd >= sandbox.budget_alert_threshold:
            await self.send_budget_alert(sandbox)
        
        return BudgetCheck(allowed=True, remaining=remaining, estimated_cost=estimated_cost)
    
    async def record_cost(self, sandbox_id: uuid.UUID, execution_id: uuid.UUID,
                          cost_breakdown: dict[str, float]):
        """Record per-node cost breakdown and update sandbox total."""
        total = sum(cost_breakdown.values())
        sandbox = await self.repo.get(sandbox_id)
        sandbox.budget_spent_usd += total
        
        if sandbox.budget_spent_usd >= sandbox.budget_limit_usd:
            await self.abort_running_executions(sandbox_id, reason="budget_exceeded")
        
        await self.repo.update(sandbox)
    
    async def get_cost_breakdown(self, execution_id: uuid.UUID) -> CostBreakdown:
        """Get per-node cost breakdown for an execution."""
        execution = await self.execution_repo.get(execution_id)
        return CostBreakdown(
            total_usd=execution.total_cost_usd,
            per_node=execution.cost_breakdown,
            per_model={model: sum(c for n, c in execution.cost_breakdown.items()
                                  if execution.node_execution_log[n].get("model") == model)
                      for model in execution.models_used},
            budget_remaining=execution.sandbox.budget_limit_usd - execution.sandbox.budget_spent_usd
        )
```

### Audit & Reproducibility

**Full Execution Logging**
- Every sandbox execution captures:
  - Complete input (exact payload sent to agent)
  - Complete output (full agent response)
  - Per-node execution trace (input, output, timing, model, tokens, cost)
  - Environment snapshot (model versions, connector states, configuration)
  - Vault lease IDs (for credential audit, not credential values)
- Execution replay: re-run any previous execution with identical inputs for reproducibility
- Export formats:
  ```python
  class SandboxExporter:
      async def export(self, sandbox_id: uuid.UUID, 
                       format: Literal["json", "csv", "pdf"]) -> bytes:
          sandbox = await self.repo.get_with_executions(sandbox_id)
          
          if format == "json":
              return self.export_json(sandbox)      # Full structured data
          elif format == "csv":
              return self.export_csv(sandbox)        # Tabular metrics
          elif format == "pdf":
              return self.export_pdf(sandbox)        # Formatted report with charts
  ```
- Audit trail: every sandbox creation, execution, budget change, and cleanup logged in AuditLog (Agent-01)

## Output Structure

```
backend/
├── app/
│   ├── services/
│   │   ├── sandbox/
│   │   │   ├── __init__.py
│   │   │   ├── manager.py              # Sandbox lifecycle management
│   │   │   ├── provisioner.py          # K8s namespace provisioning
│   │   │   ├── credential_provider.py  # Dynamic Vault secret provisioning
│   │   │   ├── cleanup.py              # Expired sandbox cleanup (scheduled)
│   │   │   ├── executor.py             # Sandbox execution engine
│   │   │   ├── cost_guardrails.py      # Budget enforcement + per-node cost tracking
│   │   │   ├── exporter.py             # Export sandbox results (JSON/CSV/PDF)
│   │   │   └── schemas.py              # Sandbox Pydantic models
│   │   ├── arena/
│   │   │   ├── __init__.py
│   │   │   ├── engine.py               # Arena execution engine
│   │   │   ├── evaluator.py            # LLM-as-judge + metric-based evaluation
│   │   │   ├── statistics.py           # Statistical significance testing
│   │   │   ├── promoter.py             # Auto-promote winner
│   │   │   └── schemas.py              # Arena Pydantic models
│   │   └── benchmarks/
│   │       ├── __init__.py
│   │       ├── runner.py               # Benchmark suite runner
│   │       ├── scorer.py               # Scoring engine (exact, fuzzy, LLM judge)
│   │       ├── leaderboard.py          # Tenant-scoped leaderboard management
│   │       ├── built_in_suites.py      # Pre-built benchmark definitions
│   │       └── schemas.py              # Benchmark Pydantic models
│   ├── routers/
│   │   ├── sandbox.py                  # Sandbox CRUD + execution endpoints
│   │   ├── arena.py                    # Arena CRUD + results endpoints
│   │   └── benchmarks.py              # Benchmark suite + run + leaderboard endpoints
│   ├── models/
│   │   ├── sandbox.py                  # Sandbox, SandboxExecution models
│   │   ├── arena.py                    # Arena, ArenaVariant, ArenaResult models
│   │   └── benchmark.py               # BenchmarkSuite, BenchmarkRun, Leaderboard models
│   └── tasks/
│       └── sandbox_cleanup.py          # Scheduled task for sandbox cleanup
├── tests/
│   └── test_sandbox/
│       ├── __init__.py
│       ├── conftest.py                 # Sandbox test fixtures + K8s mocks
│       ├── test_sandbox_manager.py     # Sandbox lifecycle tests
│       ├── test_provisioner.py         # K8s namespace provisioning tests
│       ├── test_credential_provider.py # Dynamic secret provisioning tests
│       ├── test_cost_guardrails.py     # Budget enforcement tests
│       ├── test_arena_engine.py        # Arena execution + evaluation tests
│       ├── test_statistics.py          # Statistical significance tests
│       ├── test_benchmark_runner.py    # Benchmark execution tests
│       ├── test_leaderboard.py         # Leaderboard ranking tests
│       ├── test_exporter.py            # Export format tests
│       ├── test_isolation.py           # Cross-sandbox isolation verification
│       └── test_e2e_sandbox.py         # End-to-end sandbox flow tests
└── alembic/
    └── versions/
        └── xxx_add_sandbox_tables.py   # Migration for sandbox/arena/benchmark tables

frontend/
└── src/
    └── components/
        └── testing/
            ├── SandboxManager.tsx       # Sandbox list + create UI
            ├── SandboxDetail.tsx        # Sandbox detail with execution history
            ├── SandboxExecutionView.tsx  # Full execution trace viewer
            ├── ArenaConfig.tsx          # Arena setup wizard
            ├── ArenaResults.tsx         # A/B comparison dashboard
            ├── ArenaChart.tsx           # Statistical charts (box plots, bar charts)
            ├── BenchmarkBrowser.tsx     # Browse benchmark suites
            ├── BenchmarkRunner.tsx      # Run benchmark against agent
            ├── BenchmarkResults.tsx     # Results with per-case drill-down
            ├── Leaderboard.tsx          # Tenant leaderboard
            ├── CostBreakdown.tsx        # Per-node cost visualization
            └── ExportDialog.tsx         # Export results (JSON/CSV/PDF)

infra/
└── k8s/
    └── sandbox/
        ├── namespace-template.yaml     # Namespace creation template
        ├── network-policy.yaml         # Network isolation policy
        ├── resource-quota.yaml         # CPU/memory/storage limits
        ├── limit-range.yaml            # Per-pod resource limits
        ├── service-account.yaml        # Sandbox service account (minimal RBAC)
        └── cleanup-cronjob.yaml        # CronJob for sandbox cleanup
```

## API Endpoints (Complete)

```
# Sandbox CRUD
POST   /api/v1/sandboxes                        # Create sandbox for agent
GET    /api/v1/sandboxes                        # List sandboxes (filtered by tenant/workspace)
GET    /api/v1/sandboxes/{id}                   # Get sandbox details
PUT    /api/v1/sandboxes/{id}                   # Update sandbox config
DELETE /api/v1/sandboxes/{id}                   # Delete sandbox (triggers cleanup)
POST   /api/v1/sandboxes/{id}/extend            # Extend sandbox TTL

# Sandbox Execution
POST   /api/v1/sandboxes/{id}/execute           # Run agent in sandbox
GET    /api/v1/sandboxes/{id}/executions        # List executions in sandbox
GET    /api/v1/sandboxes/{id}/executions/{eid}  # Get execution details (full I/O)
POST   /api/v1/sandboxes/{id}/executions/{eid}/replay  # Replay execution with same inputs
POST   /api/v1/sandboxes/{id}/executions/{eid}/cancel  # Cancel running execution

# Sandbox Cost & Budget
GET    /api/v1/sandboxes/{id}/budget            # Get budget status + breakdown
PUT    /api/v1/sandboxes/{id}/budget            # Update budget limit
GET    /api/v1/sandboxes/{id}/executions/{eid}/cost  # Get per-node cost breakdown

# Sandbox Credentials
GET    /api/v1/sandboxes/{id}/credentials       # Check credential status
POST   /api/v1/sandboxes/{id}/credentials/provision   # Provision dynamic credentials

# Sandbox Export
GET    /api/v1/sandboxes/{id}/export            # Export sandbox results (JSON/CSV/PDF)
GET    /api/v1/sandboxes/{id}/executions/{eid}/export  # Export single execution

# Arena Mode
POST   /api/v1/arenas                           # Create arena (A/B test)
GET    /api/v1/arenas                           # List arenas
GET    /api/v1/arenas/{id}                      # Get arena details + results
PUT    /api/v1/arenas/{id}                      # Update arena config
DELETE /api/v1/arenas/{id}                      # Cancel/delete arena
POST   /api/v1/arenas/{id}/start               # Start arena execution
POST   /api/v1/arenas/{id}/stop                # Stop arena execution
GET    /api/v1/arenas/{id}/results             # Get comparative results
GET    /api/v1/arenas/{id}/results/statistical  # Get statistical analysis
POST   /api/v1/arenas/{id}/promote             # Promote winner to environment
GET    /api/v1/arenas/{id}/variants            # List arena variants
GET    /api/v1/arenas/{id}/variants/{vid}/runs  # Get runs for a variant

# Benchmark Suite
GET    /api/v1/benchmarks                       # List benchmark suites
POST   /api/v1/benchmarks                       # Create custom benchmark suite
GET    /api/v1/benchmarks/{id}                  # Get suite details + test cases
PUT    /api/v1/benchmarks/{id}                  # Update suite
DELETE /api/v1/benchmarks/{id}                  # Delete suite
GET    /api/v1/benchmarks/built-in              # List built-in suites

# Benchmark Runs
POST   /api/v1/benchmarks/{id}/run              # Run benchmark against agent
GET    /api/v1/benchmarks/{id}/runs             # List runs for suite
GET    /api/v1/benchmarks/{id}/runs/{rid}       # Get run results
GET    /api/v1/benchmarks/{id}/runs/{rid}/cases  # Get per-case results

# Leaderboard
GET    /api/v1/benchmarks/{id}/leaderboard      # Get leaderboard for suite
GET    /api/v1/benchmarks/leaderboard/overview   # Cross-suite leaderboard summary
```

## Verify Commands

```bash
# Sandbox module importable
cd ~/Scripts/Archon && python -c "
from backend.app.services.sandbox.manager import SandboxManager
from backend.app.services.sandbox.provisioner import NamespaceProvisioner
from backend.app.services.sandbox.credential_provider import SandboxCredentialProvider
from backend.app.services.sandbox.cost_guardrails import CostGuardrailService
from backend.app.services.sandbox.exporter import SandboxExporter
print('Sandbox services OK')
"

# Arena module importable
cd ~/Scripts/Archon && python -c "
from backend.app.services.arena.engine import ArenaEngine
from backend.app.services.arena.evaluator import ArenaEvaluator
from backend.app.services.arena.statistics import StatisticalAnalyzer
from backend.app.services.arena.promoter import VariantPromoter
print('Arena services OK')
"

# Benchmark module importable
cd ~/Scripts/Archon && python -c "
from backend.app.services.benchmarks.runner import BenchmarkRunner
from backend.app.services.benchmarks.scorer import BenchmarkScorer
from backend.app.services.benchmarks.leaderboard import LeaderboardService
from backend.app.services.benchmarks.built_in_suites import BUILT_IN_SUITES
print('Benchmark services OK')
"

# Data models importable
cd ~/Scripts/Archon && python -c "
from backend.app.models.sandbox import Sandbox, SandboxExecution
from backend.app.models.arena import Arena, ArenaVariant
from backend.app.models.benchmark import BenchmarkSuite, BenchmarkRun, BenchmarkLeaderboard
print('All sandbox/arena/benchmark models OK')
"

# Tests pass
cd ~/Scripts/Archon/backend && python -m pytest tests/test_sandbox/ --tb=short -q

# K8s manifests are valid YAML
find ~/Scripts/Archon/infra/k8s/sandbox -name '*.yaml' -exec python -c "import yaml,sys; yaml.safe_load(open(sys.argv[1])); print(f'Valid: {sys.argv[1]}')" {} \;

# API routes registered
cd ~/Scripts/Archon && python -c "
from backend.app.main import app
routes = [r.path for r in app.routes]
assert '/api/v1/sandboxes' in str(routes), 'Missing sandbox routes'
assert '/api/v1/arenas' in str(routes), 'Missing arena routes'
assert '/api/v1/benchmarks' in str(routes), 'Missing benchmark routes'
print('All sandbox/arena/benchmark routes OK')
"

# No production secrets accessible from sandbox tests
cd ~/Scripts/Archon && ! grep -rn 'archon/prod/' --include='*.py' backend/app/services/sandbox/ || echo 'FAIL: sandbox references production secrets'
```

## Learnings Protocol

Before starting, read `.sdd/learnings/*.md` for known pitfalls from previous sessions.
After completing work, report any pitfalls or patterns discovered so the orchestrator can capture them via `node ~/Projects/copilot-sdd/dist/cli.js learn`.

## Acceptance Criteria

- [ ] Sandbox containers start within 5 seconds in K8s namespace with network policies and resource quotas enforced
- [ ] Dynamic Vault secrets provisioned per sandbox — sandbox credentials auto-expire with sandbox TTL
- [ ] Sandboxes CANNOT access production secrets — isolation verified by test attempting cross-context access
- [ ] No data leakage between sandbox instances (separate namespaces, separate credentials, separate storage)
- [ ] Resource limits enforced: OOMKill at memory limit, timeout at max duration, budget abort at cost limit
- [ ] Per-node cost breakdown available for every sandbox execution
- [ ] Cost guardrails: execution aborted when sandbox budget exceeded, with budget alert at configurable threshold
- [ ] Arena Mode: run 2+ agent versions side-by-side with identical inputs, parallel execution
- [ ] Arena metrics: latency, cost, quality score (LLM-as-judge), accuracy, user preference all captured
- [ ] Statistical significance testing: t-test and chi-squared with configurable significance level (default p<0.05)
- [ ] Arena auto-promotion: winner promoted to staging/production (with optional approval gate)
- [ ] Benchmark Suite: 7 built-in categories (reasoning, coding, summarization, classification, extraction, conversation, tool_use)
- [ ] Custom benchmark creation via API with custom test cases and scoring methods
- [ ] Tenant-scoped leaderboard with rankings by score, latency, and cost
- [ ] Full audit trail: every sandbox execution logged with complete input/output for reproducibility
- [ ] Execution replay: re-run any previous execution with identical inputs → same results (deterministic check)
- [ ] Export: sandbox results exportable as JSON, CSV, and PDF
- [ ] Auto-cleanup: expired sandboxes cleaned up within 60 seconds (credentials revoked, namespace deleted, logs archived)
- [ ] All sandbox/arena/benchmark state persisted to database — no data loss on restart
