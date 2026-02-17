# Agent-12: Governance, Compliance, Risk Management & Identity Governance

> **Phase**: 3 | **Dependencies**: Agent-01 (Core Backend), Agent-02 (Frontend), Agent-00 (Secrets Vault) | **Priority**: HIGH
> **Enterprise customers will not adopt without governance, compliance, and audit capabilities. This is the trust layer.**

---

## Identity

You are Agent-12: the Governance, Compliance & Risk Management Architect. You provide complete organizational visibility into AI usage, enforce compliance frameworks, manage identity governance with access reviews and privileged access management, and deliver executive-ready reporting. You build the trust infrastructure that enables enterprise adoption.

## Mission

Build a production-grade governance platform that:
1. Implements identity governance with periodic access reviews, just-in-time privilege elevation, and separation of duties
2. Provides a central agent registry with multi-stage approval workflows and lifecycle management
3. Tracks compliance across SOC2 Type II, GDPR, HIPAA, PCI-DSS, FedRAMP, ISO 27001, and NIST AI RMF
4. Computes per-agent risk scores (0-100) with automated mitigation recommendations
5. Visualizes data lineage, model lineage, and user-agent relationships via Neo4j graph database
6. Provides OPA policy management with editor, linting, dry-run testing, and conflict detection
7. Delivers a tamper-proof audit log viewer with advanced search, hash-chain verification, and cross-agent correlation
8. Generates executive-ready reports (PDF) with scheduled delivery for board-level governance reviews

## Requirements

### Identity Governance

**Periodic User Access Reviews**
- Quarterly access reviews (configurable cadence: monthly, quarterly, semi-annual, annual):
  ```python
  class AccessReview(SQLModel, table=True):
      """Periodic review of user access levels by their managers."""
      id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
      review_cycle: str  # "2025-Q1", "2025-Q2"
      status: Literal["pending", "in_progress", "completed", "overdue"]
      reviewer_id: uuid.UUID = Field(foreign_key="users.id")  # Manager
      reviewee_id: uuid.UUID = Field(foreign_key="users.id")  # Direct report
      tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
      roles_reviewed: list[dict]  # [{role_id, role_name, decision, justification}]
      agents_reviewed: list[dict]  # [{agent_id, access_level, decision}]
      decision: Literal["approve_all", "modify", "revoke_all"] | None
      justification: str | None
      completed_at: datetime | None
      due_date: datetime
      created_at: datetime
  ```
- Manager review workflow: managers receive list of their reports' access levels → approve/modify/revoke per role and per agent
- Automatic notification: email + in-app reminders at 30d, 14d, 7d, 1d before due date
- Escalation: overdue reviews escalated to tenant admin, then platform admin
- Compliance evidence: completed reviews stored as SOC2/HIPAA audit evidence

**Automatic Access Revocation for Inactive Users**
- Inactivity detection: no login, no API call, no execution trigger for configurable period (default: 90 days)
  ```python
  class InactivityPolicy(BaseModel):
      warning_threshold_days: int = 60   # Send warning at 60 days
      suspension_threshold_days: int = 90  # Suspend at 90 days
      deactivation_threshold_days: int = 180  # Deactivate at 180 days
      exclude_service_accounts: bool = True
      exclude_roles: list[str] = ["platform_admin"]
  ```
- Graduated enforcement: warning email → account suspension → account deactivation
- Reactivation: suspended users can self-reactivate via SSO; deactivated users require admin action
- Audit trail: every status change logged with reason and policy reference

**Privileged Access Management (PAM)**
- Just-in-time (JIT) privilege elevation:
  ```python
  class PrivilegeElevation(SQLModel, table=True):
      """Time-limited privilege grants with approval workflow."""
      id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
      requestor_id: uuid.UUID = Field(foreign_key="users.id")
      target_role: str  # Role being requested
      justification: str
      ticket_reference: str | None  # JIRA/ServiceNow ticket
      status: Literal["pending", "approved", "denied", "active", "expired", "revoked"]
      approved_by: uuid.UUID | None = Field(foreign_key="users.id")
      approved_at: datetime | None
      grant_start: datetime | None
      grant_end: datetime | None  # Automatic expiry
      duration_minutes: int = 60  # Default: 1 hour
      max_duration_minutes: int = 480  # Max: 8 hours
      auto_revoke: bool = True  # Automatically revoke at expiry
      extensions: int = 0  # Number of times extended
      max_extensions: int = 2
      tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
      created_at: datetime
  ```
- Time-limited grants: default 1 hour, max 8 hours, configurable per role
- Approval required: requests go to designated approver (role-based or specific users)
- Automatic revocation at expiry (no permanent privilege accumulation)
- Extension workflow: user can request extension (max 2 extensions) with re-approval
- Break-glass: emergency elevation without approval, but with mandatory post-incident review

**Separation of Duties (SoD)**
- Configurable SoD rules:
  ```python
  class SeparationOfDutyRule(SQLModel, table=True):
      id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
      name: str  # "agent_create_approve_separation"
      description: str
      conflicting_actions: list[list[str]]  # [["agent.create", "agent.approve"]]
      scope: Literal["user", "role"]  # Apply to same user or same role
      enforcement: Literal["prevent", "alert"]  # Hard block or soft alert
      tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
      enabled: bool = True
      created_at: datetime
  ```
- Built-in rules:
  - Same user cannot create AND approve an agent
  - Same user cannot create AND deploy an agent
  - Same user cannot manage secrets AND deploy agents
  - Same user cannot be both red-team operator AND agent developer
- Enforcement modes: `prevent` (hard block) or `alert` (allow but notify security team)
- SoD violation reporting: dashboard showing all violations with user, actions, and timestamps

**Orphaned Account Detection**
- Detect accounts where the user has left the organization but the account remains active:
  - Cross-reference with SCIM provisioning status (Agent-01)
  - Cross-reference with HR system via connector (if configured)
  - Flag accounts with no IdP linkage (not federated via SAML/OIDC)
  - Flag accounts where IdP reports user as deactivated but local account is still active
- Automated remediation: suspend orphaned accounts, notify tenant admin for confirmation
- Monthly orphaned account reports included in governance dashboard

### Agent Registry with Approval Workflows

**Central Agent Catalog**
```python
class AgentRegistryEntry(SQLModel, table=True):
    """Central catalog of all agents with governance metadata."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    agent_id: uuid.UUID = Field(foreign_key="agents.id", unique=True)
    display_name: str
    description: str
    owner_id: uuid.UUID = Field(foreign_key="users.id")
    department: str
    business_justification: str
    models_used: list[str]  # ["gpt-4o", "claude-3.5-sonnet"]
    data_sources_accessed: list[str]  # ["customer_db", "salesforce", "confluence"]
    data_classification: Literal["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"]
    estimated_monthly_cost: float
    actual_monthly_cost: float | None
    risk_score: float  # 0-100, computed by risk engine
    risk_factors: dict  # Breakdown of risk score components
    compliance_tags: list[str]  # ["SOC2", "HIPAA", "GDPR"]
    approval_status: Literal["draft", "submitted", "dev_review", "security_review", "compliance_review", "approved", "rejected", "published", "deprecated", "archived"]
    approval_history: list[dict]  # [{stage, reviewer, decision, timestamp, comments}]
    sunset_date: datetime | None
    last_execution: datetime | None
    execution_count_30d: int = 0
    error_rate_30d: float = 0.0
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    created_at: datetime
    updated_at: datetime | None
```

**Multi-Stage Approval Workflow**
- Approval pipeline:
  1. **Developer submits** → status: `submitted`
  2. **Team Lead review** → technical review, code quality, business justification → `dev_review`
  3. **Security review** → red-team results (Agent-10), DLP policy coverage (Agent-11), secret handling → `security_review`
  4. **Compliance sign-off** → data classification verified, compliance framework alignment, risk score acceptable → `compliance_review`
  5. **Published** → agent available for use → `published`
- Expedited path for low-risk agents:
  - Risk score < 20 AND data classification = PUBLIC → skip security + compliance review
  - Auto-approved with audit trail noting expedited path
- SLA tracking for approvals:
  ```python
  class ApprovalSLA(BaseModel):
      dev_review_hours: int = 24
      security_review_hours: int = 48
      compliance_review_hours: int = 72
      total_sla_hours: int = 168  # 7 days end-to-end
  ```
- Escalation: overdue approvals escalated after SLA breach
- Rejection workflow: reviewer provides feedback → developer revises → resubmit

**Agent Lifecycle Management**
- Deprecation workflow: owner sets sunset date → users notified → access restricted → archived
- Periodic recertification: agents recertified annually (data access, cost justification, risk re-assessment)
- Agent search and filtering: by owner, department, risk score, compliance status, model used, data classification

### Compliance Frameworks

**SOC2 Type II (All 5 Trust Service Criteria)**
```python
class SOC2Compliance(BaseModel):
    """SOC2 compliance tracker across all 5 trust service criteria."""
    security: SOC2Category  # CC1-CC9: Security controls
    availability: SOC2Category  # A1: Availability controls
    processing_integrity: SOC2Category  # PI1: Processing integrity
    confidentiality: SOC2Category  # C1: Confidentiality controls
    privacy: SOC2Category  # P1-P8: Privacy controls

class SOC2Category(BaseModel):
    criteria: list[SOC2Criterion]
    overall_score: float  # 0-100
    gaps: list[ComplianceGap]
    evidence: list[ComplianceEvidence]
    last_assessed: datetime
```
- Per-criterion tracking: CC1.1 through CC9.9 with evidence linking
- Control mapping: map Archon platform capabilities to SOC2 controls
- Evidence automation: audit logs, access reviews, encryption status, incident responses auto-linked
- Gap analysis with prioritized remediation recommendations

**GDPR**
- Data mapping: catalog all personal data processed by each agent (data subject category, data types, processing basis)
- Consent management: track consent grants/revocations per data subject per processing purpose
- Data Subject Access Request (DSAR) automation:
  ```python
  class DSARRequest(SQLModel, table=True):
      id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
      request_type: Literal["access", "rectification", "erasure", "portability", "restriction", "objection"]
      data_subject_email: str
      status: Literal["received", "identity_verified", "in_progress", "completed", "denied"]
      identity_verified: bool = False
      verification_method: str | None
      data_collected: dict | None  # All data found for this subject
      response_sent: bool = False
      response_deadline: datetime  # 30 days from receipt
      completed_at: datetime | None
      denial_reason: str | None
      tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
      created_at: datetime
  ```
- DPO (Data Protection Officer) tools: dashboard, incident notification workflow, DPIA templates
- Cross-border transfer tracking: identify when agent data flows cross geographic boundaries
- Right to erasure: automated data deletion across all agent storage, with verification

**HIPAA**
- PHI handling verification: ensure agents with healthcare data have proper controls
- Business Associate Agreement (BAA) tracking: which agents require BAAs, status of each
- Encryption verification: data at rest (AES-256) and in transit (TLS 1.3) for all PHI
- Access logging: all PHI access logged with user, timestamp, purpose, minimum necessary compliance
- HIPAA-specific audit report generation

**PCI-DSS**
- Cardholder data detection: verify no agents process/store cardholder data without PCI controls
- Network segmentation verification: ensure PCI-scoped agents are isolated
- Encryption at rest/transit verification
- Access control validation: role-based access to cardholder data environments

**FedRAMP (NIST 800-53)**
- NIST 800-53 control family tracking (AC, AU, CM, IA, SC, SI, etc.)
- Control implementation status: implemented, partially implemented, planned, not applicable
- POA&M (Plan of Action and Milestones) tracking

**ISO 27001 & NIST AI RMF**
- ISO 27001 Annex A control mapping
- NIST AI RMF function tracking: Govern, Map, Measure, Manage
- AI-specific risk categories: bias, fairness, transparency, accountability, reliability

### Risk Management

**Per-Agent Risk Scoring**
```python
class RiskAssessment(SQLModel, table=True):
    """Computed risk score for each agent based on multiple factors."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    agent_id: uuid.UUID = Field(foreign_key="agents.id")
    overall_score: float  # 0-100 (higher = more risk)
    factors: dict  # Breakdown:
    # {
    #   "data_sensitivity": 25,      # Based on data classification accessed
    #   "model_risk": 15,            # GPT-4 = higher risk than rules-based
    #   "execution_frequency": 10,   # High frequency = more exposure
    #   "error_rate": 20,            # High error rate = more risk
    #   "security_posture": 15,      # Red-team findings (Agent-10)
    #   "compliance_gaps": 15,       # Missing compliance controls
    # }
    risk_level: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    mitigations_applied: list[str]
    mitigations_recommended: list[str]
    trend: Literal["improving", "stable", "degrading"]
    previous_score: float | None
    assessed_at: datetime
    next_assessment: datetime
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
```

- Risk heat map: organization-wide view of all agents by risk level (color-coded grid)
- Risk trends over time: 30d, 90d, 365d trend lines per agent and across organization
- Automated mitigation recommendations:
  - HIGH data sensitivity + no DLP → "Enable DLP Layer 4 policy for this agent"
  - HIGH error rate → "Review agent configuration, enable output guardrails"
  - CRITICAL security posture → "Agent has unresolved Critical findings from red-team"
- Risk acceptance workflow: designated risk owner can accept risk with documented justification
- Risk reporting: monthly risk digest for tenant admins, quarterly for executive leadership

### Lineage & Visualization (Neo4j)

**Graph Data Model**
```cypher
// Data lineage: who accesses what data through which agents
(:User)-[:EXECUTES]->(:Agent)-[:READS_FROM]->(:DataSource)
(:Agent)-[:WRITES_TO]->(:DataSource)
(:Agent)-[:USES_MODEL]->(:LLMModel)
(:Agent)-[:DEPENDS_ON]->(:Agent)  // Sub-agent relationships

// Model lineage
(:LLMModel)-[:VERSION_OF]->(:ModelFamily)
(:LLMModel)-[:FINE_TUNED_FROM]->(:LLMModel)

// User-agent relationships
(:User)-[:OWNS]->(:Agent)
(:User)-[:APPROVED]->(:Agent)
(:User)-[:HAS_ACCESS]->(:Agent)
(:Department)-[:MANAGES]->(:Agent)

// Policy relationships
(:Policy)-[:APPLIES_TO]->(:Agent)
(:Policy)-[:ENFORCES]->(:ComplianceFramework)
```

**Impact Analysis**
- "If we change model X, which agents are affected?":
  ```python
  class ImpactAnalyzer:
      async def model_change_impact(self, model_id: str) -> ImpactReport:
          query = """
          MATCH (m:LLMModel {id: $model_id})<-[:USES_MODEL]-(a:Agent)
          OPTIONAL MATCH (a)<-[:EXECUTES]-(u:User)
          OPTIONAL MATCH (a)-[:READS_FROM]->(ds:DataSource)
          RETURN a, collect(distinct u) as users, collect(distinct ds) as data_sources
          """
          results = await self.neo4j.execute(query, {"model_id": model_id})
          return ImpactReport(
              affected_agents=results.agents,
              affected_users=results.users,
              affected_data_sources=results.data_sources,
              risk_assessment=await self.assess_change_risk(results),
          )

      async def data_source_change_impact(self, data_source_id: str) -> ImpactReport:
          """What happens if we modify or remove this data source?"""
          # ...

      async def user_departure_impact(self, user_id: str) -> ImpactReport:
          """What agents and data sources are affected if this user leaves?"""
          # ...
  ```

**Interactive Graph Explorer**
- React component with force-directed graph visualization (D3.js or Cytoscape.js)
- Node types: User, Agent, DataSource, LLMModel, Department, Policy
- Edge types: EXECUTES, READS_FROM, WRITES_TO, USES_MODEL, OWNS, APPROVED, APPLIES_TO
- Filters: by node type, department, risk level, compliance status
- Drill-down: click node to see details panel with metadata and relationships
- Export: graph as PNG/SVG, underlying data as JSON/CSV

### Policy Management

**OPA Policy Editor**
- Browser-based editor with:
  - Rego syntax highlighting and auto-completion
  - Inline linting and error detection
  - Real-time Rego validation against OPA compiler
  - Dry-run testing: test policy against sample inputs or historical data
  ```python
  class PolicyEditor:
      async def validate(self, rego_code: str) -> ValidationResult:
          """Validate Rego syntax and semantics."""
          result = await self.opa_client.compile(rego_code)
          return ValidationResult(
              valid=result.valid,
              errors=result.errors,
              warnings=result.warnings,
          )

      async def dry_run(self, rego_code: str, test_inputs: list[dict]) -> list[DryRunResult]:
          """Test policy against provided inputs."""
          return [await self.opa_client.evaluate(rego_code, inp) for inp in test_inputs]

      async def conflict_check(self, rego_code: str) -> list[PolicyConflict]:
          """Detect conflicts with existing active policies."""
          active_policies = await self.get_active_policies()
          conflicts = []
          for policy in active_policies:
              # Test same inputs against both policies, detect contradictions
              contradictions = await self.detect_contradictions(rego_code, policy.rego_code)
              if contradictions:
                  conflicts.append(PolicyConflict(
                      existing_policy=policy, contradictions=contradictions,
                  ))
          return conflicts
  ```

**Policy Templates**
- Pre-built templates for common governance scenarios:
  - "Restrict agent execution to business hours"
  - "Require approval for agents accessing RESTRICTED data"
  - "Limit execution cost per agent per day"
  - "Enforce minimum model version for compliance agents"
  - "Block agent creation without business justification"
- Templates parameterizable: fill in specifics (department, cost limit, time range)

**Policy Versioning & Rollback**
- Every policy change creates a new version (immutable history)
- Diff view between versions
- Instant rollback to any previous version with audit log entry
- Active version tracking: only one version active per policy at any time

**Policy Conflict Detection**
- Detect when new or modified policies contradict existing active policies
- Conflict report: which policies conflict, on what inputs, and recommended resolution
- Resolution strategies: priority ordering, scope narrowing, manual override

**Policy Effectiveness Metrics**
- Per-policy hit rate: how often triggered in last 7d, 30d, 90d
- False positive rate: alerts from this policy marked as false positive
- Coverage: what percentage of agents/users are covered by this policy
- Impact: what actions were taken (blocked, alerted, etc.) and their outcomes

### Audit Log Viewer

**Advanced Search & Filtering**
- Search dimensions:
  - User (actor), Agent (resource), Action type, Time range, Outcome (success/failure/denied)
  - Resource type (agent, user, secret, connector, policy, execution)
  - Risk score range
  - Correlation ID (trace across related events)
  - Free-text search across event details
- Saved searches: save and share commonly used filter combinations
- Real-time tail: live view of audit events as they occur

**Timeline View with Drill-Down**
- Chronological timeline with event markers
- Zoom: minute, hour, day, week, month granularity
- Drill-down: click event to see full details including related events
- Highlight: anomalous events flagged by risk engine

**Export & Retention**
- Export formats: CSV (for analysis), JSON (for processing), PDF (for compliance auditors)
- Retention policies: configurable per tenant (default: 7 years for compliance)
- Archival: older logs moved to cold storage (S3/GCS) with on-demand retrieval
- Retention policy enforcement: automatic archival and deletion per policy

**Tamper-Proof Verification**
- Hash chain verification (SHA-256, from Agent-01's AuditLog model):
  ```python
  class AuditIntegrityVerifier:
      async def verify_chain(self, start_id: uuid.UUID, end_id: uuid.UUID) -> VerificationResult:
          """Verify hash chain integrity between two audit entries."""
          entries = await self.get_entries_range(start_id, end_id)
          for i in range(1, len(entries)):
              expected_hash = self.compute_hash(entries[i-1])
              if entries[i].previous_hash != expected_hash:
                  return VerificationResult(
                      valid=False,
                      broken_at=entries[i].id,
                      expected_hash=expected_hash,
                      actual_hash=entries[i].previous_hash,
                  )
          return VerificationResult(valid=True, entries_verified=len(entries))
  ```
- Periodic automated integrity checks (hourly)
- Alert on any hash chain break (indicates tampering or data corruption)

**Cross-Agent Correlation**
- Link audit events across agents, users, and systems:
  - "Show me all actions by user X across all agents in the last 24 hours"
  - "Show me all events related to agent Y's deployment, including approval, red-team scan, and publish"
  - "Show me all failed access attempts correlated with this user's IP address"
- Correlation engine uses trace_id, user_id, agent_id, and temporal proximity

### Reports

**Executive AI Governance Report (PDF)**
- Auto-generated board-ready report including:
  - AI usage summary: agents deployed, executions, users, cost
  - Risk posture: risk heat map, trend, critical findings
  - Compliance status: per-framework scores with traffic-light indicators
  - Identity governance: access review completion, orphaned accounts, SoD violations
  - Security: red-team findings summary, credential leaks, DLP events
  - Recommendations: prioritized actions for leadership
- Generated via ReportLab or WeasyPrint

**Departmental Usage Report**
- Per-department breakdown: agents owned, executions, cost, data accessed, risk scores
- User activity: active users, agent creators, top executors

**Compliance Audit Report**
- Per-framework detailed report with control-by-control status
- Evidence linking: each control linked to supporting evidence (audit logs, configs, test results)
- Gap analysis with remediation plan

**Risk Assessment Report**
- Agent-by-agent risk breakdown
- Trend analysis: improving/degrading risk posture
- Mitigation effectiveness: which mitigations reduced risk scores

**Scheduled Delivery**
- Reports scheduled for automatic generation and delivery:
  - Executive report: monthly (1st business day)
  - Compliance report: quarterly
  - Risk report: weekly
  - Departmental report: monthly
- Delivery via email (PDF attachment) or dashboard download
- Recipients configurable per report type

## Core Data Models

```python
class GovernancePolicy(SQLModel, table=True):
    """OPA governance policy with version control."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str
    description: str
    category: str  # "access_control", "cost_management", "compliance", "agent_lifecycle"
    rego_code: str
    status: Literal["draft", "review", "active", "disabled", "archived"]
    version: int = 1
    previous_version_id: uuid.UUID | None
    scope_departments: list[str] | None
    scope_agent_ids: list[uuid.UUID] | None
    effectiveness_metrics: dict | None
    created_by: uuid.UUID = Field(foreign_key="users.id")
    approved_by: uuid.UUID | None
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    created_at: datetime
    updated_at: datetime | None

class ComplianceFrameworkStatus(SQLModel, table=True):
    """Compliance posture per framework per tenant."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    framework: str  # SOC2, GDPR, HIPAA, PCI_DSS, FEDRAMP, ISO27001, NIST_AI_RMF
    overall_score: float  # 0-100
    controls_total: int
    controls_implemented: int
    controls_partial: int
    controls_planned: int
    controls_not_applicable: int
    gaps: list[dict]  # [{control_id, description, remediation, priority}]
    evidence_links: list[dict]  # [{control_id, evidence_type, evidence_url}]
    last_assessed: datetime
    next_assessment: datetime
    assessed_by: uuid.UUID | None
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    created_at: datetime
    updated_at: datetime | None

class GovernanceReport(SQLModel, table=True):
    """Generated governance report with storage reference."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    report_type: Literal["executive", "departmental", "compliance", "risk"]
    format: Literal["pdf", "csv", "json"]
    file_url: str  # S3/MinIO storage URL
    file_size_bytes: int
    parameters: dict  # Report generation parameters (date range, department, etc.)
    generated_by: Literal["scheduled", "manual"]
    schedule_id: uuid.UUID | None
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    created_at: datetime
    expires_at: datetime | None  # Auto-delete after retention period
```

## Output Structure

```
backend/app/services/governance/
├── __init__.py
├── identity_governance.py       # Access reviews, PAM, SoD, orphaned accounts
├── agent_registry.py            # Agent catalog, approval workflows
├── compliance_engine.py         # Framework tracking, gap analysis
├── risk_engine.py               # Risk scoring, mitigation recommendations
├── lineage_service.py           # Neo4j lineage queries, impact analysis
├── policy_service.py            # OPA policy management, conflict detection
├── audit_viewer.py              # Audit log search, integrity verification
├── report_generator.py          # PDF/CSV/JSON report generation
└── scheduler.py                 # Scheduled report delivery

backend/app/routers/governance.py     # API endpoints
backend/app/models/governance.py      # SQLModel data models

frontend/src/components/governance/
├── GovernanceDashboard.tsx           # Main governance dashboard
├── IdentityGovernance/
│   ├── AccessReviewManager.tsx       # Access review interface
│   ├── PrivilegeElevation.tsx        # JIT elevation requests
│   ├── SeparationOfDuties.tsx        # SoD violation dashboard
│   └── OrphanedAccounts.tsx          # Orphaned account report
├── AgentRegistry/
│   ├── AgentCatalog.tsx              # Searchable agent catalog
│   ├── ApprovalWorkflow.tsx          # Multi-stage approval UI
│   └── AgentLifecycle.tsx            # Deprecation/recertification
├── Compliance/
│   ├── ComplianceDashboard.tsx       # Multi-framework overview
│   ├── FrameworkDetail.tsx           # Per-framework control view
│   ├── GapAnalysis.tsx               # Gap analysis with remediation
│   └── DSARManager.tsx               # GDPR DSAR workflow
├── Risk/
│   ├── RiskHeatMap.tsx               # Organization-wide risk view
│   ├── AgentRiskDetail.tsx           # Per-agent risk breakdown
│   └── RiskTrends.tsx                # Risk trend charts
├── Lineage/
│   ├── GraphExplorer.tsx             # Interactive Neo4j graph
│   ├── ImpactAnalysis.tsx            # Change impact analysis
│   └── LineageDetail.tsx             # Node detail panel
├── Policy/
│   ├── PolicyEditor.tsx              # Rego editor with linting
│   ├── PolicyTemplates.tsx           # Template library
│   ├── PolicyDryRun.tsx              # Dry-run testing UI
│   └── PolicyConflicts.tsx           # Conflict detection results
├── Audit/
│   ├── AuditLogViewer.tsx            # Advanced search/filter
│   ├── AuditTimeline.tsx             # Timeline view
│   ├── IntegrityVerifier.tsx         # Hash chain verification
│   └── AuditExport.tsx              # Export functionality
└── Reports/
    ├── ReportDashboard.tsx            # Report library
    ├── ReportScheduler.tsx            # Schedule configuration
    └── ReportViewer.tsx               # In-app report viewer

infra/neo4j/
├── docker-compose.neo4j.yml         # Neo4j service config
├── init-scripts/
│   ├── 001-constraints.cypher       # Node/relationship constraints
│   ├── 002-indexes.cypher           # Performance indexes
│   └── 003-seed-data.cypher         # Initial graph seed data
└── backup/
    └── backup.sh                    # Neo4j backup script

tests/test_governance/
├── conftest.py                      # Fixtures, factories
├── test_identity_governance.py      # Access reviews, PAM, SoD tests
├── test_agent_registry.py           # Registry, approval workflow tests
├── test_compliance.py               # Framework tracking tests
├── test_risk_engine.py              # Risk scoring tests
├── test_lineage.py                  # Neo4j lineage tests
├── test_policy_management.py        # Policy CRUD, conflict detection tests
├── test_audit_viewer.py             # Search, integrity verification tests
├── test_reports.py                  # Report generation tests
└── test_dsar.py                     # GDPR DSAR workflow tests
```

## API Endpoints (Complete)

```
# Identity Governance — Access Reviews
GET    /api/v1/governance/access-reviews                    # List access reviews
POST   /api/v1/governance/access-reviews                    # Create review cycle
GET    /api/v1/governance/access-reviews/{id}               # Get review details
PATCH  /api/v1/governance/access-reviews/{id}               # Submit review decision
GET    /api/v1/governance/access-reviews/my-reviews         # Reviews assigned to me

# Identity Governance — Privileged Access
POST   /api/v1/governance/privilege-elevations               # Request elevation
GET    /api/v1/governance/privilege-elevations               # List elevation requests
GET    /api/v1/governance/privilege-elevations/{id}          # Get elevation details
POST   /api/v1/governance/privilege-elevations/{id}/approve  # Approve elevation
POST   /api/v1/governance/privilege-elevations/{id}/deny     # Deny elevation
POST   /api/v1/governance/privilege-elevations/{id}/extend   # Extend active elevation
POST   /api/v1/governance/privilege-elevations/{id}/revoke   # Revoke active elevation

# Identity Governance — SoD & Orphaned Accounts
GET    /api/v1/governance/sod-rules                         # List SoD rules
POST   /api/v1/governance/sod-rules                         # Create SoD rule
PUT    /api/v1/governance/sod-rules/{id}                    # Update SoD rule
DELETE /api/v1/governance/sod-rules/{id}                    # Delete SoD rule
GET    /api/v1/governance/sod-violations                    # List SoD violations
GET    /api/v1/governance/orphaned-accounts                 # List orphaned accounts
POST   /api/v1/governance/orphaned-accounts/{id}/suspend    # Suspend orphaned account

# Identity Governance — Inactivity
GET    /api/v1/governance/inactive-users                    # List inactive users
GET    /api/v1/governance/inactivity-policy                 # Get inactivity policy
PUT    /api/v1/governance/inactivity-policy                 # Update inactivity policy

# Agent Registry
GET    /api/v1/governance/agents                            # List agent registry entries
GET    /api/v1/governance/agents/{id}                       # Get agent governance details
POST   /api/v1/governance/agents/{id}/submit                # Submit for approval
POST   /api/v1/governance/agents/{id}/review                # Submit review decision
POST   /api/v1/governance/agents/{id}/publish               # Publish approved agent
POST   /api/v1/governance/agents/{id}/deprecate             # Deprecate agent
POST   /api/v1/governance/agents/{id}/recertify             # Trigger recertification
GET    /api/v1/governance/agents/{id}/approval-history      # Get approval history

# Compliance
GET    /api/v1/governance/compliance                        # List all framework statuses
GET    /api/v1/governance/compliance/{framework}            # Get framework status
PUT    /api/v1/governance/compliance/{framework}             # Update framework assessment
GET    /api/v1/governance/compliance/{framework}/gaps       # Get compliance gaps
GET    /api/v1/governance/compliance/{framework}/evidence   # Get evidence links

# GDPR-specific
GET    /api/v1/governance/gdpr/data-map                    # Get data processing map
POST   /api/v1/governance/gdpr/dsar                        # Create DSAR request
GET    /api/v1/governance/gdpr/dsar                        # List DSAR requests
GET    /api/v1/governance/gdpr/dsar/{id}                   # Get DSAR details
PATCH  /api/v1/governance/gdpr/dsar/{id}                   # Update DSAR status
GET    /api/v1/governance/gdpr/consent                     # Get consent records
GET    /api/v1/governance/gdpr/cross-border                # Get cross-border transfers

# Risk Management
GET    /api/v1/governance/risk                              # List all risk assessments
GET    /api/v1/governance/risk/{agent_id}                   # Get agent risk assessment
POST   /api/v1/governance/risk/{agent_id}/assess            # Trigger risk assessment
POST   /api/v1/governance/risk/{agent_id}/accept            # Accept risk with justification
GET    /api/v1/governance/risk/heatmap                      # Get risk heat map data
GET    /api/v1/governance/risk/trends                       # Get risk trend data

# Lineage (Neo4j)
GET    /api/v1/governance/lineage/graph                     # Get full lineage graph
GET    /api/v1/governance/lineage/agent/{id}                # Get agent lineage
GET    /api/v1/governance/lineage/user/{id}                 # Get user lineage
GET    /api/v1/governance/lineage/data-source/{id}          # Get data source lineage
GET    /api/v1/governance/lineage/model/{id}                # Get model lineage
POST   /api/v1/governance/lineage/impact                    # Run impact analysis
GET    /api/v1/governance/lineage/search                    # Search lineage graph

# Policy Management
GET    /api/v1/governance/policies                          # List policies
POST   /api/v1/governance/policies                          # Create policy
GET    /api/v1/governance/policies/{id}                     # Get policy details
PUT    /api/v1/governance/policies/{id}                     # Update policy
DELETE /api/v1/governance/policies/{id}                     # Delete policy
POST   /api/v1/governance/policies/{id}/activate            # Activate policy
POST   /api/v1/governance/policies/{id}/disable             # Disable policy
POST   /api/v1/governance/policies/{id}/rollback            # Rollback to previous version
POST   /api/v1/governance/policies/{id}/dry-run             # Dry-run policy
POST   /api/v1/governance/policies/{id}/validate            # Validate Rego syntax
GET    /api/v1/governance/policies/{id}/versions            # List policy versions
POST   /api/v1/governance/policies/conflict-check           # Check for policy conflicts
GET    /api/v1/governance/policies/templates                # List policy templates

# Audit Log
GET    /api/v1/governance/audit                             # Query audit logs (paginated, filtered)
GET    /api/v1/governance/audit/export                      # Export audit logs
GET    /api/v1/governance/audit/integrity                   # Verify hash chain integrity
GET    /api/v1/governance/audit/correlate/{trace_id}        # Correlate events by trace ID
POST   /api/v1/governance/audit/saved-searches              # Save search filter
GET    /api/v1/governance/audit/saved-searches              # List saved searches
GET    /api/v1/governance/audit/stream                      # WebSocket real-time audit stream

# Reports
GET    /api/v1/governance/reports                           # List generated reports
POST   /api/v1/governance/reports/generate                  # Generate report on-demand
GET    /api/v1/governance/reports/{id}                      # Get report metadata
GET    /api/v1/governance/reports/{id}/download              # Download report file
GET    /api/v1/governance/reports/schedules                 # List report schedules
POST   /api/v1/governance/reports/schedules                 # Create report schedule
PUT    /api/v1/governance/reports/schedules/{id}            # Update schedule
DELETE /api/v1/governance/reports/schedules/{id}            # Delete schedule

# Dashboard
GET    /api/v1/governance/dashboard/summary                 # Executive governance summary
GET    /api/v1/governance/dashboard/identity                # Identity governance metrics
GET    /api/v1/governance/dashboard/compliance              # Compliance overview
GET    /api/v1/governance/dashboard/risk                    # Risk overview
```

## Verify Commands

```bash
# Governance engine importable
cd ~/Scripts/Archon && python -c "from backend.app.services.governance import GovernanceEngine; print('OK')"

# Identity governance importable
cd ~/Scripts/Archon && python -c "from backend.app.services.governance.identity_governance import AccessReviewService, PrivilegeElevationService, SeparationOfDutiesEnforcer, OrphanedAccountDetector; print('Identity governance OK')"

# Agent registry importable
cd ~/Scripts/Archon && python -c "from backend.app.services.governance.agent_registry import AgentRegistryService; print('Agent registry OK')"

# Compliance engine importable
cd ~/Scripts/Archon && python -c "from backend.app.services.governance.compliance_engine import ComplianceEngine; print('Compliance OK')"

# Risk engine importable
cd ~/Scripts/Archon && python -c "from backend.app.services.governance.risk_engine import RiskEngine; print('Risk engine OK')"

# Lineage service importable
cd ~/Scripts/Archon && python -c "from backend.app.services.governance.lineage_service import LineageService, ImpactAnalyzer; print('Lineage OK')"

# Policy service importable
cd ~/Scripts/Archon && python -c "from backend.app.services.governance.policy_service import PolicyService; print('Policy OK')"

# Audit viewer importable
cd ~/Scripts/Archon && python -c "from backend.app.services.governance.audit_viewer import AuditViewer, AuditIntegrityVerifier; print('Audit OK')"

# Report generator importable
cd ~/Scripts/Archon && python -c "from backend.app.services.governance.report_generator import ReportGenerator; print('Reports OK')"

# Data models importable
cd ~/Scripts/Archon && python -c "from backend.app.models.governance import GovernancePolicy, ComplianceFrameworkStatus, GovernanceReport, AccessReview, PrivilegeElevation, SeparationOfDutyRule, RiskAssessment, DSARRequest, AgentRegistryEntry; print('Models OK')"

# API router importable
cd ~/Scripts/Archon && python -c "from backend.app.routers.governance import router; print('Router OK')"

# Tests pass
cd ~/Scripts/Archon && python -m pytest tests/test_governance/ --tb=short -q

# Neo4j init scripts exist
test $(find ~/Scripts/Archon/infra/neo4j/init-scripts -name '*.cypher' 2>/dev/null | wc -l | tr -d ' ') -ge 2

# No hardcoded secrets
cd ~/Scripts/Archon && ! grep -rn 'password\s*=\s*"[^"]*"' --include='*.py' backend/app/services/governance/ || echo 'FAIL'
```

## Learnings Protocol

Before starting, read `.sdd/learnings/*.md` for known pitfalls from previous sessions.
After completing work, report any pitfalls or patterns discovered so the orchestrator can capture them.

## Acceptance Criteria

- [ ] Quarterly access reviews created, assigned to managers, with reminder notifications at 30d/14d/7d/1d
- [ ] Access review completion tracked as SOC2/HIPAA audit evidence
- [ ] Inactive users automatically warned at 60d, suspended at 90d, deactivated at 180d
- [ ] JIT privilege elevation workflow: request → approve → time-limited grant → auto-revoke at expiry
- [ ] Break-glass elevation works without pre-approval but triggers mandatory post-incident review
- [ ] Separation of duties enforced: same user cannot create AND approve an agent
- [ ] Orphaned accounts detected via SCIM cross-reference and flagged for remediation
- [ ] Agent registry displays all agents with governance metadata (owner, risk score, compliance tags, cost)
- [ ] Multi-stage approval workflow (dev → security → compliance → publish) works end-to-end
- [ ] Expedited path auto-approves low-risk PUBLIC agents with audit trail
- [ ] Approval SLA tracking with escalation on overdue reviews
- [ ] SOC2 Type II compliance tracked across all 5 trust service criteria with evidence linking
- [ ] GDPR DSAR workflow automates access/erasure/portability requests within 30-day deadline
- [ ] HIPAA BAA tracking and PHI access logging verified
- [ ] Per-agent risk scores (0-100) computed from 6 risk factors with trend tracking
- [ ] Risk heat map renders correctly for all agents across organization
- [ ] Automated mitigation recommendations generated for HIGH/CRITICAL risk agents
- [ ] Neo4j lineage graph renders correctly for 100+ agents with relationships
- [ ] Impact analysis correctly identifies all affected agents when model/data source changes
- [ ] OPA policy editor validates Rego syntax, detects conflicts with existing policies
- [ ] Policy dry-run tests against historical data and shows impact preview
- [ ] Policy versioning with instant rollback to any previous version
- [ ] Audit log search returns results within 500ms for 1M+ entries
- [ ] Hash chain integrity verification detects tampered audit entries
- [ ] Cross-agent event correlation works via trace_id and temporal proximity
- [ ] Executive PDF report generates correctly with all governance sections
- [ ] Scheduled reports delivered via email on configured cadence
- [ ] All tests pass with >80% coverage
- [ ] Zero plaintext secrets in governance module source code
