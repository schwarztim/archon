# Agent-03: Natural Language → Agent Wizard (Enterprise)

> **Phase**: 1 | **Dependencies**: Agent-01 (Core Backend), Agent-00 (Secrets Vault) | **Priority**: HIGH
> **The zero-to-agent pipeline. Non-technical users describe what they want; this agent delivers a production-ready, security-scanned, cost-estimated LangGraph agent.**

---

## Identity

You are Agent-03: the Natural Language → Agent Wizard. You implement the full "Describe → Plan → Build → Validate" pipeline that converts plain-English descriptions into production-grade LangGraph agents. Every generated agent inherits the creator's tenant, workspace, and permission scope. Every generated graph includes auth nodes for any connectors it uses. Every secret reference uses Vault paths — never raw keys.

## Mission

Build a 4-step wizard service that:
1. Accepts natural language descriptions and generates structured agent plans with cost estimates, model recommendations, and connector/secrets manifests
2. Converts approved plans into LangGraph JSON definitions, Python source code, and deployment configs
3. Validates generated agents via security scan (Agent-11 DLP), cost estimation (Agent-09), and compliance checks before any deployment
4. Supports iterative refinement with automatic re-generation (up to 3 iterations) when validation fails
5. Routes code-generation tasks to the optimal LLM via Agent-07's model router
6. Layers prompts (system → org → department → user) for tenant-specific generation behavior
7. Checks the template library (Agent-04) before generating from scratch — if a template matches >70% of the description, suggest the template-based approach first

## Requirements

### Auth-Aware Code Generation

**Tenant & Workspace Inheritance**
- Every generated agent definition automatically includes the creator's `tenant_id`, `workspace_id`, and `owner_id`
- Generated agent `visibility` defaults to `workspace` (configurable via org policy)
- The generated agent's `graph_definition` includes auth nodes for every connector referenced:
  ```python
  class AuthNodeConfig(BaseModel):
      """Injected into generated graphs for each connector that requires credentials."""
      connector_type: str          # "salesforce", "s3", "slack", etc.
      vault_path: str              # "archon/{tenant_id}/connectors/{connector_type}"
      auth_method: str             # "oauth2", "api_key", "iam_role"
      scopes: list[str]            # Required OAuth scopes
      refresh_strategy: str        # "auto" | "manual" | "on_expiry"
  ```
- RBAC check at generation time: user must have `agents:create` permission in the target workspace
- If user lacks a required permission for a connector, the plan step surfaces it as a blocker

**Secrets-Aware Templates**
- When the NL description mentions external services (e.g., "connect to Salesforce", "read from S3", "send via Twilio"), the wizard:
  1. Detects the connector type via NLP entity extraction
  2. Looks up the connector's credential schema from the connector registry (Agent-02)
  3. Adds a `credential_requirements` section to the plan with Vault paths:
     ```json
     {
       "credential_requirements": [
         {
           "connector": "salesforce",
           "vault_path": "archon/{tenant_id}/connectors/salesforce",
           "required_fields": ["client_id", "client_secret", "refresh_token"],
           "status": "configured" | "missing",
           "setup_url": "/settings/connectors/salesforce/configure"
         }
       ]
     }
     ```
  4. If credentials are missing, the plan includes a setup link to the Secrets Vault (Agent-00)
  5. Raw API keys, tokens, or passwords are NEVER included in any generated code or plan — only Vault path references

### 4-Step Flow with Validation

**Step 1 — Describe**
- Accept natural language input from user (text, voice transcription, or pasted example)
- NLP preprocessing:
  - Intent extraction: what the agent should DO
  - Entity extraction: which services, data sources, models are mentioned
  - Constraint extraction: performance requirements, cost limits, compliance needs
- Template matching (Agent-04 integration):
  - Compute semantic similarity between description and all templates in the tenant's library
  - If any template scores >70% similarity, present it as a suggested starting point
  - User can choose: "Use template" (fork + customize) or "Generate from scratch"
- Ambiguity resolution:
  - If the description is ambiguous, generate clarifying questions (max 3)
  - "Did you mean…?" suggestions for common patterns
  - Proceed with best interpretation if user doesn't clarify within 30 seconds (async mode)

**Step 2 — Plan**
- LLM generates a structured `NLBuildPlan` from the processed description:
  ```python
  class NLBuildPlan(BaseModel):
      """Structured plan generated from natural language description."""
      plan_id: uuid.UUID = Field(default_factory=uuid.uuid4)
      request_id: uuid.UUID                   # Links back to the NLBuildRequest
      agent_name: str                          # Suggested name
      agent_slug: str                          # URL-safe slug
      description: str                         # Cleaned-up description
      agent_type: Literal["workflow", "conversational", "autonomous", "hybrid"]
      
      # Graph structure
      nodes: list[PlannedNode]                 # Ordered list of graph nodes
      edges: list[PlannedEdge]                 # Connections between nodes
      entry_point: str                         # Starting node ID
      
      # Resource requirements
      models_needed: list[ModelRequirement]    # LLMs required (with fallbacks)
      connectors_needed: list[ConnectorRequirement]  # External service connections
      tools_needed: list[ToolRequirement]      # LangChain tools to include
      
      # Security & compliance
      credential_requirements: list[CredentialRequirement]  # Vault paths needed
      required_permissions: list[str]          # Permissions the generated agent needs
      dlp_sensitivity: Literal["low", "medium", "high", "critical"]
      
      # Cost estimation
      estimated_cost_per_run: CostEstimate     # Breakdown by model, API calls, compute
      estimated_latency_ms: int                # p50 latency estimate
      estimated_tokens_per_run: TokenEstimate  # Input + output tokens per model
      
      # Metadata
      complexity_score: float                  # 0.0-1.0
      confidence_score: float                  # How confident the planner is (0.0-1.0)
      warnings: list[str]                      # Potential issues identified
      suggested_test_cases: list[TestCase]     # Auto-generated test scenarios
      template_match: TemplateMatch | None     # If a template was matched
      
      created_at: datetime
      expires_at: datetime                     # Plan expires after 24h
  ```
- Supporting plan models:
  ```python
  class PlannedNode(BaseModel):
      node_id: str
      node_type: Literal["llm_call", "tool_invocation", "conditional", "human_approval",
                          "parallel", "sub_agent", "data_transform", "output", "auth"]
      label: str
      description: str
      config: dict                             # Node-specific configuration
      model: str | None                        # For LLM nodes: which model to use
      retry_policy: RetryPolicy | None
      timeout_seconds: int = 60
  
  class PlannedEdge(BaseModel):
      source: str
      target: str
      condition: str | None                    # For conditional edges
      label: str | None
  
  class ModelRequirement(BaseModel):
      model_id: str                            # "gpt-4o", "claude-sonnet-4-20250514", "gemini-2.0-flash"
      purpose: str                             # "code_generation", "reasoning", "classification"
      fallback: str | None                     # Fallback model if primary unavailable
      estimated_tokens: int
      estimated_cost_usd: float
  
  class ConnectorRequirement(BaseModel):
      connector_type: str
      operations: list[str]                    # ["read", "write", "query"]
      vault_path: str
      status: Literal["configured", "missing", "expired"]
  
  class CostEstimate(BaseModel):
      total_usd: float
      breakdown: dict[str, float]              # {"gpt-4o": 0.03, "salesforce_api": 0.001, ...}
      confidence: Literal["low", "medium", "high"]
  
  class TemplateMatch(BaseModel):
      template_id: uuid.UUID
      template_name: str
      similarity_score: float                  # 0.0-1.0
      differences: list[str]                   # What the template doesn't cover
  ```
- Plan presentation to user:
  - Visual flow diagram (Mermaid markdown + React Flow JSON)
  - Cost breakdown table
  - Required credentials status (configured ✅ / missing ❌)
  - Warnings and suggestions
- User can: approve, edit (modify nodes/edges in UI), reject, or request re-plan with feedback

**Step 3 — Build (Code Generation)**
- Take approved `NLBuildPlan` and generate:
  1. **LangGraph JSON definition**: importable to React Flow canvas (Agent-02 format)
  2. **Python source code**: standalone executable with type hints, docstrings, error handling
  3. **Requirements manifest**: Python dependencies, connector SDKs, model API packages
  4. **Deployment config**: environment variables (Vault references), resource limits, scaling hints
- Multi-LLM code generation via Agent-07 router:
  ```python
  class CodeGenerationRouter:
      """Routes code generation tasks to the optimal model."""
      ROUTING_TABLE = {
          "graph_structure":    {"primary": "claude-sonnet-4-20250514", "fallback": "gpt-4o"},
          "python_code":        {"primary": "claude-sonnet-4-20250514", "fallback": "gpt-4o"},
          "test_generation":    {"primary": "gpt-4o", "fallback": "claude-haiku"},
          "documentation":      {"primary": "gemini-2.0-flash", "fallback": "gpt-4o-mini"},
          "security_review":    {"primary": "claude-sonnet-4-20250514", "fallback": "gpt-4o"},
      }
      
      async def generate(self, task_type: str, plan: NLBuildPlan) -> str:
          model = await self.agent07_router.select_model(
              task_type=task_type,
              complexity=plan.complexity_score,
              tenant_preferences=await self.get_tenant_model_prefs()
          )
          return await self.call_model(model, task_type, plan)
  ```
- Code generation conventions:
  - All generated Python follows project conventions (`from __future__ import annotations`, strict type hints)
  - No hardcoded values — all configuration via environment/Vault
  - Error handling on every node (try/except with structured error output)
  - Logging via `structlog` with correlation IDs
  - Generated code includes inline comments explaining each node's purpose

**Step 4 — Validate**
- Automated validation pipeline (all must pass before deployment):
  ```python
  class ValidationPipeline:
      """Sequential validation — any failure blocks deployment."""
      
      async def validate(self, build_result: NLBuildResult) -> ValidationReport:
          checks = []
          
          # 1. Syntax validation
          checks.append(await self.check_syntax(build_result.python_code))
          
          # 2. Security scan (Agent-11 DLP integration)
          checks.append(await self.agent11_dlp_scan(build_result))
          # - No hardcoded secrets (regex + entropy analysis)
          # - No prompt injection vulnerabilities
          # - No PII leakage in prompts or outputs
          # - No unauthorized data exfiltration paths
          
          # 3. Logic validation
          checks.append(await self.check_logic(build_result.graph_definition))
          # - No infinite loops (cycle detection)
          # - No unreachable nodes (graph connectivity)
          # - All conditional edges have else branches
          # - Error handling on every external call
          
          # 4. Cost estimation (Agent-09 integration)
          checks.append(await self.agent09_cost_check(build_result))
          # - Per-run cost within tenant budget
          # - Monthly projected cost flagged if >threshold
          # - Cost approval gate triggered if >$1.00/run
          
          # 5. Compliance check
          checks.append(await self.check_compliance(build_result))
          # - Respects tenant's model allowlist
          # - Respects tenant's connector allowlist
          # - Data residency requirements met
          # - Guardrail policies satisfied
          
          # 6. Approval gate (if required)
          if any(c.requires_approval for c in checks):
              checks.append(ValidationCheck(
                  name="approval_required",
                  status="pending",
                  message="Manual approval required before deployment",
                  approvers=await self.get_approvers(build_result)
              ))
          
          return ValidationReport(checks=checks, passed=all(c.passed for c in checks))
  ```
- If validation fails:
  1. Extract error context (which check failed, why, specific line numbers)
  2. Feed error context back to the code generation LLM
  3. Re-generate with error-aware prompt (up to 3 auto-refinement iterations)
  4. If still failing after 3 iterations, escalate to human review with full context

### Prompt Layering System

**Hierarchical Prompt Configuration**
- Each NL→Agent generation uses a layered prompt stack:
  ```
  [System Prompt]       → Base generation instructions (maintained by platform team)
  [Org Prompt]          → Organization-wide conventions (set by tenant_admin)
  [Department Prompt]   → Department-specific rules (set by workspace_admin)
  [User Prompt]         → The actual user description
  ```
- Each layer is configurable per tenant via the admin UI:
  ```python
  class PromptLayer(SQLModel, table=True):
      id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
      tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
      workspace_id: uuid.UUID | None          # None = org-wide
      layer_type: Literal["system", "org", "department", "user"]
      content: str                             # The prompt text
      priority: int = 0                        # Higher = applied later (overrides)
      active: bool = True
      created_by: uuid.UUID
      created_at: datetime
      updated_at: datetime | None
  ```
- Example org prompt: "All generated agents must include a human approval node before any write operation to external systems."
- Example department prompt: "Sales agents must always check CRM connector status before proceeding. Use GPT-4o for customer-facing text generation."
- Prompts are composed at generation time: `system + org + department + user`
- Prompt injection protection: each layer is sanitized and wrapped in XML-tagged boundaries

### Feedback Loop & Auto-Refinement

**Iterative Refinement**
- After each step, users can provide natural language feedback:
  - "Make it also handle returns" → planner adds return-handling nodes
  - "Use Claude instead of GPT-4" → coder switches model references
  - "Add an approval step before sending emails" → planner inserts HumanApproval node
- Feedback is appended to the generation context (not replacing — additive)
- Auto-refinement on validation failure:
  ```python
  class AutoRefinementLoop:
      MAX_ITERATIONS = 3
      
      async def refine(self, build_result: NLBuildResult, 
                       validation_report: ValidationReport) -> NLBuildResult:
          for iteration in range(self.MAX_ITERATIONS):
              error_context = self.extract_error_context(validation_report)
              refined_result = await self.regenerate_with_context(
                  original_plan=build_result.plan,
                  previous_code=build_result.python_code,
                  errors=error_context,
                  iteration=iteration + 1
              )
              validation_report = await self.validate(refined_result)
              if validation_report.passed:
                  return refined_result
          
          # Escalate to human review
          await self.escalate_to_review(build_result, validation_report)
          raise WizardEscalationError("Auto-refinement exhausted after 3 iterations")
  ```
- Each refinement iteration is tracked in the `NLBuildResult` with diffs

### Core Data Models

**NLBuildRequest**
```python
class NLBuildRequest(SQLModel, table=True):
    """Represents a user's request to generate an agent from natural language."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    description: str                           # Raw user input
    description_cleaned: str | None            # NLP-processed input
    intent: str | None                         # Extracted intent
    entities: list[str] = Field(default_factory=list)  # Extracted entities
    constraints: dict = Field(default_factory=dict)    # Extracted constraints
    
    # Auth context (inherited by generated agent)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    workspace_id: uuid.UUID = Field(foreign_key="workspaces.id")
    owner_id: uuid.UUID = Field(foreign_key="users.id")
    
    # Prompt layers used
    prompt_layers: list[uuid.UUID] = Field(default_factory=list)
    
    # Wizard state
    status: Literal["describing", "planning", "building", "validating", 
                     "refining", "completed", "failed", "escalated"] = "describing"
    current_step: int = 1                      # 1-4
    iteration: int = 0                         # Refinement iteration count
    
    # Template match
    matched_template_id: uuid.UUID | None
    template_similarity: float | None
    used_template: bool = False
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime | None
    completed_at: datetime | None
    
    # Relationships
    plan: "NLBuildPlan | None" = None
    result: "NLBuildResult | None" = None
```

**NLBuildResult**
```python
class NLBuildResult(SQLModel, table=True):
    """The output of a successful wizard run."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    request_id: uuid.UUID = Field(foreign_key="nl_build_requests.id")
    plan_id: uuid.UUID = Field(foreign_key="nl_build_plans.id")
    
    # Generated artifacts
    graph_definition: dict                     # LangGraph JSON (React Flow compatible)
    python_code: str                           # Standalone Python source
    requirements: list[str]                    # pip dependencies
    deployment_config: dict                    # Env vars (Vault refs), resource limits
    test_cases: list[dict]                     # Auto-generated test scenarios
    documentation: str                         # Auto-generated agent documentation (Markdown)
    
    # Validation results
    validation_report: dict                    # Full validation report
    validation_passed: bool
    refinement_history: list[dict]             # History of auto-refinement iterations
    
    # Deployed agent reference
    agent_id: uuid.UUID | None = Field(foreign_key="agents.id")  # Created after deployment
    sandbox_execution_id: uuid.UUID | None     # Sandbox test run ID
    
    # Cost tracking
    generation_cost: float                     # Cost of the LLM calls to generate this agent
    generation_models_used: list[str]          # Which models were used for generation
    generation_tokens: dict                    # Token breakdown per model
    
    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    generation_duration_ms: int                # How long the full pipeline took
```

### Multi-LLM Support

- Code generation tasks are routed to the optimal model via Agent-07:
  - **Graph structure generation**: Claude Sonnet (best at structured JSON output)
  - **Python code generation**: Claude Sonnet or GPT-4o (depending on complexity)
  - **Test case generation**: GPT-4o (strong at edge case identification)
  - **Documentation generation**: Gemini Flash (fast, cost-effective for text)
  - **Security review**: Claude Sonnet (best at reasoning about code safety)
- Model selection respects tenant's model allowlist (some tenants restrict to specific providers)
- Fallback chain: if primary model is unavailable or rate-limited, fall back to next option
- Each model call includes cost tracking (tokens in/out, cost per call)

## Output Structure

```
backend/
├── app/
│   ├── services/
│   │   └── nl_wizard/
│   │       ├── __init__.py
│   │       ├── planner.py               # NL → NLBuildPlan generation
│   │       ├── coder.py                 # NLBuildPlan → code generation (multi-LLM)
│   │       ├── validator.py             # Security scan, cost check, compliance
│   │       ├── deployer.py              # Sandbox deployment after validation
│   │       ├── feedback.py              # Iterative refinement loop
│   │       ├── template_matcher.py      # Semantic similarity matching (Agent-04)
│   │       ├── prompt_layering.py       # System/org/dept/user prompt composition
│   │       ├── entity_extractor.py      # NLP entity extraction (connectors, models)
│   │       ├── secrets_resolver.py      # Credential requirement detection & Vault path resolution
│   │       ├── auth_injector.py         # Auth node injection into generated graphs
│   │       ├── cost_estimator.py        # Pre-generation cost estimation
│   │       └── schemas.py              # NLBuildRequest, NLBuildPlan, NLBuildResult, etc.
│   ├── routers/
│   │   └── wizard.py                    # All wizard API endpoints
│   ├── models/
│   │   └── wizard.py                    # SQLModel tables for wizard state
│   └── auth/
│       └── wizard_permissions.py        # Wizard-specific RBAC checks
├── tests/
│   └── test_nl_wizard/
│       ├── __init__.py
│       ├── conftest.py                  # Wizard test fixtures
│       ├── test_planner.py              # Plan generation tests
│       ├── test_coder.py                # Code generation tests
│       ├── test_validator.py            # Validation pipeline tests
│       ├── test_feedback.py             # Refinement loop tests
│       ├── test_template_matcher.py     # Template matching tests
│       ├── test_prompt_layering.py      # Prompt composition tests
│       ├── test_secrets_resolver.py     # Credential detection tests
│       ├── test_auth_injector.py        # Auth node injection tests
│       └── test_e2e_wizard.py           # End-to-end wizard flow tests
└── alembic/
    └── versions/
        └── xxx_add_wizard_tables.py     # Migration for wizard tables

frontend/
└── src/
    └── components/
        └── wizard/
            ├── WizardFlow.tsx           # 4-step wizard UI
            ├── DescribeStep.tsx          # NL input with suggestions
            ├── PlanStep.tsx             # Plan review with visual graph
            ├── BuildStep.tsx            # Generation progress + code preview
            ├── ValidateStep.tsx         # Validation results + approval
            ├── TemplateSuggestion.tsx   # Template match card
            ├── CostBreakdown.tsx        # Cost estimation display
            ├── CredentialStatus.tsx     # Missing credentials indicator
            └── FeedbackPanel.tsx        # Refinement feedback input
```

## API Endpoints (Complete)

```
# Wizard Flow
POST   /api/v1/wizard/describe              # Submit NL description → get processed request
GET    /api/v1/wizard/requests               # List user's wizard requests (paginated)
GET    /api/v1/wizard/requests/{id}          # Get request details + current state
DELETE /api/v1/wizard/requests/{id}          # Cancel/delete a wizard request

# Planning
POST   /api/v1/wizard/requests/{id}/plan     # Generate plan from description
GET    /api/v1/wizard/requests/{id}/plan     # Get current plan
PUT    /api/v1/wizard/requests/{id}/plan     # Update/edit plan (user modifications)
POST   /api/v1/wizard/requests/{id}/plan/approve   # Approve plan → trigger build
POST   /api/v1/wizard/requests/{id}/plan/reject    # Reject plan → re-plan with feedback

# Building
POST   /api/v1/wizard/requests/{id}/build    # Trigger code generation (requires approved plan)
GET    /api/v1/wizard/requests/{id}/build    # Get build status + artifacts
GET    /api/v1/wizard/requests/{id}/build/code      # Get generated Python code
GET    /api/v1/wizard/requests/{id}/build/graph     # Get generated LangGraph JSON
GET    /api/v1/wizard/requests/{id}/build/config    # Get deployment config

# Validation
POST   /api/v1/wizard/requests/{id}/validate # Trigger validation pipeline
GET    /api/v1/wizard/requests/{id}/validate # Get validation report
POST   /api/v1/wizard/requests/{id}/validate/approve  # Manual approval (if required)

# Refinement
POST   /api/v1/wizard/requests/{id}/feedback # Submit feedback for refinement
GET    /api/v1/wizard/requests/{id}/history  # Get refinement iteration history

# Deployment
POST   /api/v1/wizard/requests/{id}/deploy   # Deploy validated agent (to sandbox or production)
GET    /api/v1/wizard/requests/{id}/deploy   # Get deployment status

# Template Matching
POST   /api/v1/wizard/match-template         # Find matching templates for a description
GET    /api/v1/wizard/templates/suggestions   # Get suggested templates based on user's history

# Prompt Layers (Admin)
GET    /api/v1/wizard/prompts                # List prompt layers for tenant
POST   /api/v1/wizard/prompts                # Create prompt layer (org/department)
PUT    /api/v1/wizard/prompts/{id}           # Update prompt layer
DELETE /api/v1/wizard/prompts/{id}           # Delete prompt layer
GET    /api/v1/wizard/prompts/preview        # Preview composed prompt stack

# Credential Resolution
GET    /api/v1/wizard/requests/{id}/credentials  # Check credential status for plan
POST   /api/v1/wizard/requests/{id}/credentials/resolve  # Trigger credential setup flow
```

## Verify Commands

```bash
# Wizard module importable with all submodules
cd ~/Scripts/Archon && python -c "
from backend.app.services.nl_wizard import planner, coder, validator, deployer, feedback
from backend.app.services.nl_wizard.template_matcher import TemplateMatcher
from backend.app.services.nl_wizard.prompt_layering import PromptLayerComposer
from backend.app.services.nl_wizard.secrets_resolver import SecretsResolver
from backend.app.services.nl_wizard.auth_injector import AuthNodeInjector
from backend.app.services.nl_wizard.schemas import NLBuildRequest, NLBuildPlan, NLBuildResult
print('All wizard modules OK')
"

# Data models importable
cd ~/Scripts/Archon && python -c "
from backend.app.models.wizard import NLBuildRequest, NLBuildPlan, NLBuildResult
print('Wizard models OK')
"

# Tests pass
cd ~/Scripts/Archon/backend && python -m pytest tests/test_nl_wizard/ --tb=short -q

# API routes registered
cd ~/Scripts/Archon && python -c "
from backend.app.main import app
routes = [r.path for r in app.routes]
assert '/api/v1/wizard/describe' in str(routes), f'Missing wizard routes: {routes}'
print('Wizard routes OK')
"

# No hardcoded secrets in wizard code
cd ~/Scripts/Archon && ! grep -rn 'api_key\s*=\s*\"[^\"]*\"' --include='*.py' backend/app/services/nl_wizard/ || echo 'FAIL: hardcoded secrets found'

# Prompt layering works
cd ~/Scripts/Archon && python -c "
from backend.app.services.nl_wizard.prompt_layering import PromptLayerComposer
composer = PromptLayerComposer()
assert composer is not None
print('Prompt layering OK')
"

# Auth injection works
cd ~/Scripts/Archon && python -c "
from backend.app.services.nl_wizard.auth_injector import AuthNodeInjector
injector = AuthNodeInjector()
assert injector is not None
print('Auth injection OK')
"
```

## Learnings Protocol

Before starting, read `.sdd/learnings/*.md` for known pitfalls from previous sessions.
After completing work, report any pitfalls or patterns discovered so the orchestrator can capture them via `node ~/Projects/copilot-sdd/dist/cli.js learn`.

## Acceptance Criteria

- [ ] User describes "a customer support bot that checks order status via Salesforce" → wizard generates a working agent with Salesforce auth node and Vault credential reference
- [ ] Generated agent inherits creator's `tenant_id`, `workspace_id`, and `owner_id`
- [ ] Generated graph includes auth nodes for every connector referenced in the description
- [ ] Credential requirements section shows Vault paths (never raw keys) with configured/missing status
- [ ] Plan includes cost estimate (per-run and monthly projection) with breakdown by model and connector
- [ ] Template matching: description "customer support chatbot" returns >70% match against existing CS template and suggests template-based approach
- [ ] Prompt layering: org prompt "all agents must include approval before writes" → generated agent includes HumanApproval node before any write operation
- [ ] Multi-LLM routing: code generation uses Claude for Python, Gemini for docs (respects tenant model allowlist)
- [ ] Validation catches: hardcoded secrets, infinite loops, missing auth nodes, cost overruns
- [ ] Auto-refinement: when validation fails (e.g., missing error handling), wizard auto-fixes and re-validates (up to 3 iterations)
- [ ] Feedback loop: "make it also handle returns" → planner adds return-handling nodes without losing existing nodes
- [ ] Generated Python code is syntactically valid, has type hints, uses structlog, and passes `ruff check`
- [ ] Generated LangGraph JSON imports cleanly into the React Flow canvas
- [ ] Sandbox deployment runs and returns test results within 30 seconds
- [ ] RBAC enforced: user without `agents:create` permission gets 403 on wizard endpoints
- [ ] All wizard state persisted to database — browser refresh doesn't lose progress
- [ ] Zero plaintext secrets in generated code, plans, logs, or API responses
