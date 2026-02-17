# Agent-04: Template Library & Marketplace System (Enterprise)

> **Phase**: 1 | **Dependencies**: Agent-01 (Core Backend), Agent-02 (React Flow Builder) | **Priority**: HIGH
> **The accelerator. Templates turn days of agent building into minutes. The marketplace turns individual productivity into organizational leverage.**

---

## Identity

You are Agent-04: the Template Library & Marketplace Curator. You build and maintain a rich, secure, versioned ecosystem of ready-to-use agent templates — complete with authentication-aware installation, GPG-signed publishing, GitHub synchronization, and per-tenant usage analytics.

## Mission

Build a production-grade template system that:
1. Ships with 50+ curated templates across 8+ categories for immediate time-to-value
2. Implements a marketplace with OAuth-authenticated publishing, RBAC-gated installation, and reviewer workflows
3. Signs every template with creator identity (GPG/Sigstore) and verifies signatures on install
4. Synchronizes bi-directionally with GitHub repositories via webhooks, with CI pipelines for lint, security scan, and cost estimation on every push
5. Provides per-template variable definitions including secrets references, model preferences, and connector configs with a configuration wizard on install
6. Tracks usage analytics (install count, execution count, success rate, avg cost, user ratings) with dashboards for template creators

## Requirements

### Template Data Model

```python
class Template(SQLModel, table=True):
    """A reusable agent template that can be installed, configured, and deployed."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(max_length=255, index=True)
    slug: str = Field(unique=True, index=True)
    description: str
    long_description: str | None               # Markdown, rendered in marketplace
    category: str = Field(index=True)          # Primary category
    subcategory: str | None
    tags: list[str] = Field(default_factory=list)
    difficulty: Literal["beginner", "intermediate", "advanced", "expert"]
    
    # Template content
    graph_definition: dict                     # LangGraph JSON definition
    python_source: str | None                  # Standalone Python source code
    config_schema: dict                        # JSON Schema for template variables
    default_config: dict                       # Default values for template variables
    
    # Resource requirements
    required_connectors: list[ConnectorManifest] = Field(default_factory=list)
    required_models: list[ModelManifest] = Field(default_factory=list)
    credential_manifest: list[CredentialManifest] = Field(default_factory=list)
    estimated_cost_per_run: float | None       # USD
    estimated_latency_ms: int | None
    
    # Authorship & versioning
    author_id: uuid.UUID = Field(foreign_key="users.id")
    author_tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    version: str = "1.0.0"                     # Semver
    version_history: list[TemplateVersion] = Field(default_factory=list)
    signature: str | None                      # GPG/Sigstore signature (base64)
    signature_verified: bool = False
    signing_identity: str | None               # Signer's email or key ID
    
    # Marketplace metadata
    visibility: Literal["private", "tenant", "public"] = "tenant"
    status: Literal["draft", "review", "published", "deprecated", "archived"] = "draft"
    featured: bool = False
    trending_score: float = 0.0
    
    # Media
    icon_url: str | None
    preview_images: list[str] = Field(default_factory=list)  # Screenshot URLs
    demo_video_url: str | None
    readme: str | None                         # Full README markdown
    changelog: str | None                      # Version changelog markdown
    
    # Analytics (denormalized for performance)
    install_count: int = 0
    execution_count: int = 0
    success_rate: float | None                 # 0.0-1.0
    avg_cost_per_run: float | None
    avg_rating: float | None                   # 1.0-5.0
    rating_count: int = 0
    
    # GitHub sync
    github_repo: str | None                    # "org/repo"
    github_path: str | None                    # Path within repo
    github_branch: str = "main"
    github_last_sync: datetime | None
    github_webhook_id: str | None
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime | None
    published_at: datetime | None
    deleted_at: datetime | None                # Soft delete
    
    # Tenant scoping
    tenant_id: uuid.UUID | None                # None = platform-wide template
```

**Supporting Models**
```python
class ConnectorManifest(BaseModel):
    """Declares a connector requirement for template installation."""
    connector_type: str                        # "salesforce", "slack", "s3", etc.
    required: bool = True
    operations: list[str]                      # ["read", "write", "query"]
    description: str                           # Human-readable explanation
    setup_docs_url: str | None                 # Link to connector setup guide

class CredentialManifest(BaseModel):
    """Declares a credential requirement — Vault paths, never raw keys."""
    connector_type: str
    vault_path_pattern: str                    # "archon/{tenant_id}/connectors/{connector_type}"
    required_fields: list[str]                 # ["client_id", "client_secret", "refresh_token"]
    auth_method: str                           # "oauth2", "api_key", "iam_role"
    setup_wizard_route: str                    # "/settings/connectors/{connector_type}/configure"

class ModelManifest(BaseModel):
    """Declares a model requirement for the template."""
    model_id: str                              # "gpt-4o", "claude-sonnet-4-20250514"
    purpose: str                               # "primary_reasoning", "classification"
    required: bool = True
    fallback: str | None                       # Fallback model if primary unavailable
    min_context_window: int | None             # Minimum context window needed

class TemplateVersion(SQLModel, table=True):
    """Immutable version snapshot of a template."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    template_id: uuid.UUID = Field(foreign_key="templates.id")
    version: str                               # Semver string
    graph_definition: dict                     # Snapshot of graph at this version
    python_source: str | None
    config_schema: dict
    changelog_entry: str | None                # What changed in this version
    signature: str | None                      # GPG/Sigstore signature
    signing_identity: str | None
    author_id: uuid.UUID
    created_at: datetime = Field(default_factory=datetime.utcnow)
    parent_version_id: uuid.UUID | None        # Previous version

class TemplateInstallation(SQLModel, table=True):
    """Tracks a template installation by a user/tenant."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    template_id: uuid.UUID = Field(foreign_key="templates.id")
    template_version: str                      # Version installed
    installed_by: uuid.UUID = Field(foreign_key="users.id")
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    workspace_id: uuid.UUID = Field(foreign_key="workspaces.id")
    agent_id: uuid.UUID | None = Field(foreign_key="agents.id")  # Created agent
    configuration: dict                        # User's configuration choices
    credential_status: dict                    # {connector: "configured"|"missing"}
    status: Literal["installing", "configured", "active", "failed", "uninstalled"] = "installing"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    uninstalled_at: datetime | None

class TemplateReview(SQLModel, table=True):
    """User review/rating of a template."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    template_id: uuid.UUID = Field(foreign_key="templates.id")
    reviewer_id: uuid.UUID = Field(foreign_key="users.id")
    rating: int = Field(ge=1, le=5)            # 1-5 stars
    title: str | None
    body: str | None                           # Review text (markdown)
    verified_user: bool = False                # Has actually used the template
    helpful_count: int = 0
    status: Literal["pending", "approved", "rejected", "flagged"] = "pending"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime | None

class TemplateCategory(SQLModel, table=True):
    """Template category — includes built-in and per-tenant custom categories."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str
    slug: str = Field(unique=True)
    description: str
    icon: str | None                           # Icon name or URL
    display_order: int = 0
    tenant_id: uuid.UUID | None                # None = platform-wide
    parent_id: uuid.UUID | None                # For subcategories
    template_count: int = 0                    # Denormalized count
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

### Template Authentication & Installation

**Authentication-Aware Installation**
- Templates that use connectors include a `credential_manifest` listing all required credentials
- On install, the system:
  1. Checks which credentials are already configured in the tenant's Vault
  2. Presents a status dashboard: ✅ configured / ❌ missing for each credential
  3. For missing credentials, launches the Credential Wizard (Agent-00) inline
  4. Blocks deployment until all required credentials are configured (or marked optional)
- Credential validation: verify Vault paths are accessible and credentials are not expired
- Installation flow:
  ```python
  class TemplateInstaller:
      """Handles the full template installation lifecycle."""
      
      async def install(self, template_id: uuid.UUID, user: AuthenticatedUser,
                        workspace_id: uuid.UUID, config: dict) -> TemplateInstallation:
          template = await self.get_template(template_id)
          
          # 1. RBAC check — only developers+ can install
          await self.check_permission(user, "templates:install", workspace_id)
          
          # 2. Verify template signature
          if template.signature:
              await self.verify_signature(template)
          
          # 3. Check credential requirements
          cred_status = await self.check_credentials(
              template.credential_manifest, user.tenant_id
          )
          if any(s.status == "missing" for s in cred_status if s.required):
              return TemplateInstallation(
                  status="pending_credentials",
                  credential_status=cred_status,
                  setup_urls=[s.setup_wizard_route for s in cred_status if s.status == "missing"]
              )
          
          # 4. Apply user configuration
          validated_config = self.validate_config(template.config_schema, config)
          
          # 5. Fork template → create agent
          agent = await self.create_agent_from_template(
              template, user, workspace_id, validated_config
          )
          
          # 6. Record installation
          installation = await self.record_installation(
              template, user, workspace_id, agent, validated_config, cred_status
          )
          
          # 7. Update analytics
          await self.increment_install_count(template_id)
          
          return installation
  ```

**Marketplace RBAC**
- Publishers: authenticate via OAuth, must have `templates:publish` permission
- Reviewers: require `templates:review` role (assigned by tenant_admin)
- Installers: require `templates:install` permission (developer+ role)
- Viewers: any authenticated user can browse public templates
- Template submission workflow:
  1. Author submits template → status = "review"
  2. Reviewer gets notification → reviews code, security, quality
  3. Reviewer approves/rejects with comments
  4. On approval → status = "published", visible in marketplace
  5. On rejection → author gets feedback, can resubmit

### Template Versioning & Signing

**GPG/Sigstore Signing**
- Templates are signed by their creator using GPG or Sigstore (cosign)
- Signing flow:
  1. Author creates/updates template
  2. System computes SHA-256 hash of `graph_definition + python_source + config_schema`
  3. Hash signed with author's key (GPG key from Vault or Sigstore keyless signing via OIDC)
  4. Signature stored in `TemplateVersion.signature`
- Verification on install:
  1. Recompute content hash
  2. Verify signature against author's public key (GPG keyring or Sigstore transparency log)
  3. If verification fails → installation blocked, security alert raised
  4. Verification result cached (invalidated on template update)

**Version Management**
- Semantic versioning (major.minor.patch) with automatic bumping suggestions
- Every version creates an immutable `TemplateVersion` snapshot
- Changelog: required for minor/major version bumps
- Version compatibility: templates declare minimum platform version
- Rollback: marketplace admins can revert a template to a previous version
- Deprecation: templates can be deprecated with migration path to replacement

### GitHub Synchronization

**Bi-Directional Sync**
- Export templates to GitHub:
  1. Template → GitHub repo (one repo per template or monorepo with paths)
  2. Generates: `template.json` (graph definition), `source.py`, `config.schema.json`, `README.md`
  3. Push via GitHub API with author's OAuth token
- Import from GitHub:
  1. Webhook on push to configured branch
  2. Parse template files from repo
  3. Validate structure, run security scan
  4. Update template in database (creates new version)
- Sync configuration:
  ```python
  class GitHubSyncConfig(BaseModel):
      repo: str                                # "org/repo"
      branch: str = "main"
      path: str = "/"                          # Path within repo
      direction: Literal["push", "pull", "bidirectional"] = "bidirectional"
      auto_publish: bool = False               # Auto-publish on successful sync
      webhook_secret: str                      # Stored in Vault
  ```

**Template CI Pipeline**
- On every push to a synced GitHub repo:
  1. **Lint**: validate JSON schema, check Python syntax
  2. **Security scan**: Agent-11 DLP scan for secrets, prompt injection patterns
  3. **Cost estimation**: Agent-09 estimates per-run cost
  4. **Compatibility check**: verify required connectors and models are valid
  5. Results posted as GitHub commit status checks
- CI results stored with the template version for audit

### Template Categories (8+ Built-in)

| Category | Subcategories | Example Templates |
|----------|---------------|-------------------|
| **Customer Service** | Chatbot, Ticket Routing, FAQ, Escalation | Order Status Bot, Returns Handler, Live Chat Agent |
| **Data Analysis** | Summarization, Extraction, Comparison, Reporting | CSV Analyzer, Report Generator, Data Quality Checker |
| **Code Generation** | Review, Documentation, Testing, Refactoring | PR Reviewer, API Doc Generator, Test Writer |
| **Content Creation** | Writing, Translation, Editing, SEO | Blog Post Writer, Multi-Language Translator, SEO Optimizer |
| **Research** | Literature Review, Competitive Analysis, Fact-Checking | Research Assistant, Market Analyzer, Citation Checker |
| **Operations** | Incident Response, Workflow Automation, Scheduling | Incident Triage Bot, Approval Workflow, Meeting Scheduler |
| **Security** | Threat Detection, Compliance Audit, Vulnerability Scan | Log Analyzer, Policy Checker, CVE Scanner |
| **Custom** | Per-tenant custom categories | (Tenant-defined) |

- Per-tenant custom categories: tenant admins can create categories specific to their organization
- Category management:
  ```python
  class CategoryService:
      BUILT_IN_CATEGORIES = [
          "customer_service", "data_analysis", "code_generation", "content_creation",
          "research", "operations", "security", "custom"
      ]
      
      async def create_custom_category(self, tenant_id: uuid.UUID, 
                                        name: str, description: str) -> TemplateCategory:
          """Tenant admins can create custom categories."""
          return await self.repo.create(TemplateCategory(
              name=name, slug=slugify(name), description=description,
              tenant_id=tenant_id
          ))
  ```

### Template Configuration

**Per-Template Variable Definitions**
- Templates define configurable variables via JSON Schema:
  ```json
  {
    "config_schema": {
      "type": "object",
      "properties": {
        "model": {
          "type": "string",
          "enum": ["gpt-4o", "claude-sonnet-4-20250514", "gemini-2.0-flash"],
          "default": "gpt-4o",
          "description": "Primary LLM for reasoning"
        },
        "max_retries": {
          "type": "integer",
          "minimum": 0,
          "maximum": 5,
          "default": 3,
          "description": "Max retry attempts on failure"
        },
        "salesforce_instance": {
          "type": "string",
          "description": "Salesforce instance URL",
          "x-credential-ref": "archon/{tenant_id}/connectors/salesforce"
        },
        "notification_channel": {
          "type": "string",
          "description": "Slack channel for notifications",
          "x-connector-ref": "slack"
        }
      },
      "required": ["model"]
    }
  }
  ```
- Variables with `x-credential-ref` are resolved from Vault at runtime (never stored in config)
- Variables with `x-connector-ref` are validated against configured connectors
- Configuration wizard:
  1. Parses `config_schema` → renders form fields in UI
  2. Pre-fills defaults and detects configured connectors
  3. Validates input against JSON Schema
  4. Stores validated config with the `TemplateInstallation`

### Usage Analytics

**Tracked Metrics**
```python
class TemplateAnalytics(SQLModel, table=True):
    """Per-template analytics aggregated daily."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    template_id: uuid.UUID = Field(foreign_key="templates.id")
    date: date = Field(index=True)
    
    # Installation metrics
    installs: int = 0
    uninstalls: int = 0
    active_installations: int = 0
    
    # Execution metrics
    executions: int = 0
    successful_executions: int = 0
    failed_executions: int = 0
    avg_execution_time_ms: float | None
    total_cost_usd: float = 0.0
    avg_cost_per_run_usd: float | None
    total_tokens: int = 0
    
    # Quality metrics
    avg_rating: float | None
    new_reviews: int = 0
    
    # Engagement
    views: int = 0
    unique_viewers: int = 0
    forks: int = 0
```

- Analytics dashboard for template creators:
  - Install trend over time (daily/weekly/monthly)
  - Execution success rate trend
  - Cost distribution histogram
  - User ratings breakdown (1-5 stars)
  - Geographic distribution of installs
  - Top configuration choices (which models/connectors users prefer)
- Platform-wide analytics for admins:
  - Most popular templates (by installs, executions, rating)
  - Category distribution
  - Template quality scores (composite of success rate, rating, support burden)
  - Cost impact per template (total platform spend attributed to each template)

## Output Structure

```
backend/
├── app/
│   ├── services/
│   │   └── templates/
│   │       ├── __init__.py
│   │       ├── template_service.py      # Core CRUD + search + filtering
│   │       ├── installer.py             # Template installation with credential checks
│   │       ├── marketplace.py           # Publishing, review workflow, RBAC
│   │       ├── versioning.py            # Version management + signing
│   │       ├── signing.py               # GPG/Sigstore signature creation & verification
│   │       ├── github_sync.py           # Bi-directional GitHub synchronization
│   │       ├── github_ci.py             # Template CI pipeline (lint, scan, cost)
│   │       ├── config_wizard.py         # Configuration schema parsing + validation
│   │       ├── analytics.py             # Usage analytics aggregation + queries
│   │       ├── categories.py            # Category management (built-in + custom)
│   │       ├── search.py                # Full-text + filter search (tsvector)
│   │       └── schemas.py               # Pydantic request/response models
│   ├── routers/
│   │   ├── templates.py                 # Template CRUD + marketplace endpoints
│   │   ├── template_marketplace.py      # Publishing, reviews, featured
│   │   └── template_analytics.py        # Analytics dashboard endpoints
│   ├── models/
│   │   ├── template.py                  # Template, TemplateVersion, TemplateInstallation
│   │   ├── template_review.py           # TemplateReview model
│   │   ├── template_category.py         # TemplateCategory model
│   │   └── template_analytics.py        # TemplateAnalytics model
│   └── webhooks/
│       └── github_template_webhook.py   # GitHub webhook handler for template sync
├── tests/
│   └── test_templates/
│       ├── __init__.py
│       ├── conftest.py                  # Template test fixtures + factories
│       ├── test_template_crud.py        # CRUD operations
│       ├── test_installer.py            # Installation with credential checks
│       ├── test_marketplace.py          # Publishing, review workflow
│       ├── test_signing.py              # Signature creation + verification
│       ├── test_github_sync.py          # GitHub synchronization
│       ├── test_config_wizard.py        # Configuration validation
│       ├── test_analytics.py            # Analytics aggregation
│       ├── test_search.py               # Full-text search
│       ├── test_categories.py           # Category management
│       └── test_e2e_templates.py        # End-to-end template lifecycle
└── alembic/
    └── versions/
        └── xxx_add_template_tables.py   # Migration for template tables

frontend/
└── src/
    └── components/
        └── templates/
            ├── TemplateBrowser.tsx       # Grid layout with filtering
            ├── TemplateCard.tsx          # Card component with preview
            ├── TemplateDetail.tsx        # Full template detail page
            ├── TemplatePreview.tsx       # Live preview modal
            ├── TemplateInstallWizard.tsx # Config wizard + credential setup
            ├── TemplatePublish.tsx       # Publishing form
            ├── TemplateReviews.tsx       # Ratings + review list
            ├── CategorySidebar.tsx       # Category navigation
            ├── TemplateSearch.tsx        # Search with autocomplete
            ├── FeaturedTemplates.tsx     # Featured/trending section
            ├── AnalyticsDashboard.tsx    # Creator analytics dashboard
            └── GitHubSyncConfig.tsx      # GitHub repo connection UI

data/
└── templates/                           # 50+ curated template definitions
    ├── customer_service/
    │   ├── order-status-bot.json
    │   ├── returns-handler.json
    │   ├── faq-chatbot.json
    │   ├── ticket-router.json
    │   ├── escalation-agent.json
    │   └── live-chat-agent.json
    ├── data_analysis/
    │   ├── csv-analyzer.json
    │   ├── report-generator.json
    │   ├── data-quality-checker.json
    │   ├── trend-analyzer.json
    │   ├── survey-summarizer.json
    │   └── kpi-tracker.json
    ├── code_generation/
    │   ├── pr-reviewer.json
    │   ├── api-doc-generator.json
    │   ├── test-writer.json
    │   ├── bug-triager.json
    │   ├── code-refactorer.json
    │   └── changelog-generator.json
    ├── content_creation/
    │   ├── blog-post-writer.json
    │   ├── translator.json
    │   ├── seo-optimizer.json
    │   ├── social-media-poster.json
    │   ├── newsletter-generator.json
    │   └── copy-editor.json
    ├── research/
    │   ├── research-assistant.json
    │   ├── market-analyzer.json
    │   ├── citation-checker.json
    │   ├── competitor-tracker.json
    │   ├── patent-searcher.json
    │   └── literature-reviewer.json
    ├── operations/
    │   ├── incident-triage.json
    │   ├── approval-workflow.json
    │   ├── meeting-scheduler.json
    │   ├── onboarding-assistant.json
    │   ├── sla-monitor.json
    │   └── runbook-executor.json
    ├── security/
    │   ├── log-analyzer.json
    │   ├── policy-checker.json
    │   ├── cve-scanner.json
    │   ├── access-reviewer.json
    │   ├── phishing-detector.json
    │   └── compliance-auditor.json
    └── _template_schema.json            # JSON Schema for template definition files
```

## API Endpoints (Complete)

```
# Template CRUD
GET    /api/v1/templates                        # List/search templates (paginated, filtered)
POST   /api/v1/templates                        # Create template (draft)
GET    /api/v1/templates/{id}                   # Get template details
PUT    /api/v1/templates/{id}                   # Update template
DELETE /api/v1/templates/{id}                   # Soft-delete template
GET    /api/v1/templates/{id}/graph             # Get graph definition (React Flow JSON)
GET    /api/v1/templates/{id}/source            # Get Python source code

# Search & Discovery
GET    /api/v1/templates/search                 # Full-text search with filters
GET    /api/v1/templates/featured               # Featured templates
GET    /api/v1/templates/trending               # Trending templates (by install velocity)
GET    /api/v1/templates/categories             # List all categories
GET    /api/v1/templates/categories/{slug}      # Get templates in category
POST   /api/v1/templates/categories             # Create custom category (tenant_admin)
PUT    /api/v1/templates/categories/{id}        # Update category
DELETE /api/v1/templates/categories/{id}        # Delete custom category

# Installation
POST   /api/v1/templates/{id}/install           # Install template → create agent
GET    /api/v1/templates/{id}/install/check     # Pre-install check (credentials, permissions)
GET    /api/v1/templates/installations          # List user's installations
GET    /api/v1/templates/installations/{id}     # Get installation details
DELETE /api/v1/templates/installations/{id}     # Uninstall (soft-delete agent)

# Configuration
GET    /api/v1/templates/{id}/config-schema     # Get configuration schema
POST   /api/v1/templates/{id}/config/validate   # Validate configuration against schema
GET    /api/v1/templates/{id}/credentials       # Check credential status for template

# Versioning
GET    /api/v1/templates/{id}/versions          # List all versions
GET    /api/v1/templates/{id}/versions/{ver}    # Get specific version
POST   /api/v1/templates/{id}/versions          # Create new version
GET    /api/v1/templates/{id}/versions/{v1}/diff/{v2}  # Diff two versions
POST   /api/v1/templates/{id}/versions/{ver}/rollback  # Rollback to version (admin)

# Marketplace & Publishing
POST   /api/v1/templates/{id}/submit            # Submit for review
GET    /api/v1/templates/review-queue           # Reviewer: list pending reviews
POST   /api/v1/templates/{id}/review            # Reviewer: approve/reject
POST   /api/v1/templates/{id}/publish           # Publish approved template
POST   /api/v1/templates/{id}/deprecate         # Deprecate template

# Signing
POST   /api/v1/templates/{id}/sign              # Sign template with GPG/Sigstore
GET    /api/v1/templates/{id}/verify            # Verify template signature
GET    /api/v1/templates/{id}/signature         # Get signature details

# Reviews & Ratings
GET    /api/v1/templates/{id}/reviews           # List reviews for template
POST   /api/v1/templates/{id}/reviews           # Submit review (authenticated)
PUT    /api/v1/templates/{id}/reviews/{rid}     # Update own review
DELETE /api/v1/templates/{id}/reviews/{rid}     # Delete own review
POST   /api/v1/templates/{id}/reviews/{rid}/helpful  # Mark review as helpful

# GitHub Sync
POST   /api/v1/templates/{id}/github/connect    # Connect template to GitHub repo
DELETE /api/v1/templates/{id}/github/disconnect  # Disconnect GitHub sync
POST   /api/v1/templates/{id}/github/sync       # Trigger manual sync
GET    /api/v1/templates/{id}/github/status     # Get sync status
POST   /api/v1/webhooks/github/templates        # GitHub webhook receiver

# Analytics
GET    /api/v1/templates/{id}/analytics         # Get template analytics
GET    /api/v1/templates/{id}/analytics/trends   # Get analytics trends over time
GET    /api/v1/templates/analytics/overview      # Platform-wide template analytics (admin)
GET    /api/v1/templates/analytics/top           # Top templates by metric

# Forking
POST   /api/v1/templates/{id}/fork              # Fork template to user's workspace
```

## Verify Commands

```bash
# Template models importable
cd ~/Scripts/Archon && python -c "
from backend.app.models.template import Template, TemplateVersion, TemplateInstallation
from backend.app.models.template_review import TemplateReview
from backend.app.models.template_category import TemplateCategory
from backend.app.models.template_analytics import TemplateAnalytics
print('All template models OK')
"

# Template services importable
cd ~/Scripts/Archon && python -c "
from backend.app.services.templates.template_service import TemplateService
from backend.app.services.templates.installer import TemplateInstaller
from backend.app.services.templates.marketplace import MarketplaceService
from backend.app.services.templates.signing import TemplateSigningService
from backend.app.services.templates.github_sync import GitHubSyncService
from backend.app.services.templates.analytics import TemplateAnalyticsService
print('All template services OK')
"

# Tests pass
cd ~/Scripts/Archon/backend && python -m pytest tests/test_templates/ --tb=short -q

# Template data files exist (50+ templates)
test $(find ~/Scripts/Archon/data/templates -name '*.json' -not -name '_*' 2>/dev/null | wc -l | tr -d ' ') -ge 50 && echo 'Template count OK' || echo 'FAIL: need 50+ templates'

# API routes registered
cd ~/Scripts/Archon && python -c "
from backend.app.main import app
routes = [r.path for r in app.routes]
assert '/api/v1/templates' in str(routes), f'Missing template routes'
print('Template routes OK')
"

# Template schema validates
cd ~/Scripts/Archon && python -c "
import json, jsonschema
schema = json.load(open('data/templates/_template_schema.json'))
sample = json.load(open('data/templates/customer_service/order-status-bot.json'))
jsonschema.validate(sample, schema)
print('Template schema validation OK')
"

# No hardcoded secrets in template definitions
cd ~/Scripts/Archon && ! grep -rn 'api_key.*:.*\"sk-' --include='*.json' data/templates/ || echo 'FAIL: hardcoded secrets found'

# GitHub webhook handler importable
cd ~/Scripts/Archon && python -c "
from backend.app.webhooks.github_template_webhook import handle_template_push
print('GitHub webhook OK')
"
```

## Learnings Protocol

Before starting, read `.sdd/learnings/*.md` for known pitfalls from previous sessions.
After completing work, report any pitfalls or patterns discovered so the orchestrator can capture them via `node ~/Projects/copilot-sdd/dist/cli.js learn`.

## Acceptance Criteria

- [ ] 50+ templates across 8+ categories available at launch, each with valid JSON Schema
- [ ] Template search returns relevant results within 200ms (full-text + category + tag filters)
- [ ] One-click install: fork template → credential check → configure → deploy in <10 seconds
- [ ] Installation blocks if required credentials are missing, with links to Credential Wizard (Agent-00)
- [ ] Template signature verified on install — tampered templates are rejected with security alert
- [ ] Version history: each update creates immutable snapshot with changelog, diff between any two versions works
- [ ] Marketplace RBAC: only developers+ can install, only reviewers can approve, only publishers can publish
- [ ] Review workflow: submit → review → approve/reject with comments
- [ ] GitHub sync: push to repo → webhook → lint + security scan + cost estimate → update template in database
- [ ] Bi-directional sync: template edits in UI sync to GitHub and vice versa
- [ ] Configuration wizard renders dynamic form from JSON Schema, validates input, resolves Vault credential refs
- [ ] Usage analytics: install count, execution count, success rate, avg cost, user ratings all tracked and queryable
- [ ] Analytics dashboard loads for template creators with trend charts within 500ms
- [ ] Per-tenant custom categories can be created and templates assigned to them
- [ ] Template forking preserves original while allowing full customization in user's workspace
- [ ] Zero plaintext secrets in template definitions, configurations, or API responses
