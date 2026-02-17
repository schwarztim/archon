# Agent 04 — Templates & Marketplace — Build Prompt

> Hand this file to a coding agent. It contains everything needed to build this component.

## Context

You are building **Templates & Marketplace** for Archon — a gallery of pre-built agent templates with one-click instantiation and a marketplace for sharing/installing community agents.
Project root: `~/Scripts/Archon/`

## What Already Exists (do NOT rebuild these)

- `frontend/src/pages/TemplatesPage.tsx` (177 lines) — Has form with Name, raw JSON Definition, Category, Tags. REPLACE the form UX but keep the page structure.
- `frontend/src/pages/MarketplacePage.tsx` (232 lines) — Has publish form. No listings, no catalog. REDESIGN with catalog.
- `frontend/src/api/templates.ts` (85 lines) — API client for templates. EXTEND.
- `frontend/src/api/marketplace.ts` (68 lines) — API client for marketplace. EXTEND.
- `frontend/src/components/templates/TemplateGallery.tsx` (163 lines) — Gallery component EXISTS. EXTEND.
- `frontend/src/components/templates/TemplateCard.tsx` (92 lines) — Card component EXISTS. EXTEND.
- `backend/app/routes/templates.py` (367 lines) — Template CRUD. EXTEND with instantiate endpoint.
- `backend/app/routes/marketplace.py` (431 lines) — Marketplace routes. EXTEND with catalog/install.
- `backend/app/services/template_service.py` (584 lines) — Template service. EXTEND.
- `backend/app/services/marketplace_service.py` (517 lines) — Marketplace service. EXTEND.
- `backend/app/models/template.py` (231 lines) — Template model. KEEP.
- `backend/app/models/marketplace.py` (227 lines) — Marketplace model. KEEP.

## What to Build

### 1. Templates Page Redesign
Replace the raw JSON Definition form with:
- **Gallery View**: Grid of template cards (TemplateCard component). Each card shows: icon (based on category), name, category badge, truncated description, "Use Template" button.
- **Search & Filter**: Search bar + category filter tabs (All, Customer Support, Data Analysis, Content Generation, Code Assistant, Research, DevOps, Sales, HR, Finance, Custom)
- **Template Detail Modal**: Click card → modal with: full description, React Flow graph preview (read-only), required connectors listed, estimated cost per run, "Instantiate" button.
- **Create Template Wizard**: "Create Template" button → 3-step wizard:
  1. Name, Description, Category (dropdown), Tags (chips), Icon
  2. Build graph in embedded mini React Flow canvas OR select "Import from existing agent" (agent dropdown)
  3. Set default config values, preview, "Publish Template"

### 2. Marketplace Page Redesign
- **Browse Catalog**: Grid of marketplace package cards. Search bar + category filters + sort (Popular, Recent, Rating).
- **Package Card**: Publisher name, package name, version, download count, rating (1-5 stars), verified badge, "Install" button.
- **Install Flow**: "Install" → confirmation modal listing permissions required → creates agent from template in user's workspace.
- **Publish Flow**: "Publish to Marketplace" button → 4-step wizard:
  1. Select agent to publish
  2. Add metadata: version, changelog, screenshots
  3. Set license (MIT, Apache 2.0, Commercial, Custom)
  4. Submit for review → shows "Pending Review" status

### 3. Seed Templates
Create a backend migration/seed script that inserts 20+ starter templates:
- Customer Support Bot, Sales Qualifier, HR FAQ Bot, Code Reviewer, Data Analyzer, Content Writer, Research Assistant, DevOps Alerter, Slack Bot, Email Responder, Document Summarizer, Meeting Notes, Translation Agent, Sentiment Analyzer, Lead Scorer, Onboarding Guide, Bug Triager, Report Generator, Knowledge Base Q&A, Compliance Checker

### 4. Backend: Instantiate Endpoint
`POST /api/v1/templates/{id}/instantiate`:
- Accepts optional overrides: `{"name": "My Bot", "config_overrides": {...}}`
- Creates a new Agent from the template definition
- Increments template `usage_count`
- Returns the created agent

## Patterns to Follow (from OSS)

### Pattern 1: Dify Explore Page (from dify/web/app/components/explore/)
Dify's explore page shows app templates in a card grid with category tabs. Each card has an icon, name, description, and "Add to Workspace" button. Clicking opens a detail view with full description and a "Create" action. Archon adaptation: Same card grid pattern with categories. Add React Flow graph preview in detail view (Dify doesn't have this).

### Pattern 2: Dify App DSL Service (from dify/api/services/app_dsl_service.py)
Dify exports apps as YAML DSL files that can be imported. The service handles serialization, validation, and import/export. Archon adaptation: Templates store the agent definition (including graph_definition) as JSON. Instantiation copies this definition into a new Agent record, resetting IDs and applying user overrides.

### Pattern 3: Flowise Marketplace (from flowise)
Flowise has a marketplace tab showing community chatflows with install buttons. Each entry has a readme, screenshots, and node list. Archon adaptation: Similar catalog with richer metadata (ratings, verified badges, license).

## Backend Deliverables

| Endpoint | Method | What It Does |
|---|---|---|
| `POST /api/v1/templates/{id}/instantiate` | POST | Create agent from template |
| `GET /api/v1/templates/` | GET | Enhanced: add search, category filter |
| `GET /api/v1/marketplace/catalog` | GET | Public listings with search/sort |
| `POST /api/v1/marketplace/{id}/install` | POST | Install package into workspace |

## Frontend Deliverables

| Component | Action | Description |
|---|---|---|
| `pages/TemplatesPage.tsx` | MODIFY | Gallery with search, categories, detail modal |
| `pages/MarketplacePage.tsx` | MODIFY | Catalog with search, install flow |
| `components/templates/TemplateGallery.tsx` | MODIFY | Grid layout with filtering |
| `components/templates/TemplateCard.tsx` | MODIFY | Rich card with icon, badge, actions |
| `components/templates/TemplateDetail.tsx` | CREATE | Detail modal with graph preview |
| `components/templates/CreateTemplateWizard.tsx` | CREATE | 3-step template creation |
| `components/marketplace/CatalogGrid.tsx` | CREATE | Marketplace catalog grid |
| `components/marketplace/PackageCard.tsx` | CREATE | Marketplace package card |
| `components/marketplace/InstallDialog.tsx` | CREATE | Install confirmation dialog |
| `api/templates.ts` | MODIFY | Add instantiate, search endpoints |
| `api/marketplace.ts` | MODIFY | Add catalog, install endpoints |

## Integration Points

- **Agent 01 (Backend)**: Instantiation creates Agent via standard CRUD
- **Agent 02 (Builder)**: Template graph preview uses React Flow components (import from canvas/)
- **Agent 03 (NL Wizard)**: Wizard Step 2 suggests matching templates
- **Agent 13 (Governance)**: Published marketplace items go through approval workflow

## Acceptance Criteria

1. Templates page shows gallery of cards with icons, not a raw JSON form
2. Search bar filters templates by name/description
3. Category tabs filter templates
4. Click template card → detail modal with full description + graph preview
5. "Use Template" creates a working agent in one click
6. Template creation uses a 3-step wizard, not raw JSON textarea
7. Marketplace page shows browseable catalog with search/sort
8. "Install" from marketplace creates agent in user's workspace
9. 20+ seed templates available on fresh install
10. Zero raw JSON visible on any template form

## Files to Read Before Starting

- `~/Scripts/Archon/agents/AGENT_RULES.md` (mandatory coding standards)
- `~/Scripts/Archon/frontend/src/components/templates/TemplateGallery.tsx` (existing gallery)
- `~/Scripts/Archon/backend/app/routes/templates.py` (existing routes)

## Files to Create/Modify

| Path | Action |
|---|---|
| `frontend/src/pages/TemplatesPage.tsx` | MODIFY |
| `frontend/src/pages/MarketplacePage.tsx` | MODIFY |
| `frontend/src/components/templates/TemplateGallery.tsx` | MODIFY |
| `frontend/src/components/templates/TemplateCard.tsx` | MODIFY |
| `frontend/src/components/templates/TemplateDetail.tsx` | CREATE |
| `frontend/src/components/templates/CreateTemplateWizard.tsx` | CREATE |
| `frontend/src/components/marketplace/CatalogGrid.tsx` | CREATE |
| `frontend/src/components/marketplace/PackageCard.tsx` | CREATE |
| `frontend/src/components/marketplace/InstallDialog.tsx` | CREATE |
| `frontend/src/api/templates.ts` | MODIFY |
| `frontend/src/api/marketplace.ts` | MODIFY |
| `backend/app/routes/templates.py` | MODIFY |
| `backend/app/routes/marketplace.py` | MODIFY |
| `backend/scripts/seed_templates.py` | CREATE |

## Testing

```bash
cd ~/Scripts/Archon && PYTHONPATH=backend python3 -m pytest tests/ --no-header -q
cd ~/Scripts/Archon && docker compose build frontend
# Open http://localhost:3000/templates
# 1. Verify gallery shows template cards (not a JSON form)
# 2. Search for "customer" → verify filtered results
# 3. Click a template → verify detail modal with graph preview
# 4. Click "Use Template" → verify agent created
# 5. Go to /agents → verify new agent appears
curl http://localhost:8000/api/v1/templates/ -H "Authorization: Bearer $TOKEN"
curl -X POST http://localhost:8000/api/v1/templates/{id}/instantiate -H "Authorization: Bearer $TOKEN" -d '{"name":"My Bot"}'
```

## Constraints

- Python 3.12, type hints, docstrings. Use `python3` not `python`.
- Always `PYTHONPATH=backend` for pytest.
- API envelope: `{"data": ..., "meta": {"request_id", "timestamp"}}`
- No raw JSON fields on any user-facing form.
- All credentials via SecretsManager, never in DB.
- Never use `password=value` directly — use dict unpacking.
- Do NOT read ROADMAP.md, INSTRUCTIONS.md, ARCHITECTURE.md.
- Tests must pass: `cd ~/Scripts/Archon && PYTHONPATH=backend python3 -m pytest tests/ --no-header -q`
