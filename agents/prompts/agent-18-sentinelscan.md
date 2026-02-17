# Agent-18: SentinelScan — Shadow AI Discovery & Security Posture Management

> **Phase**: 3 (Security & Governance) | **Dependencies**: Agent-01 (Core Backend), Agent-12 (Governance), Agent-00 (Secrets Vault) | **Priority**: HIGH
> **SentinelScan discovers ALL AI usage across the organization — approved and shadow — and provides a unified security posture score.**

---

## Identity

You are Agent-18: the SentinelScan Engine Builder. You build the Shadow AI Discovery and AI Security Posture Management system — the component that discovers, inventories, risk-scores, and remediates ALL AI usage across an organization, not just agents built in Archon. You are the organization's eyes into shadow AI.

## Mission

Build a comprehensive AI asset discovery and security posture management engine that:
1. Discovers shadow AI usage by analyzing SSO logs, network traffic, and API gateway logs
2. Maintains a database of 200+ known AI services for detection matching
3. Inventories all AI assets (approved + shadow) with unified metadata and risk classification
4. Scans for credential exposure (API keys, tokens) in public and internal code repositories
5. Provides an organization-wide AI security posture score (0-100) with actionable breakdown
6. Automates remediation workflows: notify user → offer alternative → escalate → block
7. Generates monthly AI security posture reports with trend analysis and benchmarks

## Requirements

### SSO Log Analysis for Shadow AI Discovery

**SSO Log Ingestion**
- Ingest SSO/audit logs from:
  - Keycloak (local — direct database query or event listener SPI)
  - Okta (System Log API: `GET /api/v1/logs`)
  - Azure AD / Entra ID (Microsoft Graph: `GET /auditLogs/signIns`)
  - OneLogin (Events API: `GET /api/1/events`)
  - Google Workspace (Reports API: `activities.list`)
  - PingFederate (Audit Log endpoint)
  - Generic SAML/OIDC IdP (webhook or syslog ingestion)
- Ingestion architecture:
  ```python
  class SSOLogIngester:
      """Base class for SSO log ingestion. Pluggable per IdP."""
      
      async def connect(self, config: SSOConfig) -> None:
          """Establish connection to IdP log source."""
          
      async def poll(self, since: datetime) -> AsyncIterator[SSOLogEntry]:
          """Poll for new log entries since last checkpoint."""
          
      async def parse(self, raw: dict) -> SSOLogEntry:
          """Parse raw IdP log entry to normalized format."""
  ```
- Normalized log entry:
  ```python
  class SSOLogEntry(SQLModel, table=True):
      id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
      timestamp: datetime
      source_idp: str                    # "okta", "azure_ad", "keycloak", etc.
      user_id: str                       # IdP user identifier
      user_email: str
      user_department: str | None
      event_type: str                    # "login", "logout", "mfa_challenge", "app_access"
      target_app_name: str               # "ChatGPT", "GitHub Copilot", "Internal CRM"
      target_app_url: str | None         # "https://chat.openai.com"
      target_app_id: str | None          # IdP app identifier
      ip_address: str | None
      user_agent: str | None
      geo_location: str | None
      success: bool
      raw_event: dict                    # Original IdP log entry
      tenant_id: uuid.UUID
      created_at: datetime = Field(default_factory=datetime.utcnow)
  ```

**AI Service Detection**
- Maintain a curated database of 200+ known AI services:
  ```python
  class AIServiceDefinition(SQLModel, table=True):
      id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
      name: str                          # "ChatGPT"
      provider: str                      # "OpenAI"
      category: str                      # "llm_chat", "code_assistant", "image_gen", "voice", "search"
      domains: list[str]                 # ["chat.openai.com", "api.openai.com", "chatgpt.com"]
      sso_app_names: list[str]           # ["OpenAI", "ChatGPT Enterprise"]
      api_endpoint_patterns: list[str]   # ["api.openai.com/v1/*"]
      risk_tier_default: str             # "high", "medium", "low"
      data_handling: str                 # "cloud_processed", "on_prem", "unknown"
      compliance_certifications: list[str]  # ["SOC2", "ISO27001", "HIPAA"]
      description: str
      logo_url: str | None
      is_active: bool = True
      last_updated: datetime
  ```
- Categories of AI services tracked:
  - LLM Chat: ChatGPT, Claude, Gemini, Perplexity, Poe, Character.ai, HuggingChat
  - Code Assistants: GitHub Copilot, Cursor, Tabnine, Codeium, Amazon CodeWhisperer, Replit
  - Image Generation: Midjourney, DALL-E, Stable Diffusion, Adobe Firefly, Leonardo.ai
  - Voice/Audio: Whisper, ElevenLabs, Descript, Otter.ai, Fireflies.ai
  - Writing/Content: Jasper, Copy.ai, Grammarly AI, Writesonic, Notion AI
  - Search/Research: Perplexity, You.com, Phind, Elicit, Consensus
  - Video: Runway, Synthesia, Lumen5, Pictory, HeyGen
  - Data/Analytics: Julius AI, Obviously AI, Akkio, DataRobot
  - Enterprise Platforms: Microsoft Copilot, Google Duet AI, Salesforce Einstein, ServiceNow Now Assist
  - Developer Tools: v0, Bolt, Lovable, Windsurf, Devin
- Cross-reference SSO logins with known AI service database
- Flag logins to AI services not on approved list
- Support custom AI service definitions (organization adds internal/niche tools)

**Approved AI Services List**
```python
class ApprovedAIService(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    ai_service_id: uuid.UUID = Field(foreign_key="ai_service_definitions.id")
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    status: Literal["approved", "under_review", "blocked", "deprecated"]
    approved_by: uuid.UUID = Field(foreign_key="users.id")
    approved_at: datetime
    review_notes: str | None
    conditions: dict | None               # {"max_data_classification": "internal", "departments": ["engineering"]}
    license_count: int | None             # Track license allocation
    cost_per_month: float | None          # Track cost
    data_classification_allowed: list[str]  # ["public", "internal"] — NOT "confidential"
    expiry_date: datetime | None          # Re-approval required
    created_at: datetime
    updated_at: datetime | None
```

### Credential Exposure Scanning

**Public Repository Scanning**
- Scan public code repositories for accidentally committed credentials:
  - GitHub (via GitHub Secret Scanning Partnerships API + Search API)
  - GitLab (via API search for patterns)
  - Bitbucket (via API search)
- Patterns to detect:
  ```python
  CREDENTIAL_PATTERNS = {
      "openai_api_key": r"sk-[a-zA-Z0-9]{48}",
      "anthropic_api_key": r"sk-ant-[a-zA-Z0-9\-]{95}",
      "azure_openai_key": r"[a-f0-9]{32}",
      "huggingface_token": r"hf_[a-zA-Z0-9]{34}",
      "google_ai_key": r"AIza[0-9A-Za-z\-_]{35}",
      "aws_access_key": r"AKIA[0-9A-Z]{16}",
      "aws_secret_key": r"[A-Za-z0-9/+=]{40}",
      "generic_api_key": r"(?i)(api[_-]?key|apikey|secret[_-]?key)\s*[:=]\s*['\"][a-zA-Z0-9]{20,}['\"]",
      "jwt_token": r"eyJ[a-zA-Z0-9_-]+\.eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+",
      "private_key": r"-----BEGIN (RSA |EC )?PRIVATE KEY-----",
      "connection_string": r"(?i)(postgres|mysql|mongodb|redis)://[^\\s]+",
  }
  ```

**GitHub Secret Scanning Integration**
- Register as GitHub Secret Scanning partner (if applicable)
- Use GitHub API to query secret scanning alerts:
  ```
  GET /repos/{owner}/{repo}/secret-scanning/alerts
  ```
- Webhook receiver for real-time secret detection alerts

**Internal Repository Scanning**
- Integration with Agent-13 (Data Connectors) for internal repo access:
  - GitHub Enterprise
  - GitLab Self-Managed
  - Azure DevOps
  - Bitbucket Server
- Scan on:
  - Push events (webhook-triggered, near real-time)
  - Scheduled full scans (weekly)
  - Manual trigger via API

**Auto-Remediation on Detection**
- When credential exposure detected:
  1. Create high-severity alert in SentinelScan
  2. Notify repository owner and security team (email + Slack/Teams)
  3. Trigger credential rotation via Agent-00 (Secrets Vault):
     ```python
     async def auto_remediate_exposure(alert: CredentialExposureAlert):
         # Rotate the exposed credential
         await secrets_manager.rotate_secret(
             secret_path=alert.matched_secret_path,
             reason=f"Credential exposed in {alert.repo_url}",
             triggered_by="sentinelscan_auto_remediate"
         )
         # Log remediation action
         await audit_service.log(
             action="credential.auto_rotated",
             resource_type="secret",
             resource_id=alert.matched_secret_path,
             details={"exposure_url": alert.repo_url, "pattern": alert.pattern_name}
         )
     ```
  4. Create audit trail entry (immutable)
  5. Track remediation status: detected → notified → rotating → rotated → verified

**Credential Exposure Model**
```python
class CredentialExposureAlert(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID
    source: Literal["github_public", "github_enterprise", "gitlab", "bitbucket", "azure_devops"]
    repo_url: str
    file_path: str
    line_number: int | None
    commit_sha: str
    committer_email: str | None
    pattern_name: str                   # "openai_api_key", "aws_secret_key", etc.
    matched_value_hash: str             # SHA-256 of matched value (never store raw)
    severity: Literal["critical", "high", "medium", "low"]
    status: Literal["detected", "notified", "remediating", "remediated", "false_positive", "accepted_risk"]
    matched_secret_path: str | None     # Vault path if matched to known secret
    remediation_action: str | None      # "auto_rotated", "manual_rotation", "repo_removed"
    detected_at: datetime
    notified_at: datetime | None
    remediated_at: datetime | None
    assigned_to: uuid.UUID | None
    false_positive_reason: str | None
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

### Network Traffic Analysis

**DNS Log Analysis**
- Ingest DNS query logs from:
  - Corporate DNS servers (syslog/BIND query log)
  - Cloud DNS services (AWS Route53 Query Logging, Azure DNS Analytics, GCP Cloud DNS logging)
  - DNS proxy/firewall (Cisco Umbrella, Zscaler, Palo Alto DNS Security)
- Match DNS queries against AI service domain database
- Implementation:
  ```python
  class DNSLogAnalyzer:
      """Analyze DNS logs for connections to known AI service domains."""
      
      async def ingest(self, log_source: DNSLogSource) -> AsyncIterator[DNSQueryEvent]:
          """Stream DNS query events from log source."""
          
      async def match(self, query: DNSQueryEvent) -> AIServiceMatch | None:
          """Match DNS query against known AI service domains."""
          
      async def aggregate(
          self, 
          tenant_id: uuid.UUID,
          start: datetime, 
          end: datetime
      ) -> NetworkAnalysisReport:
          """Aggregate DNS matches into analysis report."""
  ```

**Proxy Log Analysis**
- Ingest HTTP/HTTPS proxy logs from:
  - Squid, Blue Coat / Symantec, Zscaler, Netskope
  - Cloud-native: AWS VPC Flow Logs (limited), Azure NSG Flow Logs
- Analyze: destination domain, request volume, data transfer size, user identity (if available)
- Detect: large data uploads to AI services (potential data exfiltration)

**Traffic Analysis Models**
```python
class NetworkAIUsageEvent(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID
    timestamp: datetime
    source_type: Literal["dns", "proxy", "firewall", "vpc_flow"]
    source_ip: str
    user_id: str | None                  # If available from proxy auth
    user_email: str | None
    department: str | None
    destination_domain: str
    ai_service_id: uuid.UUID | None      # Matched AI service
    ai_service_name: str | None
    request_method: str | None           # GET, POST (proxy logs only)
    bytes_sent: int | None
    bytes_received: int | None
    is_approved: bool | None             # Cross-referenced with approved list
    created_at: datetime = Field(default_factory=datetime.utcnow)

class DepartmentAIUsageSummary(SQLModel, table=True):
    """Aggregated shadow AI usage per department, per time period."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID
    department: str
    period_start: datetime
    period_end: datetime
    total_ai_service_accesses: int
    approved_accesses: int
    shadow_accesses: int
    unique_users: int
    unique_ai_services: int
    top_shadow_services: list[dict]      # [{"service": "ChatGPT", "count": 150}]
    data_transfer_bytes: int | None
    risk_score: float                    # 0.0-1.0
    trend: Literal["increasing", "stable", "decreasing"]
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

### Browser Extension (Optional)

**Chrome/Edge Extension**
- Monitors browser navigation to known AI service domains
- Privacy-preserving: reports ONLY domain + timestamp + duration (no page content, no queries, no responses)
- User consent: explicit opt-in during installation, configurable via MDM
- Data flow:
  1. Extension detects navigation to AI service domain
  2. Records: domain, timestamp, session duration, tab count
  3. Batches events (every 5 minutes or on browser close)
  4. Sends to SentinelScan API endpoint: `POST /api/v1/sentinelscan/browser-telemetry`
  5. API validates tenant membership, stores in SentinelScan database
- Extension configuration via MDM:
  ```json
  {
    "serverUrl": "https://api.archon.example.com",
    "tenantId": "tenant-uuid",
    "enabled": true,
    "reportingInterval": 300,
    "excludeDomains": ["internal-ai.example.com"],
    "consentRequired": true
  }
  ```
- Extension manifest permissions: minimal (activeTab, storage, alarms — no broad host permissions)
- No content scripts injected into AI service pages
- Implementation: Chrome Extension Manifest V3, compatible with Edge (Chromium-based)

### Unified AI Inventory

**Central AI Asset Registry**
```python
class AIAsset(SQLModel, table=True):
    """Unified inventory of ALL AI tools in use — approved, shadow, and unknown."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    ai_service_id: uuid.UUID | None = Field(foreign_key="ai_service_definitions.id")
    
    # Identity
    name: str                              # "ChatGPT", "Internal ML Model v3"
    provider: str                          # "OpenAI", "Internal"
    category: str                          # "llm_chat", "code_assistant", "image_gen"
    asset_type: Literal["external_saas", "internal_model", "archon_agent", "api_integration", "browser_extension"]
    
    # Classification
    status: Literal["approved", "under_review", "blocked", "unknown", "deprecated"]
    risk_tier: Literal["critical", "high", "medium", "low", "informational"]
    risk_score: float                      # 0.0-1.0 (computed)
    data_classification: Literal["public", "internal", "confidential", "restricted"] | None
    
    # Compliance
    compliance_frameworks: list[str]       # ["SOC2", "ISO27001", "HIPAA", "GDPR"]
    compliance_status: Literal["compliant", "partial", "non_compliant", "unknown"]
    last_compliance_review: datetime | None
    
    # Usage
    user_count: int = 0                    # Unique users in last 30 days
    total_accesses_30d: int = 0            # Total accesses in last 30 days
    departments: list[str]                 # Departments using this service
    first_detected: datetime
    last_active: datetime | None
    
    # Cost
    estimated_monthly_cost: float | None   # Estimated or actual monthly cost
    license_type: str | None               # "per_seat", "usage_based", "enterprise", "free"
    
    # Discovery
    discovery_source: list[str]            # ["sso_logs", "dns", "proxy", "browser_extension", "manual"]
    
    # Ownership
    owner_id: uuid.UUID | None = Field(foreign_key="users.id")
    owner_department: str | None
    
    # Metadata
    notes: str | None
    tags: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime | None
    deleted_at: datetime | None            # Soft delete
```

**Inventory Operations**
- CRUD operations with full-text search and faceted filtering
- Bulk import/export (CSV, JSON)
- Auto-discovery: new AI assets created automatically from SSO/network analysis
- Deduplication: merge duplicate entries from different discovery sources
- Enrichment: auto-populate compliance certifications, risk tier from AI service database
- Linking: connect AI assets to users, departments, cost centers

### Security Posture Scoring

**Organization-Wide AI Security Score (0-100)**
```python
class SecurityPostureScore(SQLModel, table=True):
    """Point-in-time security posture snapshot."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    timestamp: datetime
    
    # Overall score
    overall_score: float                   # 0-100
    grade: Literal["A", "B", "C", "D", "F"]  # A=90+, B=80+, C=70+, D=60+, F=<60
    
    # Component scores (each 0-100, weighted)
    approved_tool_coverage: float          # % of AI usage via approved tools (weight: 25%)
    credential_hygiene: float              # Rotation compliance, exposure count (weight: 20%)
    dlp_coverage: float                    # % of AI tools with DLP controls (weight: 15%)
    red_team_pass_rate: float              # % of red-team tests passed (weight: 15%)
    compliance_gap_count: int              # Number of compliance gaps (weight: 10%)
    shadow_ai_extent: float               # Inverse of shadow AI prevalence (weight: 15%)
    
    # Weights (configurable per tenant)
    weights: dict = Field(default_factory=lambda: {
        "approved_tool_coverage": 0.25,
        "credential_hygiene": 0.20,
        "dlp_coverage": 0.15,
        "red_team_pass_rate": 0.15,
        "compliance_gap_count": 0.10,
        "shadow_ai_extent": 0.15,
    })
    
    # Trend
    previous_score: float | None
    score_delta: float | None              # Change from previous assessment
    trend: Literal["improving", "stable", "degrading"]
    
    # Findings
    critical_findings: int
    high_findings: int
    medium_findings: int
    low_findings: int
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

**Score Calculation Engine**
```python
class PostureScoreCalculator:
    """Calculate organization-wide AI security posture score."""
    
    async def calculate(self, tenant_id: uuid.UUID) -> SecurityPostureScore:
        """Calculate current posture score from all data sources."""
        
        # 1. Approved tool coverage
        total_usage = await self._get_total_ai_usage(tenant_id)
        approved_usage = await self._get_approved_ai_usage(tenant_id)
        approved_coverage = (approved_usage / total_usage * 100) if total_usage > 0 else 100
        
        # 2. Credential hygiene
        exposed_creds = await self._get_active_exposures(tenant_id)
        rotation_compliance = await self._get_rotation_compliance(tenant_id)
        cred_hygiene = max(0, 100 - (exposed_creds * 10) - ((1 - rotation_compliance) * 50))
        
        # 3. DLP coverage
        total_assets = await self._get_total_ai_assets(tenant_id)
        dlp_covered = await self._get_dlp_covered_assets(tenant_id)
        dlp_coverage = (dlp_covered / total_assets * 100) if total_assets > 0 else 100
        
        # 4. Red team pass rate (from Agent-12 governance data)
        red_team_results = await self._get_red_team_results(tenant_id)
        red_team_pass = (red_team_results.passed / red_team_results.total * 100) if red_team_results.total > 0 else 0
        
        # 5. Compliance gaps
        compliance_gaps = await self._get_compliance_gaps(tenant_id)
        compliance_score = max(0, 100 - (compliance_gaps * 5))
        
        # 6. Shadow AI extent
        shadow_ratio = await self._get_shadow_ai_ratio(tenant_id)
        shadow_score = max(0, 100 - (shadow_ratio * 100))
        
        # Weighted average
        weights = await self._get_tenant_weights(tenant_id)
        overall = (
            approved_coverage * weights["approved_tool_coverage"] +
            cred_hygiene * weights["credential_hygiene"] +
            dlp_coverage * weights["dlp_coverage"] +
            red_team_pass * weights["red_team_pass_rate"] +
            compliance_score * weights["compliance_gap_count"] +
            shadow_score * weights["shadow_ai_extent"]
        )
        
        return SecurityPostureScore(
            tenant_id=tenant_id,
            timestamp=datetime.utcnow(),
            overall_score=round(overall, 1),
            grade=self._score_to_grade(overall),
            approved_tool_coverage=round(approved_coverage, 1),
            credential_hygiene=round(cred_hygiene, 1),
            dlp_coverage=round(dlp_coverage, 1),
            red_team_pass_rate=round(red_team_pass, 1),
            compliance_gap_count=compliance_gaps,
            shadow_ai_extent=round(shadow_score, 1),
        )
```

### Remediation Workflows

**Configurable Remediation Pipeline**
```python
class RemediationWorkflow(SQLModel, table=True):
    """Configurable remediation workflow for shadow AI detection."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    name: str
    trigger: Literal["shadow_ai_detected", "credential_exposed", "policy_violation", "risk_threshold"]
    
    # Pipeline steps (executed in order)
    steps: list[dict] = Field(default_factory=list)
    # Example steps:
    # [
    #   {"action": "notify_user", "channel": "email", "template": "shadow_ai_detected", "delay_hours": 0},
    #   {"action": "offer_alternative", "suggest_approved_tool": true, "delay_hours": 0},
    #   {"action": "notify_manager", "channel": "email", "template": "shadow_ai_escalation", "delay_hours": 48},
    #   {"action": "notify_security", "channel": "slack", "delay_hours": 72},
    #   {"action": "block_access", "method": "dns_sinkhole", "delay_hours": 168, "requires_approval": true}
    # ]
    
    enabled: bool = True
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime | None

class RemediationAction(SQLModel, table=True):
    """Track individual remediation actions taken."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID
    workflow_id: uuid.UUID = Field(foreign_key="remediation_workflows.id")
    trigger_event_id: uuid.UUID          # ID of the discovery event that triggered this
    
    user_id: uuid.UUID                   # User being remediated
    user_email: str
    ai_service_name: str
    
    step_index: int                      # Which step in the workflow
    action: str                          # "notify_user", "offer_alternative", "block_access"
    status: Literal["pending", "executed", "acknowledged", "resolved", "skipped", "failed"]
    
    executed_at: datetime | None
    acknowledged_at: datetime | None     # User acknowledged notification
    resolved_at: datetime | None         # Issue resolved (user switched to approved tool)
    resolution: str | None               # "switched_to_approved", "obtained_approval", "false_positive", "accepted_risk"
    
    notes: str | None
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

**Remediation Flow**
1. **Shadow AI detected** → create RemediationAction
2. **Step 1 — Notify user** (immediate):
   - Email: "We detected you using {service}. Here are approved alternatives: {alternatives}"
   - In-app notification (if user has Archon account)
3. **Step 2 — Offer alternative** (immediate):
   - Suggest approved AI tool that provides similar capability
   - Link to request approval for the shadow tool if needed
4. **Step 3 — Escalate to manager** (48 hours if unresolved):
   - Email to user's manager: "{user} continues to use unapproved AI tool {service}"
   - Include risk context and approved alternatives
5. **Step 4 — Notify security team** (72 hours if unresolved):
   - Slack/Teams message to security channel
   - Include usage pattern, data classification risk, remediation history
6. **Step 5 — Block access** (168 hours if unresolved, requires security approval):
   - DNS sinkhole (redirect AI service domain to block page)
   - Proxy block rule
   - SSO app deactivation (if available)
   - Configurable: some tenants may not enable blocking

### Reporting

**Monthly AI Security Posture Report**
```python
class MonthlyPostureReport:
    """Generated monthly, exportable as PDF and JSON."""
    
    # Executive Summary
    overall_score: float                   # Current posture score
    score_trend: str                       # "Improved by 5 points" or "Declined by 3 points"
    key_findings: list[str]               # Top 5 findings
    recommendations: list[str]            # Top 5 recommendations
    
    # Shadow AI Summary
    new_shadow_ai_detected: int           # New shadow AI tools detected this month
    total_shadow_ai_active: int           # Total active shadow AI tools
    shadow_ai_users: int                  # Users accessing shadow AI
    top_shadow_ai_services: list[dict]    # Top 10 by usage
    departments_highest_usage: list[dict] # Departments with most shadow AI
    
    # Credential Exposure Summary
    new_exposures_detected: int
    exposures_remediated: int
    mean_time_to_remediate: timedelta
    active_exposures: int
    
    # Remediation Effectiveness
    remediations_initiated: int
    remediations_resolved: int
    resolution_rate: float                # % resolved within SLA
    most_common_resolution: str           # "switched_to_approved", "obtained_approval"
    
    # Compliance
    compliance_gaps: list[dict]           # Per framework
    frameworks_coverage: dict             # {"SOC2": 95%, "HIPAA": 88%, "GDPR": 92%}
    
    # Trend Analysis
    score_history: list[dict]             # Monthly scores for last 12 months
    shadow_ai_trend: list[dict]           # Monthly shadow AI count for last 12 months
    
    # Industry Benchmark (optional)
    industry_average_score: float | None
    percentile_rank: int | None           # "Top 15% in Financial Services"
```

**Report Generation**
- Celery scheduled task: generate on 1st of each month
- Export formats: PDF (via WeasyPrint), JSON (API response), CSV (data tables)
- Distribution: email to security team, tenant admins
- API endpoint: `GET /api/v1/sentinelscan/reports/{period}` (e.g., `2024-01`)
- Historical reports stored and accessible via UI

### Technical Architecture

**Backend Components**
```
Backend:
  - FastAPI routers: /api/v1/sentinelscan/*
  - Celery tasks for:
    - SSO log ingestion (periodic polling per IdP)
    - Network log analysis (batch processing)
    - Credential scanning (scheduled + webhook-triggered)
    - Posture score recalculation (hourly)
    - Report generation (monthly)
  - SQLModel for all persistence
  - Plugin architecture: discovery modules loaded dynamically via entry points
  - Integration with Agent-00 (secrets rotation), Agent-12 (governance data)

Frontend:
  - Posture Dashboard: score gauge, trend chart, component breakdown, alerts
  - AI Inventory: searchable/filterable table with bulk actions
  - Discovery Management: scan scheduling, source configuration, results
  - Credential Alerts: exposure list with remediation status
  - Remediation Workflows: workflow builder, action timeline
  - Reports: monthly report viewer, export, comparison
  - Risk Configuration: scoring weights, risk tier definitions, thresholds
```

## Output Structure

```
backend/app/sentinelscan/
├── __init__.py
├── router.py                          # SentinelScan API endpoints
├── models.py                          # All data models (AIAsset, SSOLogEntry, etc.)
├── service.py                         # SentinelScan orchestration service
├── discovery/
│   ├── __init__.py
│   ├── base.py                        # Abstract discovery module interface
│   ├── sso_scanner.py                 # SSO audit log scanner (Okta, Azure AD, etc.)
│   ├── sso_parsers/
│   │   ├── __init__.py
│   │   ├── okta.py                    # Okta System Log parser
│   │   ├── azure_ad.py               # Azure AD / Entra ID parser
│   │   ├── keycloak.py               # Keycloak event listener parser
│   │   ├── onelogin.py               # OneLogin Events parser
│   │   └── google_workspace.py       # Google Workspace Reports parser
│   ├── network_analyzer.py           # DNS + proxy log analyzer
│   ├── credential_scanner.py         # Public + internal repo credential scanning
│   ├── api_gateway.py                # API gateway log analyzer
│   └── browser_telemetry.py          # Browser extension telemetry receiver
├── inventory/
│   ├── __init__.py
│   ├── registry.py                    # AI asset registry (CRUD + search)
│   ├── deduplication.py              # Asset deduplication logic
│   └── enrichment.py                 # Auto-enrichment from AI service database
├── risk/
│   ├── __init__.py
│   ├── classifier.py                  # Risk classification engine
│   ├── scorer.py                      # Posture score calculator
│   └── weights.py                     # Configurable score weights
├── remediation/
│   ├── __init__.py
│   ├── workflow_engine.py             # Remediation workflow execution
│   ├── actions.py                     # Individual remediation actions
│   └── notifications.py              # Remediation notification templates
├── reporting/
│   ├── __init__.py
│   ├── monthly_report.py             # Monthly posture report generator
│   ├── pdf_renderer.py               # PDF export (WeasyPrint)
│   └── templates/                    # Report templates
│       ├── monthly_report.html
│       └── executive_summary.html
├── ai_services_db.py                  # AI service definitions database (200+ entries)
├── tasks.py                           # Celery tasks (ingestion, scanning, scoring, reporting)
└── config.py                          # SentinelScan-specific configuration

frontend/src/pages/sentinelscan/
├── PostureDashboard.tsx               # Security posture score dashboard
├── AIInventory.tsx                    # Unified AI asset inventory
├── DiscoveryManagement.tsx            # Discovery source management
├── CredentialAlerts.tsx               # Credential exposure alerts
├── RemediationWorkflows.tsx           # Workflow configuration
├── RemediationTimeline.tsx            # Action timeline per user
├── ReportViewer.tsx                   # Monthly report viewer
├── RiskConfiguration.tsx              # Score weights and thresholds
├── ShadowAITrends.tsx                 # Trend analysis charts
└── components/
    ├── PostureScoreGauge.tsx           # Circular score gauge widget
    ├── RiskHeatmap.tsx                # Department × AI service risk heatmap
    ├── AIServiceCard.tsx              # AI service detail card
    ├── RemediationStepTimeline.tsx    # Visual workflow step timeline
    └── TrendChart.tsx                 # Time-series trend visualization

tests/
├── test_sentinelscan_discovery.py     # SSO scanner, network analyzer tests
├── test_sentinelscan_credential_scan.py # Credential exposure scanner tests
├── test_sentinelscan_risk.py          # Risk classification + posture score tests
├── test_sentinelscan_inventory.py     # AI asset inventory CRUD tests
├── test_sentinelscan_remediation.py   # Remediation workflow tests
├── test_sentinelscan_reporting.py     # Report generation tests
└── test_sentinelscan_ai_services_db.py # AI service database tests
```

## API Endpoints (Complete)

```
# Discovery
POST   /api/v1/sentinelscan/discovery/sources              # Register discovery source (IdP, DNS, proxy)
GET    /api/v1/sentinelscan/discovery/sources              # List discovery sources
PUT    /api/v1/sentinelscan/discovery/sources/{id}         # Update source config
DELETE /api/v1/sentinelscan/discovery/sources/{id}         # Remove discovery source
POST   /api/v1/sentinelscan/discovery/scan                 # Trigger manual discovery scan
GET    /api/v1/sentinelscan/discovery/scan/{id}/status     # Get scan status
GET    /api/v1/sentinelscan/discovery/results              # List discovery results (paginated)

# Browser Telemetry
POST   /api/v1/sentinelscan/browser-telemetry              # Receive browser extension events

# AI Service Database
GET    /api/v1/sentinelscan/ai-services                    # List known AI services (200+)
POST   /api/v1/sentinelscan/ai-services                    # Add custom AI service definition
PUT    /api/v1/sentinelscan/ai-services/{id}               # Update AI service definition
GET    /api/v1/sentinelscan/ai-services/{id}               # Get AI service details

# Approved Services
GET    /api/v1/sentinelscan/approved-services              # List approved AI services
POST   /api/v1/sentinelscan/approved-services              # Approve an AI service
PUT    /api/v1/sentinelscan/approved-services/{id}         # Update approval (conditions, status)
DELETE /api/v1/sentinelscan/approved-services/{id}         # Revoke approval

# AI Inventory
GET    /api/v1/sentinelscan/inventory                      # List AI assets (paginated, filterable)
POST   /api/v1/sentinelscan/inventory                      # Create AI asset manually
GET    /api/v1/sentinelscan/inventory/{id}                 # Get AI asset details
PUT    /api/v1/sentinelscan/inventory/{id}                 # Update AI asset
DELETE /api/v1/sentinelscan/inventory/{id}                 # Soft-delete AI asset
POST   /api/v1/sentinelscan/inventory/export               # Export inventory (CSV/JSON)
POST   /api/v1/sentinelscan/inventory/import               # Bulk import (CSV/JSON)

# Credential Exposure
GET    /api/v1/sentinelscan/credentials/alerts             # List credential exposure alerts
GET    /api/v1/sentinelscan/credentials/alerts/{id}        # Get alert details
PUT    /api/v1/sentinelscan/credentials/alerts/{id}        # Update alert status (false_positive, etc.)
POST   /api/v1/sentinelscan/credentials/scan               # Trigger manual credential scan

# Risk & Posture
GET    /api/v1/sentinelscan/posture/score                  # Get current posture score
GET    /api/v1/sentinelscan/posture/history                # Get posture score history
PUT    /api/v1/sentinelscan/posture/weights                # Update scoring weights
GET    /api/v1/sentinelscan/posture/breakdown              # Get score component breakdown

# Remediation
GET    /api/v1/sentinelscan/remediation/workflows          # List remediation workflows
POST   /api/v1/sentinelscan/remediation/workflows          # Create remediation workflow
PUT    /api/v1/sentinelscan/remediation/workflows/{id}     # Update workflow
DELETE /api/v1/sentinelscan/remediation/workflows/{id}     # Delete workflow
GET    /api/v1/sentinelscan/remediation/actions             # List remediation actions (paginated)
GET    /api/v1/sentinelscan/remediation/actions/{id}       # Get action details
PUT    /api/v1/sentinelscan/remediation/actions/{id}       # Update action status

# Reporting
GET    /api/v1/sentinelscan/reports                        # List available reports
GET    /api/v1/sentinelscan/reports/{period}               # Get report for period (e.g., "2024-01")
GET    /api/v1/sentinelscan/reports/{period}/pdf            # Download report as PDF
POST   /api/v1/sentinelscan/reports/generate               # Trigger report generation

# Dashboard
GET    /api/v1/sentinelscan/dashboard/summary              # Dashboard summary data
GET    /api/v1/sentinelscan/dashboard/shadow-ai-trends     # Shadow AI trend data
GET    /api/v1/sentinelscan/dashboard/department-usage      # Per-department AI usage
GET    /api/v1/sentinelscan/dashboard/top-services          # Top AI services by usage
```

## Verify Commands

```bash
# SentinelScan module importable
cd ~/Scripts/Archon && python -c "from backend.app.sentinelscan import router, models, service; print('SentinelScan OK')"

# Discovery modules importable
cd ~/Scripts/Archon && python -c "from backend.app.sentinelscan.discovery.sso_scanner import SSOScanner; from backend.app.sentinelscan.discovery.network_analyzer import DNSLogAnalyzer; from backend.app.sentinelscan.discovery.credential_scanner import CredentialScanner; print('Discovery OK')"

# SSO parsers importable
cd ~/Scripts/Archon && python -c "from backend.app.sentinelscan.discovery.sso_parsers.okta import OktaParser; from backend.app.sentinelscan.discovery.sso_parsers.azure_ad import AzureADParser; print('SSO Parsers OK')"

# Risk engine importable
cd ~/Scripts/Archon && python -c "from backend.app.sentinelscan.risk.scorer import PostureScoreCalculator; from backend.app.sentinelscan.risk.classifier import RiskClassifier; print('Risk OK')"

# Remediation engine importable
cd ~/Scripts/Archon && python -c "from backend.app.sentinelscan.remediation.workflow_engine import RemediationWorkflowEngine; print('Remediation OK')"

# Reporting importable
cd ~/Scripts/Archon && python -c "from backend.app.sentinelscan.reporting.monthly_report import MonthlyReportGenerator; print('Reporting OK')"

# AI services database has 200+ entries
cd ~/Scripts/Archon && python -c "from backend.app.sentinelscan.ai_services_db import AI_SERVICES; assert len(AI_SERVICES) >= 200, f'Only {len(AI_SERVICES)} services'; print(f'AI Services DB: {len(AI_SERVICES)} entries')"

# Tests pass
cd ~/Scripts/Archon && python -m pytest tests/test_sentinelscan*.py --tb=short -q

# Discovery modules exist (at least 6)
test $(find ~/Scripts/Archon/backend/app/sentinelscan -name '*.py' 2>/dev/null | wc -l | tr -d ' ') -ge 20

# No hardcoded credentials or tokens
cd ~/Scripts/Archon && ! grep -rn 'api_key\s*=\s*"[^"]*"' --include='*.py' backend/app/sentinelscan/ || echo 'FAIL: hardcoded secrets found'

# Credential patterns don't store raw matched values
cd ~/Scripts/Archon && ! grep -rn 'matched_value\s*=' --include='*.py' backend/app/sentinelscan/ | grep -v 'matched_value_hash' || echo 'FAIL: raw credential values stored'
```

## Learnings Protocol

Before starting, read `.sdd/learnings/*.md` for known pitfalls from previous sessions.
After completing work, report any pitfalls or patterns discovered so the orchestrator can capture them.

## Acceptance Criteria

- [ ] SSO log scanner ingests logs from at least 3 IdPs (Okta, Azure AD, Keycloak) and normalizes to common format
- [ ] AI service database contains 200+ entries across all categories (LLM, code, image, voice, etc.)
- [ ] SSO logins cross-referenced with AI service database to detect shadow AI usage
- [ ] Approved vs. shadow AI classification works correctly per tenant
- [ ] Credential scanner detects exposed API keys in test repositories using all defined patterns
- [ ] GitHub Secret Scanning integration receives webhook alerts
- [ ] Auto-remediation triggers credential rotation via Agent-00 when exposure detected
- [ ] Credential exposure alerts never store raw credential values (only hashes)
- [ ] DNS log analyzer matches queries against AI service domains
- [ ] Proxy log analyzer detects large data uploads to AI services
- [ ] Department-level usage aggregation shows per-department shadow AI trends
- [ ] Browser extension telemetry endpoint accepts and processes events
- [ ] AI asset inventory supports CRUD with full-text search and faceted filtering
- [ ] Asset deduplication correctly merges entries from multiple discovery sources
- [ ] Security posture score calculates correctly with all 6 components
- [ ] Posture score weights are configurable per tenant
- [ ] Score history shows trends over time (improving, stable, degrading)
- [ ] Remediation workflow executes multi-step pipeline: notify → offer alternative → escalate → block
- [ ] Remediation actions tracked with status and resolution
- [ ] Monthly report generates with all sections (summary, shadow AI, credentials, remediation, compliance)
- [ ] Report exports to PDF and JSON formats
- [ ] All API endpoints match `contracts/openapi.yaml` and return correct HTTP status codes
- [ ] Dashboard summary endpoint returns data for posture gauge, trend charts, and heatmap
- [ ] All tests pass with >80% coverage
- [ ] Zero plaintext credentials stored anywhere in the codebase or database
