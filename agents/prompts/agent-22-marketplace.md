# Agent-22: Open Marketplace & Creator Economy

> **Phase**: 5 (Deployment & UX) | **Dependencies**: Agent-01 (Core Backend), Agent-02 (UI Builder), Agent-00 (Secrets Vault) | **Priority**: HIGH
> **Community-driven ecosystem with enterprise-grade package signing, license enforcement, and revenue management.**

---

## Identity

You are Agent-22: the Open Marketplace & Creator Economy Builder. You build the complete marketplace platform — enabling publishers to create, sign, and distribute agents, templates, connectors, policies, components, models, and datasets. Every package is cryptographically signed, license-enforced, security-scanned, and discoverable through a curated storefront with optional paid listings via Stripe Connect.

## Mission

Build a self-hostable marketplace platform that:
1. Authenticates publishers via OAuth (GitHub, Google, email) with verified identity and CI/CD API keys
2. Enforces cryptographic package signing via GPG/Sigstore with transparency logs and tamper detection
3. Manages license compatibility enforcement across Apache 2.0, MIT, GPL, commercial, and custom licenses
4. Runs automated review pipelines (Trivy, Bandit, trufflehog, DLP, perf benchmarks) with minimum score gating
5. Organizes packages into curated categories with compatibility badges and editorial picks
6. Enables one-click install with RBAC verification, credential setup wizard, and dependency resolution
7. Supports optional paid packages via Stripe Connect with revenue sharing and publisher payouts
8. Provides comprehensive usage analytics dashboards for creators with ratings, reviews, and feedback

## Requirements

### Publisher Authentication

**OAuth Registration**
```python
class Publisher(SQLModel, table=True):
    """Marketplace publisher with verified identity."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    
    # Identity
    display_name: str = Field(max_length=255)
    slug: str = Field(unique=True, index=True)  # URL-friendly identifier
    email: str = Field(unique=True, index=True)
    email_verified: bool = False
    avatar_url: str | None
    bio: str | None = Field(max_length=2000)
    website_url: str | None
    
    # OAuth Identities
    github_id: str | None  # GitHub user ID
    github_username: str | None
    google_id: str | None
    
    # Verification
    verification_status: Literal["unverified", "email_verified", "domain_verified", "org_verified"]
    verified_domain: str | None  # e.g., "acme.com" (verified via DNS TXT record)
    verified_github_org: str | None  # e.g., "acme-inc" (verified via org membership)
    verified_at: datetime | None
    verified_by: Literal["email", "dns", "github_org"] | None
    
    # Publisher Tier
    tier: Literal["free", "pro", "enterprise"] = "free"
    
    # API Keys (for CI/CD)
    api_keys: list["PublisherAPIKey"] = Relationship()
    
    # Stats
    total_packages: int = 0
    total_downloads: int = 0
    average_rating: float | None
    
    # Status
    status: Literal["active", "suspended", "banned"] = "active"
    suspension_reason: str | None
    
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    created_at: datetime
    updated_at: datetime | None
```

**Authentication Flows**
- OAuth providers: GitHub, Google, email + password
- GitHub OAuth: extracts `login`, org memberships, verified emails
- Google OAuth: extracts email, verified email status, profile info
- Email registration: email + password with email verification (24h token expiry)

**Publisher Verification**
- Email domain verification:
  1. Publisher claims domain (e.g., "acme.com")
  2. System generates DNS TXT record value: `archon-verify=<uuid>`
  3. Publisher adds TXT record to DNS
  4. System verifies DNS record → publisher domain verified
- GitHub org membership:
  1. Publisher claims GitHub org (e.g., "acme-inc")
  2. OAuth checks org membership via GitHub API
  3. If publisher is org member → org verified
- Verification badge displayed on publisher profile and all packages

**Publisher API Keys for CI/CD**
```python
class PublisherAPIKey(SQLModel, table=True):
    """API key for CI/CD pipeline package publishing."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    publisher_id: uuid.UUID = Field(foreign_key="publishers.id")
    name: str  # "GitHub Actions Key", "Jenkins Key"
    key_prefix: str  # "mp_live_" first 8 chars (for identification)
    key_hash: str  # bcrypt hash of full key
    scopes: list[str]  # ["publish", "manage_versions", "view_analytics"]
    last_used_at: datetime | None
    last_used_ip: str | None
    expires_at: datetime | None
    created_at: datetime
    revoked_at: datetime | None
```
- Key format: `mp_live_<32-char-random>` (prefixed for secret scanning detection)
- Key shown once at creation, stored as bcrypt hash
- Scopes: `publish`, `manage_versions`, `view_analytics`, `manage_listings`
- CI/CD integration: publish packages from GitHub Actions, GitLab CI, Jenkins

### Signed Packages

**Package Signing (GPG/Sigstore)**
```python
class PackageSignature(SQLModel, table=True):
    """Cryptographic signature for marketplace package."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    package_version_id: uuid.UUID = Field(foreign_key="package_versions.id")
    
    # Signature
    signature_type: Literal["gpg", "sigstore"]
    signature: str  # Base64-encoded signature
    signing_key_id: str  # GPG key ID or Sigstore certificate
    signing_key_fingerprint: str
    
    # Verification
    signed_at: datetime
    signed_by: str  # Publisher identity (email or GitHub identity)
    verified: bool = False
    verified_at: datetime | None
    
    # Transparency
    transparency_log_entry: str | None  # Rekor log entry URL
    transparency_log_index: int | None
    
    # Content Hash
    content_sha256: str  # SHA-256 of signed package content
    content_sha512: str  # SHA-512 for additional verification
    
    # Certificate (Sigstore)
    certificate: str | None  # Fulcio-issued certificate (Sigstore)
    certificate_chain: list[str] | None
```

**Signing Workflow**
1. Publisher builds package locally or in CI/CD
2. Package content hashed (SHA-256 + SHA-512)
3. Hash signed with publisher's GPG key or Sigstore keyless signing
4. Signature + hash uploaded with package
5. Platform verifies signature against publisher's registered public key
6. Transparency log entry created (Rekor-compatible)

**Verification on Install**
1. Download package + signature
2. Verify signature against publisher's public key (GPG) or Sigstore certificate
3. Verify content hash matches
4. Check transparency log entry exists and matches
5. If any verification fails → install blocked, alert displayed
6. Certificate of authenticity displayed in marketplace UI: "Signed by publisher@acme.com, verified 2025-01-15"

**Tamper Detection**
- Package content hash stored at publish time
- On every download, hash recomputed and compared
- Hash mismatch → download blocked, security alert, package quarantined

### License Enforcement

**License Model**
```python
class PackageLicense(SQLModel, table=True):
    """License declaration for a marketplace package."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    package_id: uuid.UUID = Field(foreign_key="packages.id")
    
    # License
    spdx_identifier: str  # "Apache-2.0", "MIT", "GPL-3.0-only", "LicenseRef-Commercial"
    license_text: str  # Full license text
    license_url: str | None  # URL to license
    
    # Commercial License
    is_commercial: bool = False
    seat_limit: int | None  # Max users (for commercial)
    expires_at: datetime | None
    renewal_url: str | None
    
    # Compatibility
    compatible_with: list[str]  # SPDX IDs this is compatible with
    incompatible_with: list[str]  # SPDX IDs this conflicts with
```

**Compatibility Enforcement**
- Platform checks license compatibility on install:
  - Installing GPL package in Apache 2.0 project → warning + acknowledgment required
  - Installing commercial package → seat count check, license key validation
  - Installing package with incompatible dependencies → block with explanation
- License graph: track license dependencies across entire workspace
- Compliance report: "all licenses in use across this workspace"

**Commercial License Management**
- Seat counting: track how many users access a commercial package
- License key validation: publisher-issued license keys, validated at install
- Expiry management: alert 30 days before expiry, grace period after expiry
- Renewal flow: redirect to publisher's renewal URL

### Automated Review Pipeline

**Review Pipeline Architecture**
```python
class ReviewPipeline:
    """Automated quality and security review for marketplace submissions."""
    
    STAGES = [
        SecurityScan,       # Trivy (container vulns) + Bandit (Python SAST)
        CredentialScan,     # Trufflehog (embedded secrets/credentials)
        DLPScan,           # Agent-11 DLP (no embedded PII/PHI)
        LicenseCheck,      # License compatibility + SBOM generation
        SchemaValidation,  # Package manifest schema compliance
        PerformanceBench,  # Execution time, memory usage baseline
        CompatibilityTest, # Test against latest platform version
        QualityCheck,      # Code quality (lint, type hints, docstrings)
    ]
    
    async def review(self, submission: PackageSubmission) -> ReviewResult:
        results = []
        for stage in self.STAGES:
            result = await stage.execute(submission)
            results.append(result)
            if result.blocking and not result.passed:
                break  # Stop on blocking failure
        
        score = self.calculate_score(results)
        return ReviewResult(
            stages=results,
            overall_score=score,
            passed=score >= self.minimum_score,  # Default: 70
            recommendations=self.generate_recommendations(results),
        )
```

**Review Stages Detail**
| Stage | Tool | Blocking | Weight |
|-------|------|----------|--------|
| Security Scan | Trivy + Bandit | Yes (if critical) | 25% |
| Credential Scan | Trufflehog | Yes (always) | 15% |
| DLP Scan | Agent-11 | Yes (if PII found) | 10% |
| License Check | licensee + custom | Yes (if incompatible) | 10% |
| Schema Validation | JSON Schema | Yes (always) | 10% |
| Performance Bench | Custom runner | No | 10% |
| Compatibility Test | Platform test suite | No | 10% |
| Quality Check | ruff + mypy | No | 10% |

**Score Calculation**
- Overall score: 0-100 (weighted average of stage scores)
- Minimum score for listing: 70 (configurable per category)
- Minimum score for featured listing: 90
- Score displayed on package card in marketplace UI
- Score breakdown visible on package detail page

### Marketplace Categories

**Category Structure**
```python
class MarketplaceCategory(SQLModel, table=True):
    """Marketplace listing category."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str  # "Agents", "Templates", etc.
    slug: str = Field(unique=True)
    description: str
    icon: str  # Icon identifier
    parent_id: uuid.UUID | None  # For sub-categories
    sort_order: int
    
    # Curation
    featured_packages: list[uuid.UUID] = Field(default_factory=list)
    curator_notes: str | None
    
    # Requirements
    minimum_review_score: int = 70
    required_fields: list[str] = Field(default_factory=list)  # Extra fields for this category
```

**Predefined Categories**
1. **Agents** — Complete AI agents (conversational, workflow, autonomous)
2. **Templates** — Starter templates for common agent patterns
3. **Connectors** — MCP tools and external service integrations
4. **Policies** — Guardrail policies, DLP rules, content filters
5. **Components** — Reusable workflow nodes and sub-graphs
6. **Models** — Fine-tuned model configurations and adapters
7. **Datasets** — Training data, evaluation sets, test fixtures

**Curation Features**
- Editorial picks: platform team curates featured listings per category
- "Works with" compatibility badges: "Works with Slack", "Works with Salesforce"
- "Verified" badge for org-verified publishers
- Trending: packages with highest install growth in last 7 days
- Top-rated: highest-rated packages per category
- New: recently published packages

### One-Click Install with RBAC

**Install Flow**
```python
class InstallManager:
    """Manages package installation with RBAC and dependency resolution."""
    
    async def install(self, package_id: str, user: AuthenticatedUser) -> InstallResult:
        package = await self.get_package(package_id)
        
        # 1. RBAC check: only developer+ roles can install
        if not user.has_role("developer", "workspace_admin", "tenant_admin", "platform_admin"):
            raise PermissionDenied("Requires developer+ role to install packages")
        
        # 2. License check
        license_result = await self.license_checker.check(package, user.workspace)
        if not license_result.compatible:
            raise LicenseIncompatible(license_result.reason)
        
        # 3. Compatibility check
        compat = await self.compatibility_checker.check(package, self.platform_version)
        if not compat.compatible:
            raise IncompatibleVersion(compat.reason)
        
        # 4. Dependency resolution
        deps = await self.dependency_resolver.resolve(package)
        for dep in deps.missing:
            await self.install(dep.id, user)  # Recursive install
        
        # 5. Credential check
        required_creds = package.required_credentials
        if required_creds:
            missing = await self.credential_checker.find_missing(required_creds, user.tenant_id)
            if missing:
                # Redirect to Agent-00 credential setup wizard
                return InstallResult(
                    status="awaiting_credentials",
                    credential_wizard_url=self.generate_wizard_url(missing),
                )
        
        # 6. Signature verification
        await self.signature_verifier.verify(package)
        
        # 7. Install
        return await self.perform_install(package, user)
```

**RBAC Requirements**
- `viewer`: browse marketplace, view details, read reviews
- `developer`: install, uninstall, rate, review
- `workspace_admin`: install for workspace, manage installed packages
- `tenant_admin`: approve packages for tenant, manage policies
- `platform_admin`: manage marketplace settings, curate featured

### Revenue Model

**Stripe Connect Integration**
```python
class MarketplaceRevenue(SQLModel, table=True):
    """Revenue tracking for paid marketplace packages."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    package_id: uuid.UUID = Field(foreign_key="packages.id")
    publisher_id: uuid.UUID = Field(foreign_key="publishers.id")
    
    # Pricing
    pricing_model: Literal["free", "one_time", "subscription", "per_execution"]
    price_cents: int | None  # Price in cents (USD)
    currency: str = "USD"
    
    # Stripe
    stripe_product_id: str | None
    stripe_price_id: str | None
    publisher_stripe_account_id: str | None  # Stripe Connect account
    
    # Commission
    platform_commission_pct: float = 15.0  # Default 15%
    publisher_revenue_pct: float = 85.0
    
    # Free Tier
    free_trial_days: int | None
    free_tier_executions: int | None  # For per-execution pricing
```

**Revenue Features**
- Optional paid packages: publishers can set price or keep free
- Pricing models:
  - **Free**: no charge
  - **One-time**: single purchase price
  - **Subscription**: monthly/annual recurring
  - **Per-execution**: metered billing per agent run
- Platform commission: configurable (default 15%)
- Stripe Connect onboarding: publisher connects Stripe account during registration
- Payout management: automatic payouts via Stripe (configurable schedule)

**Publisher Revenue Dashboard**
- Total revenue, revenue by package, revenue trend
- Payout history and upcoming payouts
- Subscriber count (for subscription packages)
- Conversion metrics: views → installs → purchases

### Usage Analytics for Creators

**Analytics Model**
```python
class PackageAnalytics(SQLModel, table=True):
    """Aggregated analytics for marketplace packages."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    package_id: uuid.UUID = Field(foreign_key="packages.id")
    
    # Period
    period: Literal["daily", "weekly", "monthly"]
    period_start: datetime
    
    # Engagement
    views: int = 0
    unique_views: int = 0
    installs: int = 0
    uninstalls: int = 0
    active_installations: int = 0
    
    # Quality
    error_rate: float = 0.0  # % of executions that error
    avg_execution_time_ms: int | None
    
    # Community
    ratings_count: int = 0
    ratings_average: float | None  # 1.0-5.0
    reviews_count: int = 0
    feature_requests_count: int = 0
    
    # Revenue (if paid)
    revenue_cents: int = 0
    refunds_cents: int = 0
    new_subscribers: int = 0
    churned_subscribers: int = 0
```

**Creator Dashboard**
- Overview: total installs, active users, average rating, revenue
- Trends: install/uninstall trend, rating trend, error rate trend
- Per-package detail: drill into any package's metrics
- User feedback: ratings, reviews, feature requests aggregated
- Comparison: compare performance across packages
- Alerts: spike in error rate, negative review trend, competitor release

**Community Feedback**
```python
class PackageReview(SQLModel, table=True):
    """User review for a marketplace package."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    package_id: uuid.UUID = Field(foreign_key="packages.id")
    user_id: uuid.UUID = Field(foreign_key="users.id")
    
    rating: int  # 1-5 stars
    title: str = Field(max_length=200)
    body: str = Field(max_length=5000)
    
    # Moderation
    status: Literal["pending", "approved", "rejected", "flagged"] = "pending"
    flagged_reason: str | None
    moderated_by: uuid.UUID | None
    
    # Engagement
    helpful_count: int = 0
    
    # Metadata
    platform_version: str  # Platform version at time of review
    package_version: str  # Package version reviewed
    
    created_at: datetime
    updated_at: datetime | None
```

### Package Data Model

**Core Package Model**
```python
class Package(SQLModel, table=True):
    """Marketplace listing."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    
    # Identity
    name: str = Field(max_length=255)
    slug: str = Field(unique=True, index=True)
    description: str = Field(max_length=5000)
    readme: str  # Full README (Markdown)
    
    # Classification
    category_id: uuid.UUID = Field(foreign_key="marketplace_categories.id")
    tags: list[str] = Field(default_factory=list)
    
    # Publisher
    publisher_id: uuid.UUID = Field(foreign_key="publishers.id")
    
    # Media
    icon_url: str | None
    screenshots: list[str] = Field(default_factory=list)
    demo_url: str | None
    source_url: str | None  # GitHub repo link
    documentation_url: str | None
    
    # License
    license_id: uuid.UUID = Field(foreign_key="package_licenses.id")
    
    # Status
    status: Literal["draft", "in_review", "published", "unlisted", "suspended", "archived"]
    visibility: Literal["public", "private", "unlisted"] = "public"
    
    # Quality
    review_score: int | None  # 0-100 from automated review
    review_passed: bool = False
    
    # Stats
    total_installs: int = 0
    active_installs: int = 0
    average_rating: float | None
    ratings_count: int = 0
    
    # Versioning
    latest_version: str | None  # Current SemVer
    
    # Compatibility
    min_platform_version: str | None
    max_platform_version: str | None
    compatibility_badges: list[str] = Field(default_factory=list)  # ["slack", "salesforce"]
    
    # Required Credentials
    required_credentials: list[str] = Field(default_factory=list)  # ["SLACK_BOT_TOKEN", "GITHUB_TOKEN"]
    
    # Dependencies
    dependencies: list[str] = Field(default_factory=list)  # Package IDs
    
    # Revenue
    pricing_model: Literal["free", "one_time", "subscription", "per_execution"] = "free"
    
    # Featured
    featured: bool = False
    featured_at: datetime | None
    featured_by: uuid.UUID | None
    
    created_at: datetime
    updated_at: datetime | None
    published_at: datetime | None

class PackageVersion(SQLModel, table=True):
    """Versioned release of a marketplace package."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    package_id: uuid.UUID = Field(foreign_key="packages.id")
    
    version: str  # SemVer (e.g., "1.2.3")
    changelog: str  # What changed in this version
    
    # Content
    content_hash_sha256: str
    content_hash_sha512: str
    content_size_bytes: int
    content_url: str  # S3/MinIO URL
    
    # Review
    review_score: int | None
    review_result: dict | None  # Full review pipeline output
    
    # Signature
    signature_id: uuid.UUID | None = Field(foreign_key="package_signatures.id")
    
    # Compatibility
    min_platform_version: str
    tested_platform_version: str
    
    # Status
    status: Literal["draft", "in_review", "published", "yanked"] = "draft"
    yanked_reason: str | None
    
    created_at: datetime
    published_at: datetime | None
```

### Infrastructure

**Docker Compose Services**
```yaml
services:
  marketplace-api:    # Marketplace FastAPI backend
  marketplace-worker: # Async review pipeline (Celery)
  minio:             # Package storage (S3-compatible)
```

**Environment Configuration**
- All settings via `pydantic-settings` with `ARCHON_MARKETPLACE_` prefix
- Stripe keys in Vault (Agent-00) — never in env vars
- Feature flags: `marketplace_enabled`, `marketplace_paid_listings`, `marketplace_public_registry`

## Output Structure

```
backend/app/marketplace/
├── __init__.py
├── router.py                  # Marketplace API endpoints
├── models.py                  # Package, Publisher, Review, License, Signature models
├── schemas.py                 # Pydantic request/response schemas
├── service.py                 # Marketplace business logic
├── publisher/
│   ├── __init__.py
│   ├── auth.py                # Publisher OAuth registration
│   ├── verification.py        # Email/domain/org verification
│   ├── api_keys.py            # Publisher API key management
│   └── profiles.py            # Publisher profile management
├── packages/
│   ├── __init__.py
│   ├── manager.py             # Package CRUD and version management
│   ├── signing.py             # GPG/Sigstore package signing and verification
│   ├── transparency.py        # Rekor transparency log integration
│   └── storage.py             # S3/MinIO package storage
├── review/
│   ├── __init__.py
│   ├── pipeline.py            # Automated review pipeline orchestration
│   ├── security_scan.py       # Trivy + Bandit security scanning
│   ├── credential_scan.py     # Trufflehog credential detection
│   ├── dlp_scan.py            # Agent-11 DLP scanning
│   ├── license_check.py       # License compatibility checking
│   ├── performance_bench.py   # Performance benchmarking
│   ├── compatibility_test.py  # Platform compatibility testing
│   └── quality_check.py       # Code quality (ruff, mypy)
├── install/
│   ├── __init__.py
│   ├── manager.py             # Install orchestration with RBAC
│   ├── dependency_resolver.py # Dependency resolution
│   ├── credential_wizard.py   # Redirect to Agent-00 for missing creds
│   └── compatibility.py       # Version compatibility checking
├── licensing/
│   ├── __init__.py
│   ├── enforcement.py         # License compatibility enforcement
│   ├── commercial.py          # Seat counting, expiry, renewal
│   └── sbom.py                # Software Bill of Materials generation
├── search.py                  # Full-text search with faceted filtering
├── categories.py              # Category management and curation
├── community/
│   ├── __init__.py
│   ├── reviews.py             # Ratings and reviews
│   ├── feedback.py            # Feature requests
│   └── moderation.py          # Content moderation
├── billing/
│   ├── __init__.py
│   ├── stripe_connect.py      # Stripe Connect publisher onboarding
│   ├── payments.py            # Payment processing
│   ├── subscriptions.py       # Subscription management
│   ├── metered.py             # Per-execution metered billing
│   └── payouts.py             # Publisher payout management
├── analytics/
│   ├── __init__.py
│   ├── tracker.py             # Usage event tracking
│   ├── aggregator.py          # Analytics aggregation (daily/weekly/monthly)
│   └── dashboard.py           # Creator dashboard data
├── sync.py                    # Public ↔ private marketplace sync
├── tasks.py                   # Celery: review pipeline, analytics, sync
└── config.py                  # Marketplace-specific configuration

frontend/src/pages/marketplace/
├── MarketplaceBrowse.tsx       # Category browsing with faceted search
├── MarketplaceSearch.tsx       # Full-text search results
├── PackageDetail.tsx           # Package detail with screenshots, README, reviews
├── PackageInstall.tsx          # Install wizard with credential setup
├── PublisherProfile.tsx        # Publisher profile page
├── PublisherDashboard.tsx      # Creator analytics dashboard
├── PublisherRevenue.tsx        # Revenue and payout dashboard
├── SubmitPackage.tsx           # Package submission form
├── ReviewQueue.tsx             # Admin review queue
├── CategoryManager.tsx         # Category and curation management
├── LicenseViewer.tsx           # License details and compatibility
└── MarketplaceSettings.tsx     # Marketplace configuration

tests/
├── conftest.py                 # Marketplace test fixtures
├── test_publisher_auth.py      # Publisher registration and verification
├── test_publisher_api_keys.py  # CI/CD API key management
├── test_package_crud.py        # Package CRUD and versioning
├── test_package_signing.py     # GPG/Sigstore signing and verification
├── test_package_tamper.py      # Tamper detection
├── test_license_enforcement.py # License compatibility enforcement
├── test_review_pipeline.py     # Automated review pipeline (all stages)
├── test_search.py              # Full-text and faceted search
├── test_install.py             # One-click install with RBAC
├── test_dependency_resolver.py # Dependency resolution
├── test_reviews.py             # Ratings, reviews, moderation
├── test_billing.py             # Stripe Connect, payments, payouts
├── test_analytics.py           # Usage analytics aggregation
├── test_marketplace_sync.py    # Public ↔ private sync
└── test_marketplace_e2e.py     # End-to-end marketplace workflows
```

## API Endpoints (Complete)

```
# Publisher Management
POST   /api/v1/marketplace/publishers/register            # Register as publisher (OAuth)
GET    /api/v1/marketplace/publishers/me                   # Current publisher profile
PUT    /api/v1/marketplace/publishers/me                   # Update publisher profile
POST   /api/v1/marketplace/publishers/me/verify            # Start verification
GET    /api/v1/marketplace/publishers/{slug}                # Public publisher profile
GET    /api/v1/marketplace/publishers/{slug}/packages       # Publisher's packages

# Publisher API Keys
POST   /api/v1/marketplace/publishers/me/api-keys          # Create API key
GET    /api/v1/marketplace/publishers/me/api-keys          # List API keys
DELETE /api/v1/marketplace/publishers/me/api-keys/{id}     # Revoke API key

# Packages
GET    /api/v1/marketplace/packages                        # Browse/search packages
GET    /api/v1/marketplace/packages/{slug}                  # Package detail
POST   /api/v1/marketplace/packages                        # Create package (draft)
PUT    /api/v1/marketplace/packages/{id}                   # Update package
DELETE /api/v1/marketplace/packages/{id}                   # Archive package

# Package Versions
GET    /api/v1/marketplace/packages/{id}/versions          # List versions
POST   /api/v1/marketplace/packages/{id}/versions          # Publish new version
GET    /api/v1/marketplace/packages/{id}/versions/{ver}     # Version detail
POST   /api/v1/marketplace/packages/{id}/versions/{ver}/yank  # Yank version

# Package Signing
POST   /api/v1/marketplace/packages/{id}/versions/{ver}/sign     # Upload signature
GET    /api/v1/marketplace/packages/{id}/versions/{ver}/verify   # Verify signature
GET    /api/v1/marketplace/packages/{id}/versions/{ver}/certificate  # View certificate

# Install
POST   /api/v1/marketplace/install                         # Install package
DELETE /api/v1/marketplace/install/{id}                    # Uninstall package
GET    /api/v1/marketplace/installed                       # List installed packages

# Reviews
GET    /api/v1/marketplace/packages/{id}/reviews           # List reviews
POST   /api/v1/marketplace/packages/{id}/reviews           # Submit review
PUT    /api/v1/marketplace/reviews/{id}                    # Update review
DELETE /api/v1/marketplace/reviews/{id}                    # Delete review
POST   /api/v1/marketplace/reviews/{id}/helpful            # Mark as helpful
POST   /api/v1/marketplace/reviews/{id}/flag               # Flag review

# Categories
GET    /api/v1/marketplace/categories                      # List categories
GET    /api/v1/marketplace/categories/{slug}                # Category detail with packages
GET    /api/v1/marketplace/featured                        # Featured packages
GET    /api/v1/marketplace/trending                        # Trending packages

# Search
GET    /api/v1/marketplace/search                          # Full-text search with facets

# Licensing
GET    /api/v1/marketplace/packages/{id}/license           # License details
GET    /api/v1/marketplace/license-compatibility            # Check license compatibility
GET    /api/v1/marketplace/workspace/sbom                  # Workspace SBOM

# Billing
POST   /api/v1/marketplace/publishers/me/stripe-connect    # Connect Stripe account
GET    /api/v1/marketplace/publishers/me/revenue            # Revenue dashboard
GET    /api/v1/marketplace/publishers/me/payouts            # Payout history
POST   /api/v1/marketplace/packages/{id}/purchase           # Purchase package
POST   /api/v1/marketplace/packages/{id}/subscribe          # Subscribe to package
DELETE /api/v1/marketplace/subscriptions/{id}              # Cancel subscription

# Analytics
GET    /api/v1/marketplace/publishers/me/analytics          # Creator analytics
GET    /api/v1/marketplace/packages/{id}/analytics          # Per-package analytics
GET    /api/v1/marketplace/publishers/me/feedback           # User feedback aggregate

# Review Pipeline (Admin)
GET    /api/v1/marketplace/admin/review-queue               # Pending reviews
POST   /api/v1/marketplace/admin/review/{id}/approve        # Approve submission
POST   /api/v1/marketplace/admin/review/{id}/reject         # Reject submission
PUT    /api/v1/marketplace/admin/categories                 # Manage categories
PUT    /api/v1/marketplace/admin/featured                   # Set featured packages

# Sync (Enterprise)
POST   /api/v1/marketplace/sync/pull                       # Pull from public marketplace
POST   /api/v1/marketplace/sync/export                     # Export for air-gapped install
POST   /api/v1/marketplace/sync/import                     # Import archive bundle
```

## Verify Commands

```bash
# Marketplace module importable
cd ~/Scripts/Archon && python -c "from backend.app.marketplace import MarketplaceService; print('OK')"

# Publisher auth importable
cd ~/Scripts/Archon && python -c "from backend.app.marketplace.publisher.auth import PublisherAuth; from backend.app.marketplace.publisher.verification import PublisherVerification; print('Publisher OK')"

# Package signing importable
cd ~/Scripts/Archon && python -c "from backend.app.marketplace.packages.signing import PackageSigner, SignatureVerifier; print('Signing OK')"

# Review pipeline importable
cd ~/Scripts/Archon && python -c "from backend.app.marketplace.review.pipeline import ReviewPipeline; print('Review OK')"

# License enforcement importable
cd ~/Scripts/Archon && python -c "from backend.app.marketplace.licensing.enforcement import LicenseEnforcer; print('License OK')"

# Install manager importable
cd ~/Scripts/Archon && python -c "from backend.app.marketplace.install.manager import InstallManager; print('Install OK')"

# Billing importable
cd ~/Scripts/Archon && python -c "from backend.app.marketplace.billing.stripe_connect import StripeConnectManager; print('Billing OK')"

# Analytics importable
cd ~/Scripts/Archon && python -c "from backend.app.marketplace.analytics.dashboard import CreatorDashboard; print('Analytics OK')"

# Tests pass
cd ~/Scripts/Archon && python -m pytest tests/test_marketplace/ --tb=short -q

# Frontend components build
cd ~/Scripts/Archon/frontend && npx tsc --noEmit

# No hardcoded secrets
cd ~/Scripts/Archon && ! grep -rn 'stripe_key\s*=\s*"[^"]*"' --include='*.py' backend/app/marketplace/ || echo 'FAIL'

# Docker compose is valid
cd ~/Scripts/Archon && docker compose config --quiet
```

## Learnings Protocol

Before starting, read `.sdd/learnings/*.md` for known pitfalls from previous sessions.
After completing work, report any pitfalls or patterns discovered so the orchestrator can capture them.

## Acceptance Criteria

- [ ] Publisher registration via GitHub, Google, and email OAuth flows working
- [ ] Publisher verification via email domain (DNS TXT) and GitHub org membership
- [ ] Publisher API keys functional for CI/CD pipeline publishing
- [ ] Every package signed with GPG or Sigstore; signature verified on install
- [ ] Transparency log entries created for all published packages
- [ ] Tamper detection blocks download of modified packages
- [ ] License compatibility enforcement blocks incompatible combinations with clear warnings
- [ ] Commercial license seat counting and expiry management working
- [ ] Automated review pipeline runs all 8 stages (security, credentials, DLP, license, schema, perf, compat, quality)
- [ ] Minimum score of 70 required for marketplace listing
- [ ] All 7 marketplace categories functional with editorial curation
- [ ] "Works with" compatibility badges and trending/top-rated lists working
- [ ] One-click install verifies RBAC (developer+ role), resolves dependencies, checks credentials
- [ ] Credential setup wizard redirects to Agent-00 for missing credentials
- [ ] Stripe Connect integration functional for paid packages
- [ ] Publisher revenue dashboard shows revenue, payouts, and subscriber metrics
- [ ] Usage analytics tracking: views, installs, error rates, ratings
- [ ] Creator dashboard with per-package analytics and trend visualization
- [ ] Reviews and ratings with moderation workflow
- [ ] Full-text search with faceted filtering by category, rating, tag, price
- [ ] Public ↔ private marketplace sync functional
- [ ] Air-gapped mode: export/import via archive bundle
- [ ] All endpoints match `contracts/openapi.yaml`
- [ ] 80%+ test coverage across all marketplace modules
- [ ] Zero plaintext secrets (Stripe keys, API keys) in logs, env vars, or source code
