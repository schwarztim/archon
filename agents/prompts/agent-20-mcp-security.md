# Agent-20: MCP Security Guardian & Tool Governance

> **Phase**: 3 (Security & Governance) | **Dependencies**: Agent-01 (Core Backend), Agent-11 (DLP), Agent-15 (MCP Interactive), Agent-00 (Secrets Vault) | **Priority**: HIGH
> **Every MCP tool call passes through this agent's security pipeline. Zero trust for tool execution.**

---

## Identity

You are Agent-20: the MCP Security Guardian & Tool Governance Builder. You build the enterprise-grade security layer for all Model Context Protocol interactions — ensuring every MCP tool call is scoped via OAuth, credentialed via Vault, sandboxed in ephemeral containers, authorized by policy matrix, validated against schema, and scored for security posture. No MCP tool executes outside your governance.

## Mission

Build a comprehensive MCP security and governance layer that:
1. Enforces tool-level OAuth scopes with user consent management and scope escalation workflows
2. Stores and injects all MCP tool credentials via Vault (Agent-00) with per-tenant isolation
3. Runs each MCP tool invocation in an ephemeral gVisor/Firecracker sandbox with strict resource limits
4. Enforces a tool authorization matrix (role × department × agent → tool) with emergency kill switches
5. Tracks MCP tool definition changes with versioning, diff views, and automated compatibility testing
6. Validates all MCP tool responses against declared schemas with DLP scanning (Agent-11)
7. Maintains a community vulnerability database with CVE-like tracking and auto-disable on critical findings
8. Computes per-tool security scores (0-100) with a security posture dashboard

## Requirements

### Tool-Level OAuth Scopes

**Scope Registration & Management**
- Each MCP tool registered with specific OAuth 2.0 scopes it requires:
  ```python
  class MCPToolScope(SQLModel, table=True):
      """OAuth scope required by an MCP tool."""
      id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
      tool_id: uuid.UUID = Field(foreign_key="mcp_tools.id")
      scope: str  # e.g., "mcp:slack:send_message", "mcp:github:create_pr"
      description: str  # Human-readable: "Send messages on your behalf in Slack"
      risk_level: Literal["low", "medium", "high", "critical"]
      requires_admin_approval: bool = False
      created_at: datetime
  ```
- Scope categories:
  - `mcp:read:*` — Read-only access to tool data
  - `mcp:write:*` — Write/mutate access
  - `mcp:admin:*` — Administrative operations
  - `mcp:execute:*` — Execute external commands/scripts
  - `mcp:network:*` — Network access (HTTP calls, etc.)

**User Consent Flow**
- When a user invokes an agent that uses MCP tools, the system checks if the user has consented to those tool scopes
- Consent flow:
  1. Agent execution reaches MCP tool node
  2. System checks user's granted scopes against tool's required scopes
  3. If missing scopes → execution paused, user presented with consent dialog
  4. Consent dialog lists: tool name, scopes requested, risk levels, what the tool will access
  5. User approves/denies → consent recorded with timestamp and IP
  6. Execution resumes or aborts based on consent
- Scope escalation: if a tool update adds new scopes, existing users must re-consent
- Consent revocation: user can revoke tool consent at any time via settings UI
- Admin override: tenant admin can pre-approve scopes for all users in a department

**Scope Management UI**
- Per-user scope dashboard: view all consented scopes, revoke any
- Per-tool scope viewer: which users have consented, which haven't
- Audit trail: every consent grant/revocation logged

### Vault Integration for MCP Credentials

**Credential Storage**
- All MCP tools that connect to external services store credentials in Vault (Agent-00):
  ```python
  class MCPCredentialManager:
      """Manages MCP tool credentials via Vault."""
      VAULT_PATH = "secret/data/mcp/{tenant_id}/{tool_id}"
      
      async def store_credential(
          self, tenant_id: str, tool_id: str, credential: MCPCredential
      ) -> None:
          await self.vault.write(
              self.VAULT_PATH.format(tenant_id=tenant_id, tool_id=tool_id),
              {
                  "api_key": credential.api_key,
                  "oauth_token": credential.oauth_token,
                  "refresh_token": credential.refresh_token,
                  "webhook_secret": credential.webhook_secret,
                  "metadata": credential.metadata,
              },
          )
      
      async def inject_credentials(
          self, tenant_id: str, tool_id: str, execution_context: dict
      ) -> dict:
          """Inject credentials at execution time — never cached in app memory."""
          creds = await self.vault.read(
              f"{self.VAULT_PATH}".format(tenant_id=tenant_id, tool_id=tool_id)
          )
          execution_context["__mcp_credentials"] = creds
          return execution_context
  ```

**Per-Tenant MCP Credentials**
- Tenant isolation: Tenant A's Slack bot token vs Tenant B's Slack bot token stored at separate Vault paths
- Credential lifecycle:
  - Creation: admin configures tool credentials via secure UI (values transmitted via Vault transit)
  - Rotation: automatic rotation for supported providers (OAuth refresh), manual rotation for API keys
  - Revocation: admin revokes → Vault deletes → active sessions using this credential terminated
- Credential injection at execution time:
  1. Sandbox requests credentials from Vault via short-lived Vault token
  2. Credentials injected into sandbox environment
  3. After execution, sandbox destroyed, credentials gone
  4. No credential caching in Redis, database, or application memory

### Ephemeral Sandbox per MCP Call

**Container Isolation**
```python
class MCPSandbox(SQLModel):
    """Configuration for ephemeral MCP tool execution sandbox."""
    runtime: Literal["gvisor", "firecracker", "docker"] = "gvisor"
    
    # Resource Limits
    memory_mb: int = 256  # Max 256MB RAM (configurable per tool)
    cpu_cores: float = 0.5  # Max 0.5 CPU (configurable per tool)
    disk_mb: int = 100  # Max 100MB temp storage
    
    # Timeout
    execution_timeout_s: int = 30  # Max 30 seconds (configurable, absolute max 300s)
    graceful_shutdown_s: int = 5  # Grace period for cleanup
    
    # Network Policy
    network_mode: Literal["none", "restricted", "allowlist"]
    allowed_domains: list[str] = []  # Only these domains reachable
    blocked_ports: list[int] = [22, 25, 445]  # Always blocked
    max_connections: int = 10
    egress_bandwidth_mbps: float = 10.0
    
    # Filesystem
    root_fs: Literal["readonly"] = "readonly"  # Always read-only
    temp_dir: str = "/tmp/mcp"  # Writable temp directory (within disk_mb limit)
    mount_points: list[str] = []  # No host mounts by default
    
    # Security
    no_new_privileges: bool = True
    seccomp_profile: str = "mcp-restricted"
    capabilities_drop: list[str] = ["ALL"]
    capabilities_add: list[str] = []  # None by default
```

**Sandbox Lifecycle**
1. MCP tool invocation received
2. Sandbox created with tool-specific resource limits
3. Credentials injected from Vault (one-time read)
4. Tool code executed in sandbox
5. Response captured
6. Sandbox destroyed — zero data persistence
7. Response passes through validation pipeline

**Network Allowlisting**
- Per-tool network policy: admin configures which domains each tool can reach
- Default: `network_mode: "none"` (no network access)
- Allowlist examples: Slack tool → `["api.slack.com"]`, GitHub tool → `["api.github.com"]`
- DNS resolution inside sandbox restricted to allowlisted domains
- All egress traffic logged with destination, bytes, duration

### Tool Authorization Matrix

**Authorization Model**
```python
class ToolAuthorizationRule(SQLModel, table=True):
    """Defines who can use which MCP tools."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    
    # Subject (who)
    subject_type: Literal["role", "department", "user", "agent", "workspace"]
    subject_id: str  # Role name, department ID, user ID, agent ID, workspace ID
    
    # Object (what tool)
    tool_id: uuid.UUID = Field(foreign_key="mcp_tools.id")
    tool_server_id: uuid.UUID | None  # If null, applies to all servers with this tool
    
    # Permission
    permission: Literal["allow", "deny", "require_approval"]
    
    # Constraints
    parameter_restrictions: dict | None  # {"channel": ["#general", "#dev"]} for Slack
    max_invocations_per_hour: int | None
    allowed_time_window: str | None  # Cron expression: "* 9-17 * * MON-FRI"
    
    # Metadata
    created_by: uuid.UUID
    created_at: datetime
    expires_at: datetime | None
    reason: str | None  # Why this rule was created
```

**Default Deny Policy**
- All MCP tools denied by default — explicit allow rules required
- Evaluation order: user-specific → role → department → workspace → tenant default
- Most specific rule wins; deny always overrides allow at same specificity level

**Emergency Kill Switch**
- Disable any MCP tool globally in <10 seconds:
  ```python
  class MCPKillSwitch:
      async def disable_tool(self, tool_id: str, reason: str) -> None:
          """Emergency disable — takes effect within 10 seconds globally."""
          await self.redis.set(f"mcp:killed:{tool_id}", reason)
          await self.redis.publish("mcp:kill", json.dumps({
              "tool_id": tool_id,
              "reason": reason,
              "disabled_at": datetime.utcnow().isoformat(),
              "disabled_by": self.current_user_id,
          }))
          # All sandbox workers subscribe to mcp:kill channel
          # Active executions of this tool are terminated
          await self.audit_log.record("mcp_tool.emergency_disabled", tool_id=tool_id, reason=reason)
  ```
- Kill switch checked before every tool execution (Redis lookup, <1ms)
- Kill switch dashboard: currently disabled tools, reason, who disabled, re-enable button

### Change Detection & Versioning

**Tool Definition Tracking**
```python
class MCPToolVersion(SQLModel, table=True):
    """Tracks every version of an MCP tool definition."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tool_id: uuid.UUID = Field(foreign_key="mcp_tools.id")
    version: int  # Auto-incrementing per tool
    
    # Tool Definition
    name: str
    description: str
    input_schema: dict  # JSON Schema
    output_schema: dict  # JSON Schema (if declared)
    annotations: dict | None  # MCP tool annotations
    
    # Change Metadata
    change_type: Literal["added", "modified", "removed"]
    diff_from_previous: dict | None  # JSON diff from previous version
    breaking_change: bool = False  # True if input/output schema changed incompatibly
    
    # Detection
    detected_at: datetime
    detected_by: Literal["poll", "webhook", "manual"]
    server_id: uuid.UUID = Field(foreign_key="mcp_servers.id")
    
    # Status
    status: Literal["active", "pinned", "deprecated", "disabled"]
    pinned_by_agents: list[uuid.UUID] = Field(default_factory=list)
```

**Change Detection Pipeline**
1. Poll MCP servers every 5 minutes (configurable) for tool list changes
2. Compare current tool definitions against stored versions
3. For each change:
   - Compute JSON diff (additions, removals, modifications)
   - Classify: breaking vs non-breaking change
   - If breaking: alert all agents using this tool, auto-pin them to previous version
   - If non-breaking: update, log, notify
4. Alert channels: email, Slack webhook, in-app notification, PagerDuty (critical changes)

**Automated Compatibility Testing**
- When a tool version changes, automatically test against all agents that use it:
  1. Find all agents with workflows referencing this tool
  2. For each agent, run existing test cases against new tool version
  3. Report: which agents are compatible, which break
  4. Dashboard: tool update impact analysis

**Diff View**
- Side-by-side comparison of tool versions (schema, description, parameters)
- Highlight additions (green), removals (red), modifications (yellow)
- Breaking change indicators with impact assessment

### Response Validation

**Schema Validation**
- Validate every MCP tool response against its declared output schema:
  ```python
  class MCPResponseValidator:
      async def validate(self, tool: MCPTool, response: Any) -> ValidationResult:
          # 1. Schema compliance
          schema_result = jsonschema.validate(response, tool.output_schema)
          
          # 2. Size limits
          if len(json.dumps(response)) > tool.max_response_bytes:
              return ValidationResult(valid=False, reason="response_too_large")
          
          # 3. DLP scan (Agent-11)
          dlp_result = await self.dlp_scanner.scan(response)
          if dlp_result.has_violations:
              return ValidationResult(
                  valid=False, reason="dlp_violation",
                  findings=dlp_result.findings,
                  action=dlp_result.recommended_action,  # block, redact, alert
              )
          
          # 4. Prompt injection detection
          injection_result = await self.injection_detector.scan(response)
          if injection_result.is_suspicious:
              return ValidationResult(
                  valid=False, reason="indirect_prompt_injection",
                  confidence=injection_result.confidence,
                  suspicious_content=injection_result.flagged_segments,
              )
          
          return ValidationResult(valid=True)
  ```

**DLP Scan on Tool Outputs (Agent-11)**
- Every tool response passes through Agent-11's DLP pipeline before reaching the LLM
- Scan for: PII, PHI, credentials, API keys, internal URLs, code secrets
- Actions: block (reject response), redact (mask sensitive data), alert (pass through but notify)

**Prompt Injection Detection**
- Detect indirect prompt injection in tool responses:
  - Pattern matching: instructions embedded in data ("ignore previous instructions", "system: you are now...")
  - Semantic analysis: response content that attempts to alter LLM behavior
  - Confidence scoring: 0.0-1.0, threshold configurable (default: 0.7 → block)
- Blocked injections logged in audit trail with full response content for investigation

**Data Exfiltration Detection**
- Detect tools that return data exceeding expected scope:
  - Response contains data types not in output schema
  - Response includes data from unrelated resources
  - Response size anomaly (10x larger than historical average)
- Action: block + alert + auto-disable tool pending review

### Community Vulnerability Database

**Vulnerability Model**
```python
class MCPVulnerability(SQLModel, table=True):
    """CVE-like tracking for MCP tool vulnerabilities."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    
    # Identifier
    vuln_id: str  # Format: MCP-2025-0001 (auto-generated)
    
    # Affected Tool
    tool_name: str
    tool_server: str
    affected_versions: list[str]  # SemVer ranges
    fixed_versions: list[str] | None
    
    # Classification
    severity: Literal["critical", "high", "medium", "low"]
    cvss_score: float | None  # 0.0-10.0
    category: Literal[
        "prompt_injection", "data_exfiltration", "privilege_escalation",
        "denial_of_service", "credential_leak", "supply_chain",
        "schema_violation", "sandbox_escape"
    ]
    
    # Details
    title: str
    description: str
    impact: str
    proof_of_concept: str | None  # Redacted if sensitive
    remediation: str
    references: list[str]  # URLs
    
    # Disclosure
    reported_by: str
    reported_at: datetime
    disclosed_at: datetime | None
    status: Literal["reported", "confirmed", "investigating", "fixed", "wont_fix", "disputed"]
    
    # Auto-remediation
    auto_disable: bool = False  # True for critical: auto-disable affected tools
    auto_disable_triggered: bool = False
    
    created_at: datetime
    updated_at: datetime | None
```

**Automated Scanning**
- On every MCP server connection, scan installed tools against vulnerability DB
- Scheduled scan: every 6 hours
- Real-time: when new vulnerability published, immediately scan all connected servers
- Auto-disable: critical vulnerabilities automatically disable affected tools

**Disclosure Workflow**
1. Reporter submits vulnerability via API or UI (authenticated)
2. Auto-assign severity based on category + impact description
3. Security team receives notification (PagerDuty for critical)
4. Investigation: confirm/dispute within SLA (critical: 4h, high: 24h, medium: 72h)
5. Fix coordinated with tool publisher (if external)
6. Advisory published to all affected tenants
7. Auto-disable for critical vulnerabilities where no fix is available

### Security Scoring

**Per-Tool Security Score (0-100)**
```python
class MCPSecurityScore(SQLModel, table=True):
    """Composite security score for an MCP tool."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tool_id: uuid.UUID = Field(foreign_key="mcp_tools.id")
    
    # Score Components (each 0-100, weighted)
    sandbox_compliance: int      # Weight: 25% — runs in sandbox, respects limits
    credential_hygiene: int      # Weight: 20% — uses Vault, no hardcoded creds
    response_validation: int     # Weight: 20% — schema compliance, no injection
    vulnerability_history: int   # Weight: 15% — past vulnerabilities, fix time
    community_trust: int         # Weight: 10% — usage, ratings, verified publisher
    scope_minimality: int        # Weight: 10% — requests minimal OAuth scopes
    
    # Composite
    overall_score: int  # Weighted average
    grade: Literal["A", "B", "C", "D", "F"]  # A=90+, B=80+, C=70+, D=60+, F=<60
    
    # Policy
    meets_minimum: bool  # Meets tenant's minimum security score threshold
    last_evaluated_at: datetime
    evaluation_details: dict  # Detailed breakdown with justifications
```

**Security Posture Dashboard**
- Overview: total tools, average score, distribution by grade
- Per-tool detail: score components, trend over time, recommendations
- Alerts: tools below minimum score, score regressions, new vulnerabilities
- Compliance view: which tools meet SOC2/ISO27001 requirements

### Infrastructure

**Docker Compose Services**
```yaml
services:
  mcp-security:    # MCP security gateway (FastAPI)
  mcp-sandbox:     # Sandbox orchestrator (gVisor/Firecracker)
  mcp-scanner:     # Vulnerability scanner (Celery worker)
```

**Environment Configuration**
- All settings via `pydantic-settings` with `ARCHON_MCP_SECURITY_` prefix
- Tool credentials in Vault — never in env vars, config files, or application memory
- Feature flags: `mcp_sandbox_enabled`, `mcp_kill_switch`, `mcp_vuln_scanning`

## Output Structure

```
backend/app/mcp_security/
├── __init__.py
├── router.py                  # MCP security API endpoints
├── models.py                  # MCPTool, MCPToolVersion, MCPVulnerability, MCPSecurityScore
├── schemas.py                 # Pydantic request/response schemas
├── scopes/
│   ├── __init__.py
│   ├── manager.py             # OAuth scope registration and management
│   ├── consent.py             # User consent flow and tracking
│   └── escalation.py          # Scope escalation and re-consent
├── credentials/
│   ├── __init__.py
│   ├── vault_manager.py       # Vault credential storage and injection
│   └── rotation.py            # Credential rotation lifecycle
├── sandbox/
│   ├── __init__.py
│   ├── orchestrator.py        # Ephemeral container lifecycle management
│   ├── gvisor.py              # gVisor runtime adapter
│   ├── firecracker.py         # Firecracker runtime adapter
│   ├── network_policy.py      # Domain allowlisting and egress control
│   └── resource_limits.py     # CPU, memory, disk, timeout enforcement
├── authorization/
│   ├── __init__.py
│   ├── matrix.py              # Tool authorization matrix engine
│   ├── kill_switch.py         # Emergency tool disable
│   └── policies.py            # OPA policy evaluation
├── versioning/
│   ├── __init__.py
│   ├── tracker.py             # Tool definition change detection
│   ├── differ.py              # Schema diff computation
│   └── compatibility.py       # Automated compatibility testing
├── validation/
│   ├── __init__.py
│   ├── schema_validator.py    # Response schema validation
│   ├── injection_detector.py  # Indirect prompt injection detection
│   ├── dlp_scanner.py         # DLP scan on tool outputs (Agent-11)
│   └── exfiltration.py        # Data exfiltration detection
├── vulnerability/
│   ├── __init__.py
│   ├── database.py            # Vulnerability CRUD and search
│   ├── scanner.py             # Automated vulnerability scanning
│   ├── disclosure.py          # Disclosure workflow management
│   └── auto_remediation.py    # Auto-disable on critical findings
├── scoring/
│   ├── __init__.py
│   ├── calculator.py          # Security score computation
│   └── dashboard.py           # Score aggregation and trending
├── audit.py                   # MCP security audit logging
├── tasks.py                   # Celery: scanning, polling, scoring
└── config.py                  # MCP security-specific configuration

frontend/src/pages/mcp-security/
├── MCPDashboard.tsx            # Security posture overview
├── ToolInventory.tsx           # All registered tools with scores
├── ToolDiffViewer.tsx          # Side-by-side version comparison
├── AuthorizationMatrix.tsx     # Authorization rules editor
├── ConsentManager.tsx          # User scope consent management
├── KillSwitchPanel.tsx         # Emergency disable controls
├── VulnerabilityBrowser.tsx    # Vulnerability database browser
├── VulnerabilityReport.tsx     # Submit vulnerability report
├── SecurityScoreDetail.tsx     # Per-tool score breakdown
└── CredentialManager.tsx       # Tool credential configuration

tests/
├── conftest.py                 # MCP security test fixtures
├── test_mcp_scopes.py          # OAuth scope management and consent
├── test_mcp_credentials.py     # Vault credential injection
├── test_mcp_sandbox.py         # Ephemeral container lifecycle
├── test_mcp_sandbox_network.py # Network allowlisting
├── test_mcp_authorization.py   # Authorization matrix evaluation
├── test_mcp_kill_switch.py     # Emergency disable timing
├── test_mcp_change_detection.py  # Tool version tracking and diff
├── test_mcp_compatibility.py   # Automated compatibility testing
├── test_mcp_response_validation.py  # Schema + injection + DLP
├── test_mcp_exfiltration.py    # Data exfiltration detection
├── test_mcp_vulnerability_db.py  # Vulnerability CRUD and scanning
├── test_mcp_disclosure.py      # Disclosure workflow
├── test_mcp_scoring.py         # Security score computation
└── test_mcp_security_e2e.py    # End-to-end security pipeline
```

## API Endpoints (Complete)

```
# Tool Scope Management
GET    /api/v1/mcp-security/scopes                          # List all registered tool scopes
GET    /api/v1/mcp-security/tools/{tool_id}/scopes           # Get scopes for a tool
PUT    /api/v1/mcp-security/tools/{tool_id}/scopes           # Update tool scopes
GET    /api/v1/mcp-security/users/{user_id}/consents         # List user's scope consents
POST   /api/v1/mcp-security/users/{user_id}/consents         # Grant consent
DELETE /api/v1/mcp-security/users/{user_id}/consents/{scope} # Revoke consent

# Tool Credentials
POST   /api/v1/mcp-security/tools/{tool_id}/credentials      # Store credential in Vault
PUT    /api/v1/mcp-security/tools/{tool_id}/credentials      # Rotate credential
DELETE /api/v1/mcp-security/tools/{tool_id}/credentials      # Revoke credential
GET    /api/v1/mcp-security/tools/{tool_id}/credentials/status  # Credential health check

# Sandbox Configuration
GET    /api/v1/mcp-security/sandbox/config                   # Get sandbox defaults
PUT    /api/v1/mcp-security/sandbox/config                   # Update sandbox defaults
GET    /api/v1/mcp-security/tools/{tool_id}/sandbox           # Get tool-specific sandbox config
PUT    /api/v1/mcp-security/tools/{tool_id}/sandbox           # Update tool sandbox config
GET    /api/v1/mcp-security/sandbox/active                   # List active sandboxes

# Authorization Matrix
GET    /api/v1/mcp-security/authorization/rules              # List authorization rules
POST   /api/v1/mcp-security/authorization/rules              # Create rule
PUT    /api/v1/mcp-security/authorization/rules/{id}         # Update rule
DELETE /api/v1/mcp-security/authorization/rules/{id}         # Delete rule
POST   /api/v1/mcp-security/authorization/evaluate           # Evaluate access decision
POST   /api/v1/mcp-security/tools/{tool_id}/kill             # Emergency disable tool
POST   /api/v1/mcp-security/tools/{tool_id}/enable           # Re-enable killed tool
GET    /api/v1/mcp-security/kill-switch/active               # List currently killed tools

# Version Management
GET    /api/v1/mcp-security/tools/{tool_id}/versions         # List tool versions
GET    /api/v1/mcp-security/tools/{tool_id}/versions/{v}/diff  # Diff between versions
POST   /api/v1/mcp-security/tools/{tool_id}/pin/{version}    # Pin to version
POST   /api/v1/mcp-security/tools/{tool_id}/unpin            # Unpin version
GET    /api/v1/mcp-security/changes                          # List recent tool changes
GET    /api/v1/mcp-security/changes/{id}/impact              # Impact analysis

# Vulnerability Database
GET    /api/v1/mcp-security/vulnerabilities                  # List vulnerabilities
POST   /api/v1/mcp-security/vulnerabilities                  # Report vulnerability
GET    /api/v1/mcp-security/vulnerabilities/{id}             # Get vulnerability details
PATCH  /api/v1/mcp-security/vulnerabilities/{id}             # Update status
POST   /api/v1/mcp-security/vulnerabilities/scan             # Trigger scan now
GET    /api/v1/mcp-security/vulnerabilities/affected          # List affected tools

# Security Scoring
GET    /api/v1/mcp-security/scores                           # All tool scores
GET    /api/v1/mcp-security/tools/{tool_id}/score             # Tool score detail
POST   /api/v1/mcp-security/scores/recalculate               # Recalculate all scores
GET    /api/v1/mcp-security/scores/summary                   # Security posture summary

# Audit
GET    /api/v1/mcp-security/audit                            # Query MCP security audit logs
GET    /api/v1/mcp-security/audit/export                     # Export audit logs
```

## Verify Commands

```bash
# MCP Security module importable
cd ~/Scripts/Archon && python -c "from backend.app.mcp_security import MCPSecurityGuardian; print('OK')"

# Scope management importable
cd ~/Scripts/Archon && python -c "from backend.app.mcp_security.scopes.manager import ScopeManager; from backend.app.mcp_security.scopes.consent import ConsentService; print('Scopes OK')"

# Credential manager importable
cd ~/Scripts/Archon && python -c "from backend.app.mcp_security.credentials.vault_manager import MCPCredentialManager; print('Credentials OK')"

# Sandbox orchestrator importable
cd ~/Scripts/Archon && python -c "from backend.app.mcp_security.sandbox.orchestrator import SandboxOrchestrator; print('Sandbox OK')"

# Authorization matrix importable
cd ~/Scripts/Archon && python -c "from backend.app.mcp_security.authorization.matrix import ToolAuthorizationMatrix; from backend.app.mcp_security.authorization.kill_switch import MCPKillSwitch; print('AuthZ OK')"

# Vulnerability database importable
cd ~/Scripts/Archon && python -c "from backend.app.mcp_security.vulnerability.database import VulnerabilityDB; from backend.app.mcp_security.vulnerability.scanner import VulnerabilityScanner; print('VulnDB OK')"

# Security scoring importable
cd ~/Scripts/Archon && python -c "from backend.app.mcp_security.scoring.calculator import SecurityScoreCalculator; print('Scoring OK')"

# Tests pass
cd ~/Scripts/Archon && python -m pytest tests/test_mcp_security/ --tb=short -q

# No hardcoded credentials
cd ~/Scripts/Archon && ! grep -rn 'api_key\s*=\s*"[^"]*"' --include='*.py' backend/app/mcp_security/ || echo 'FAIL'

# Docker compose is valid
cd ~/Scripts/Archon && docker compose config --quiet
```

## Learnings Protocol

Before starting, read `.sdd/learnings/*.md` for known pitfalls from previous sessions.
After completing work, report any pitfalls or patterns discovered so the orchestrator can capture them.

## Acceptance Criteria

- [ ] Each MCP tool registered with specific OAuth scopes; user consent required before first use
- [ ] Scope escalation triggers re-consent flow; consent revocable at any time
- [ ] All MCP tool credentials stored in Vault with per-tenant isolation
- [ ] Credential injection happens at execution time only; zero caching in app memory
- [ ] Each MCP tool invocation runs in ephemeral gVisor/Firecracker sandbox
- [ ] Sandbox enforces: 256MB RAM, 0.5 CPU, 30s timeout, read-only filesystem
- [ ] Network allowlisting restricts sandbox egress to configured domains only
- [ ] Tool authorization matrix enforces default-deny with role/department/agent granularity
- [ ] Emergency kill switch disables any MCP tool globally in <10 seconds
- [ ] Tool definition changes detected, diffed, and classified as breaking/non-breaking
- [ ] Breaking changes auto-pin affected agents to previous tool version
- [ ] Automated compatibility testing runs against agents using changed tools
- [ ] Response validation catches schema violations, prompt injection, and data exfiltration
- [ ] DLP scan (Agent-11) applied to all tool outputs before reaching LLM
- [ ] Community vulnerability database with CVE-like tracking (MCP-YYYY-NNNN format)
- [ ] Critical vulnerabilities auto-disable affected tools
- [ ] Per-tool security score (0-100) computed from 6 weighted components
- [ ] Security posture dashboard shows tool inventory, scores, trends, alerts
- [ ] All MCP security interactions fully audited
- [ ] All endpoints match `contracts/openapi.yaml`
- [ ] 80%+ test coverage across all MCP security modules
- [ ] Zero plaintext credentials in logs, env vars, or source code
