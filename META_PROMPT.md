# Archon — Meta-Prompt: Generate All 22 Agent Build Prompts

> **What this is**: A prompt you paste into any agentic AI tool (Copilot CLI, Claude Code, Cursor, Codex, etc.).
> It instructs the AI to study Dify and other OSS platforms, then produce 22 standalone build prompts —
> one per Archon agent — each ready to hand directly to a sub-agent that will write the actual code.
>
> **Run from any directory. Self-orienting.**

---

You are **Archon Prompt Architect** — a senior platform engineer whose job is to produce 22 implementation-ready build prompts for the Archon AI orchestration platform.

You will NOT write application code. You will output **22 markdown prompt files**, one per agent, saved to `~/Scripts/Archon/agents/build-prompts/agent-XX-build.md`. Each file is a complete, standalone instruction set that a separate AI coding agent will receive to build that piece of the platform.

## Phase 1: Research (do this FIRST before writing any prompts)

### 1A — Study Dify (primary reference)

Dify is the closest open-source platform to what we're building. Clone or browse it and extract the patterns we want to steal:

```bash
# Clone Dify for reference (if not already present)
cd ~/Scripts && git clone --depth 1 https://github.com/langgenius/dify.git dify-reference 2>/dev/null || true
```

Study these specific areas of Dify's codebase and document what you learn:

| Archon Agent | What to Study in Dify | Where to Look |
|---|---|---|
| 01 Core Backend | App model schema, how they structure agent configs | `api/models/model.py`, `api/models/workflow.py` |
| 02 Visual Builder | React Flow graph implementation, node types, serialization | `web/app/components/workflow/` |
| 03 NL Wizard | How they handle "generate from description" | `web/app/components/app/create-app-dialog/` |
| 04 Templates | Template gallery, one-click instantiate, explore page | `web/app/components/explore/`, `api/services/app_dsl_service.py` |
| 05 Agent Wizard | App creation flow, configuration panels | `web/app/components/app/configuration/` |
| 06 Executions | Workflow run tracing, step-by-step logs, token tracking | `web/app/components/workflow/run/`, `api/core/workflow/` |
| 07 Workflows | Workflow editor, node config panels, iteration/parallel nodes | `web/app/components/workflow/nodes/`, `api/core/workflow/nodes/` |
| 08 Model Router | Model provider management, credential forms, load balancing | `web/app/components/header/account-setting/model-provider-page/`, `api/core/model_runtime/` |
| 09 Connectors | Tool/API integration, OAuth flows, credential management | `web/app/components/tools/`, `api/core/tools/` |
| 10 Lifecycle | App publishing, environment management | `api/services/app_service.py` |
| 11 Cost Engine | Token usage tracking, billing, quota management | `api/core/model_runtime/model_providers/`, billing models |
| 12 DLP | Content moderation, sensitive word filters | `api/core/moderation/`, `api/core/app/apps/advanced_chat/app_generator.py` |
| 13 Governance | N/A in Dify — design from scratch |
| 14 SentinelScan | N/A in Dify — design from scratch |
| 15 MCP Apps | N/A in Dify — design from scratch |
| 16 SSO/Users | Workspace/member management, SSO (enterprise) | `web/app/components/header/account-setting/members-page/`, `api/services/workspace_service.py` |
| 17 Secrets | How Dify stores provider API keys | `api/core/model_runtime/model_providers/`, `api/models/provider.py` |
| 18 Audit | Operation logs | `api/services/operation_log_service.py` if exists |
| 19 Settings | System settings pages | `web/app/components/header/account-setting/` |
| 20 Dashboard | App overview, analytics | `web/app/components/app/overview/` |

### 1B — Also scan these for specific patterns

| Project | Clone Command | What to Extract |
|---|---|---|
| Flowise | `git clone --depth 1 https://github.com/FlowiseAI/Flowise.git ~/Scripts/flowise-reference 2>/dev/null \|\| true` | Node palette UX, drag-drop canvas, chatflow testing |
| Coze Studio | `git clone --depth 1 https://github.com/coze-dev/coze-studio.git ~/Scripts/coze-reference 2>/dev/null \|\| true` | Plugin system, workflow nodes, knowledge base UI |
| Idun | `git clone --depth 1 https://github.com/Idun-Group/idun-agent-platform.git ~/Scripts/idun-reference 2>/dev/null \|\| true` | Guardrails integration, SSO/RBAC, MCP tool control, OpenTelemetry tracing |

### 1C — Read Archon's existing state

```bash
cd ~/Scripts/Archon

# Agent definitions (what each agent must do — 968 lines)
cat agents/AGENT_DEFINITIONS.md

# Dependency graph, acceptance criteria, gap inventory (646 lines)
cat agents/swarm-state.json

# Coding standards every agent must follow
cat agents/AGENT_RULES.md

# Gap coverage matrix and critical path
cat agents/DEFINITION_COMPLETE_REPORT.md
```

Also explore the current codebase to understand what already exists:

```bash
# Backend routes (what endpoints exist)
ls backend/app/routes/*.py

# Frontend pages (what UI exists)
ls frontend/src/pages/*.tsx

# Frontend API clients
ls frontend/src/api/*.ts

# Services (business logic)
ls backend/app/services/*.py

# Models (DB schemas)
ls backend/app/models/*.py
```

## Phase 2: Generate the 22 Build Prompts

Create the output directory:
```bash
mkdir -p ~/Scripts/Archon/agents/build-prompts
```

For **each** of the 22 agents below, produce a file at `~/Scripts/Archon/agents/build-prompts/agent-XX-build.md` that a coding agent can execute standalone.

### Agent List

| ID | Name | Priority |
|---|---|---|
| 01 | Core Backend & API Gateway | Critical |
| 02 | Visual Graph Builder | Critical |
| 03 | NL-to-Agent Wizard | High |
| 04 | Templates & Marketplace | High |
| 05 | Agent Creation Wizard | Critical |
| 06 | Executions & Tracing | Critical |
| 07 | Workflows Graph | High |
| 08 | Model Router + Vault Secrets | Critical |
| 09 | Connectors Onboarding | High |
| 10 | Lifecycle & Deployment | High |
| 11 | Cost Engine | High |
| 12 | DLP & Guardrails | Critical |
| 13 | Governance & Registry | High |
| 14 | SentinelScan | Medium |
| 15 | MCP Apps Engine | Medium |
| 16 | SSO + Tenants + Users | Critical |
| 17 | Secrets Vault | Critical |
| 18 | Audit Log | Critical |
| 19 | Settings Platform | High |
| 20 | Dashboard | High |
| 21 | Deployment Infrastructure | Medium |
| 22 | Master Validator | Critical |

### Required Structure for Each Build Prompt

Every `agent-XX-build.md` file MUST follow this exact template:

```markdown
# Agent XX — [Name] — Build Prompt

> Hand this file to a coding agent. It contains everything needed to build this component.

## Context

You are building **[component name]** for Archon, an enterprise AI orchestration platform.
Project root: `~/Scripts/Archon/`

## What Already Exists (do NOT rebuild these)

[List the specific files that already exist for this agent's domain.
Include line counts. Tell the agent what to EXTEND vs what to REPLACE.]

## What to Build

[Precise deliverables — files to create, files to modify, endpoints to add, components to wire.]

## Patterns to Follow (stolen from OSS)

[For each pattern borrowed from Dify/Flowise/Coze/Idun, describe:
- WHAT the pattern is (e.g., "Dify's model provider credential form")
- WHERE you saw it (e.g., "dify/web/app/components/header/account-setting/model-provider-page/")
- HOW to adapt it for Archon (e.g., "Store credentials in Vault instead of encrypted DB column")
- Include pseudocode, component structure, or API shape — NOT copy-pasted code]

## Backend Deliverables

[List every endpoint, model change, service method to create/modify.
Include request/response shapes. Use the API envelope format.]

## Frontend Deliverables

[List every component, page modification, API client function.
Describe the UX flow step-by-step — what the user sees and clicks.]

## Integration Points

[Which other agents' code does this touch? What contracts must be respected?
List the exact import paths and function signatures.]

## Acceptance Criteria

[Numbered list. These are pass/fail — the agent's work isn't done until ALL are met.]

## Files to Read Before Starting

- `~/Scripts/Archon/agents/AGENT_RULES.md` (mandatory coding standards)
- [1-2 other specific files relevant to THIS agent]

## Files to Create/Modify

[Explicit file path list with action: CREATE or MODIFY]

## Testing

[How to verify the work. Include specific test commands and curl examples.]

## Constraints

- Python 3.12, type hints, docstrings. Use `python3` not `python`.
- Always `PYTHONPATH=backend` for pytest.
- API envelope: `{"data": ..., "meta": {"request_id", "timestamp"}}`
- No raw JSON fields on any user-facing form.
- All credentials via SecretsManager, never in DB.
- Never use `password=value` directly — use dict unpacking.
- Do NOT read ROADMAP.md, INSTRUCTIONS.md, ARCHITECTURE.md.
- Tests must pass: `cd ~/Scripts/Archon && PYTHONPATH=backend python3 -m pytest tests/ --no-header -q`
```

### Quality Requirements for the Prompts You Generate

Each build prompt must be:

1. **Self-contained** — A coding agent with no prior context can execute it. No "refer to the main doc" — inline everything needed.
2. **Specific** — File paths, endpoint URLs, component names, model field names. No vague "implement a good UI".
3. **OSS-informed** — Every agent prompt must reference at least 2 concrete patterns from Dify or the other OSS projects, with the source file path and an explanation of how to adapt it. Don't copy code — describe the pattern.
4. **Archon-aware** — Must account for what already exists. Tell the agent what to extend vs replace. Include current line counts so the agent knows the scale.
5. **Testable** — Every prompt ends with concrete verification steps (curl commands, pytest, browser checks).
6. **Zero-JSON** — Every prompt must explicitly instruct: "No raw JSON fields on any user-facing form. Use dropdowns, wizards, visual builders, form fields."

### What NOT to Include in the Build Prompts

- Do NOT copy-paste OSS code (license violation). Describe patterns and shapes only.
- Do NOT include the full AGENT_DEFINITIONS.md — extract only what's relevant per agent.
- Do NOT add time estimates.
- Do NOT reference files that don't exist in Archon.

## Phase 3: Output Summary

After creating all 22 files, output a summary table:

```markdown
| File | Agent | Lines | OSS Patterns Referenced | Key Deliverables |
|---|---|---|---|---|
| agent-01-build.md | Core Backend | ~200 | Dify app model, Dify API structure | Expand Agent model, execution engine, health fix |
| ... | ... | ... | ... | ... |
```

And verify:
```bash
ls -la ~/Scripts/Archon/agents/build-prompts/agent-*-build.md | wc -l
# Must be 22
```

## Rules

- Work inside `~/Scripts/Archon/`. All output goes to `agents/build-prompts/`.
- Clone reference repos to `~/Scripts/*-reference/` — do NOT modify them.
- Do NOT write any Archon application code. You are writing PROMPTS ONLY.
- Do NOT read ROADMAP.md, INSTRUCTIONS.md, ARCHITECTURE.md, or other large docs in Archon.
- Use sub-agents for parallelism — e.g., one agent researches Dify while another researches Flowise.
- If a pattern doesn't exist in any OSS project (Governance, SentinelScan, MCP Apps), design it from first principles and note "Original design — no OSS reference".

## BEGIN

Start with Phase 1 (research). Read Archon's definitions, clone and study the OSS repos. Then move to Phase 2 and produce all 22 build prompt files. Finish with the Phase 3 summary.
