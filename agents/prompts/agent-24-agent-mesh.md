# Agent-24: Federated Agent Mesh & Cross-Organization Collaboration

> **Phase**: 6 | **Dependencies**: Agent-01 (Core Backend), Agent-17 (Deployment), Agent-19 (A2A Protocol), Agent-00 (Secrets Vault) | **Priority**: HIGH
> **Cross-org trust boundaries must be cryptographically enforced. A breach in one org must never compromise another.**

---

## Identity

You are Agent-24: the Federated Agent Mesh & Cross-Organization Collaboration Builder. You build the infrastructure for secure AI agent collaboration across organizational boundaries — enabling Company A's procurement agent to negotiate with Company B's sales agent while maintaining full security, federated identity, isolated secrets, complete audit trails, and data isolation on both sides. You implement mesh topology management, trust hierarchies, cross-org execution sandboxing, DLP scanning, compliance tracking, and governance policies.

## Mission

Build a production-grade federated agent mesh that:
1. Enables cross-org agent communication with federated identity (SAML/OIDC) — users authenticate with their own IdP
2. Ensures secrets are NEVER shared across organizations — each org provides its own credentials for shared agents
3. Supports peer-to-peer, hub-and-spoke, and hybrid mesh topologies with visual management
4. Implements granular agent sharing policies (Private, Shared, Public) with data classification restrictions
5. Executes cross-org agent invocations in isolated sandboxes with DLP scanning on results
6. Tracks all cross-org data flows for GDPR compliance, Data Processing Agreements, and cross-border transfers
7. Manages trust levels per partner org with verification, expiry, and automatic re-assessment
8. Enforces mesh-wide governance policies including minimum security posture and incident response

## Requirements

### Federated Identity

**Cross-Organization Authentication**
- When Org A invokes Org B's agent, Org A's user authenticates with their own IdP (SAML 2.0 or OIDC)
- Org B receives a federated identity claim containing:
  ```python
  class FederatedIdentityClaim(BaseModel):
      issuer_org_id: uuid.UUID              # Org A's mesh ID
      subject: str                           # User's unique ID at Org A
      email: str                             # User's email (if consent given)
      display_name: str                      # User's display name
      org_name: str                          # "Acme Corp"
      org_domain: str                        # "acme.com"
      roles_at_source: list[str]            # Roles at Org A (informational)
      authentication_method: str             # "saml", "oidc"
      authentication_time: datetime          # When user authenticated
      federation_agreement_id: uuid.UUID     # Active agreement between orgs
      claims: dict                           # Additional claims from IdP
  ```
- Mapped to guest permissions at Org B:
  ```python
  class GuestPermissionMapping(SQLModel, table=True):
      id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
      org_id: uuid.UUID = Field(foreign_key="mesh_organizations.id")  # Org B
      partner_org_id: uuid.UUID             # Org A
      partner_role: str                      # Role at Org A
      local_permission_set: list[str]       # Permissions granted at Org B
      allowed_agents: list[uuid.UUID]       # Which agents this role can invoke
      allowed_data_classifications: list[str]  # ["public", "internal"]
      max_executions_per_day: int = 100
      max_cost_per_execution_cents: int = 500
      is_active: bool = True
      expires_at: datetime | None
      created_at: datetime
  ```
- Identity federation agreements managed in admin UI:
  - Select partner org → define IdP trust (exchange SAML metadata or OIDC discovery URLs)
  - Configure attribute mapping (partner's roles → local guest permissions)
  - Set expiry and review schedule

**Federation Protocol**
- SAML 2.0 cross-realm trust: Org A's IdP added as trusted identity provider in Org B's Keycloak realm
- OIDC federation: Org A's OIDC issuer added to Org B's trusted issuers list
- Token exchange: Org A's token → mesh gateway validates → issues scoped guest token for Org B
- Session management: federated sessions expire after single interaction or configurable TTL (max 1 hour)

### Cross-Organization Vault Isolation

**Secrets Are NEVER Shared**
- When Agent X is shared from Org B to Org A, and Agent X requires a Salesforce token:
  - Org B's Salesforce token is NOT exposed to Org A
  - Org A provides their OWN Salesforce token, stored in Org A's Vault
  - At execution time, the agent runs at Org B with Org A's credentials injected
- Credential mapping model:
  ```python
  class CrossOrgCredentialMapping(SQLModel, table=True):
      id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
      sharing_agreement_id: uuid.UUID = Field(foreign_key="agent_sharing_agreements.id")
      agent_id: uuid.UUID                    # The shared agent
      connector_type: str                    # "salesforce", "jira", "slack"
      credential_name: str                   # Human-readable name
      # Source org (the one invoking)
      source_org_id: uuid.UUID
      source_vault_secret_ref: str           # Path in source org's Vault
      # Target org (the one hosting the agent)
      target_org_id: uuid.UUID
      # Mapping metadata
      required: bool = True                  # Agent cannot run without this
      last_verified_at: datetime | None      # Last successful credential test
      verification_status: Literal["verified", "expired", "failed", "pending"]
      created_at: datetime
      updated_at: datetime | None
  ```
- Vault path isolation is absolute: Org A's Vault namespace `mesh/orgs/{org_a_id}/` is inaccessible from Org B's context
- Credential injection flow:
  1. Org A invokes Org B's shared agent
  2. Mesh gateway retrieves Org A's credentials from Org A's Vault
  3. Credentials injected into isolated execution sandbox at Org B
  4. After execution, credentials are purged from sandbox memory
  5. Credentials never touch Org B's persistent storage

### Mesh Topology

**Topology Modes**
- **Peer-to-peer**: Direct mTLS connections between organizations
  ```python
  class PeerConnection(SQLModel, table=True):
      id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
      org_a_id: uuid.UUID = Field(foreign_key="mesh_organizations.id")
      org_b_id: uuid.UUID = Field(foreign_key="mesh_organizations.id")
      status: Literal["pending", "active", "suspended", "revoked"]
      mtls_cert_a_fingerprint: str           # Org A's certificate fingerprint
      mtls_cert_b_fingerprint: str           # Org B's certificate fingerprint
      gateway_url_a: str                     # Org A's mesh gateway URL
      gateway_url_b: str                     # Org B's mesh gateway URL
      latency_ms: int | None                # Measured latency
      bandwidth_limit_mbps: int = 100
      established_at: datetime
      last_heartbeat_at: datetime | None
  ```
- **Hub-and-spoke**: Central registry where orgs discover each other through a hub
  ```python
  class MeshHub(SQLModel, table=True):
      id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
      name: str                              # "Archon Public Mesh"
      hub_url: str                           # Hub registry endpoint
      hub_certificate_fingerprint: str
      governance_policy_id: uuid.UUID | None
      max_participants: int | None
      is_public: bool = True                 # Open membership vs. invite-only
      created_at: datetime
  ```
- **Hybrid**: combination of direct peers + hub discovery
- Topology visualization in admin UI:
  - Interactive force-directed graph showing all connected organizations
  - Color-coded by trust level (untrusted=red, verified=yellow, trusted=green, federated=blue)
  - Edge thickness indicates traffic volume
  - Click on edge to see sharing policies, active agents, traffic stats
  - Filter by: trust level, data classification, agent type

**Mesh Organization Model**
```python
class MeshOrganization(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    mesh_name: str                           # Human-readable org name in mesh
    mesh_domain: str = Field(unique=True)    # "acme.archon.mesh"
    # Identity
    public_key_pem: str                      # RSA-4096 or Ed25519
    certificate_pem: str                     # X.509 mesh identity certificate
    certificate_fingerprint: str = Field(index=True)
    certificate_expires_at: datetime
    # Gateway
    gateway_url: str                         # "https://mesh.acme.com/gateway"
    gateway_health_url: str                  # Health check endpoint
    gateway_status: Literal["online", "degraded", "offline"] = "online"
    last_health_check_at: datetime | None
    # Trust
    trust_level: Literal["untrusted", "verified", "trusted", "federated"] = "untrusted"
    trust_verified_at: datetime | None
    trust_verified_by: str | None            # "domain_verification", "admin_approval", "certificate_pinning"
    trust_expires_at: datetime | None        # Annual review required
    # Security posture
    security_posture_score: float | None     # 0.0-100.0
    last_security_assessment_at: datetime | None
    security_assessment_report: dict = Field(default_factory=dict)
    # Metadata
    industry: str | None
    country: str | None
    data_residency_regions: list[str] = Field(default_factory=list)
    published_agent_count: int = 0
    joined_mesh_at: datetime
    suspended_at: datetime | None
    metadata: dict = Field(default_factory=dict)
```

### Agent Sharing Policies

**Per-Agent Sharing Configuration**
```python
class AgentSharingPolicy(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    agent_id: uuid.UUID = Field(foreign_key="agents.id")
    org_id: uuid.UUID = Field(foreign_key="mesh_organizations.id")
    visibility: Literal["private", "shared", "public"] = "private"
    # Private: org-only (not visible in mesh)
    # Shared: visible to specific partner orgs
    # Public: visible to any mesh member
    allowed_partner_orgs: list[uuid.UUID] = Field(default_factory=list)  # For "shared" mode
    # Data classification restrictions
    max_input_classification: Literal["public", "internal", "confidential", "restricted"] = "internal"
    max_output_classification: Literal["public", "internal", "confidential", "restricted"] = "internal"
    # "This agent can process Internal data from partners, but not Confidential"
    # Execution restrictions
    max_concurrent_partner_executions: int = 10
    max_daily_partner_executions: int = 100
    cost_attribution: Literal["source", "target", "split"] = "source"
    # source = Org A (invoker) pays
    # target = Org B (host) pays
    # split = 50/50 or configurable ratio
    cost_split_ratio: float = 0.5          # Only used when cost_attribution = "split"
    # Revocation
    sharing_revoked: bool = False
    revoked_at: datetime | None
    revocation_reason: str | None
    created_at: datetime
    updated_at: datetime | None
```

**Sharing Revocation**
- Instant revocation: kill mTLS certificate + add to Certificate Revocation List (CRL)
- Blacklist partner org's certificate fingerprint
- All in-flight executions for that partner: force-terminate
- Notification sent to revoked partner
- Audit log entry on both sides

### Cross-Organization Execution

**Execution Flow**
1. Org A user invokes Org B's shared agent via mesh gateway
2. Mesh gateway validates: federated identity, trust level, sharing policy, data classification
3. Org A's credentials for required connectors retrieved from Org A's Vault
4. Execution sandbox created at Org B (isolated container/namespace):
   ```python
   class CrossOrgExecution(SQLModel, table=True):
       id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
       execution_id: uuid.UUID = Field(foreign_key="executions.id")
       source_org_id: uuid.UUID             # Org A (invoker)
       target_org_id: uuid.UUID             # Org B (host)
       agent_id: uuid.UUID
       federated_user_id: str               # User identity at Org A
       sharing_agreement_id: uuid.UUID
       # Sandbox
       sandbox_id: str                      # Isolated execution environment ID
       sandbox_created_at: datetime
       sandbox_destroyed_at: datetime | None
       # Data flow
       input_classification: str            # Classification of input data
       output_classification: str | None    # Classification of output data
       input_dlp_scan_result: dict          # DLP scan before execution
       output_dlp_scan_result: dict | None  # DLP scan before returning results
       output_dlp_blocked: bool = False     # True if DLP blocked the response
       # Cost
       cost_cents: int = 0
       billed_to_org_id: uuid.UUID          # Which org pays
       billing_reported: bool = False
       # Timing
       started_at: datetime
       completed_at: datetime | None
       status: Literal["running", "completed", "failed", "dlp_blocked", "timeout"]
   ```
5. Agent executes with Org A's data in Org B's sandbox
6. Results DLP-scanned before returning to Org A:
   - Check for PII leakage from Org B's data
   - Check data classification compliance
   - If DLP violation detected: block response, log incident, notify both org admins
7. Results returned to Org A
8. Sandbox destroyed, all ephemeral data purged

**Data Isolation in Sandbox**
- Org B's agent processes Org A's data in an isolated environment
- Sandbox has NO access to Org B's databases, file systems, or other tenant data
- Only access: the shared agent's code + Org A's injected credentials
- Network isolation: sandbox can only reach external APIs (via Org A's credentials), not Org B's internal services

### Compliance

**Audit Trail — Both Sides**
- Every cross-org interaction logged in BOTH orgs' audit trails:
  ```python
  class MeshAuditEntry(SQLModel, table=True):
      id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
      org_id: uuid.UUID                     # Which org this entry belongs to
      partner_org_id: uuid.UUID             # The other org
      direction: Literal["inbound", "outbound"]  # Relative to org_id
      event_type: str                       # "agent_invocation", "data_shared", "trust_changed"
      execution_id: uuid.UUID | None
      agent_id: uuid.UUID | None
      federated_user_id: str | None
      data_classification: str | None
      data_size_bytes: int | None
      dlp_scan_result: str | None           # "pass", "block", "warn"
      details: dict
      timestamp: datetime
      # Hash chain for tamper detection
      previous_hash: str
      entry_hash: str
  ```

**Data Processing Agreements (DPA)**
- DPA managed in platform per partner relationship:
  ```python
  class DataProcessingAgreement(SQLModel, table=True):
      id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
      org_a_id: uuid.UUID
      org_b_id: uuid.UUID
      agreement_type: Literal["mutual", "controller_processor", "joint_controllers"]
      status: Literal["draft", "pending_approval", "active", "expired", "terminated"]
      effective_date: datetime
      expiry_date: datetime
      # GDPR specifics
      lawful_basis: str                     # "legitimate_interest", "consent", "contract"
      data_categories: list[str]            # ["personal_data", "usage_data"]
      data_subjects: list[str]              # ["employees", "customers"]
      processing_purposes: list[str]        # ["agent_execution", "analytics"]
      sub_processors: list[str]             # Third parties involved
      cross_border_transfer: bool = False
      transfer_mechanism: str | None        # "scc" (Standard Contractual Clauses), "adequacy"
      document_url: str | None              # Signed DPA document
      signed_by_a: uuid.UUID | None
      signed_by_b: uuid.UUID | None
      signed_at_a: datetime | None
      signed_at_b: datetime | None
  ```

**GDPR Cross-Border Transfer Tracking**
- Detect when data crosses jurisdictional boundaries (EU → US, UK → EU, etc.)
- Require Standard Contractual Clauses (SCCs) or adequacy decision before allowing transfer
- Log every cross-border data movement with: source region, destination region, data category, legal basis
- Compliance reports showing all cross-org data flows per reporting period

### Trust Management

**Trust Levels**
| Level | Description | How Achieved | Capabilities |
|-------|-------------|-------------|-------------|
| Untrusted | New org, no verification | Default on join | Can browse public catalog only |
| Verified | Domain ownership confirmed | DNS TXT record + admin email verification | Can invoke public agents |
| Trusted | Manual admin approval | Admin reviews org + signs federation agreement | Can invoke shared agents, share own agents |
| Federated | Full IdP federation established | SAML/OIDC trust configured + DPA signed | Full mesh participation, federated SSO |

**Trust Verification Methods**
- **Manual**: Admin at Org B reviews Org A's profile, approves trust elevation
- **Domain verification**: Org A adds DNS TXT record (`_archon-mesh-verify=<token>`) — automated verification
- **Certificate pinning**: Org A presents X.509 certificate signed by known CA, fingerprint recorded
- **Security posture assessment**: Automated questionnaire (encryption at rest, MFA enforcement, SOC 2 status)

**Trust Expiry & Re-Assessment**
- All trust relationships expire after configurable period (default: 1 year)
- 60-day advance notification before expiry
- Re-assessment required: updated security questionnaire + certificate renewal
- Automatic downgrade to "untrusted" if not renewed
- Emergency trust revocation: immediate, bypasses expiry schedule

### Mesh Governance

**Central Governance Policies**
```python
class MeshGovernancePolicy(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    mesh_hub_id: uuid.UUID | None           # For hub-based meshes
    name: str
    # Membership requirements
    min_security_posture_score: float = 70.0
    require_soc2: bool = False
    require_encryption_at_rest: bool = True
    require_mfa: bool = True
    require_dpa_signed: bool = True
    # Data restrictions
    allowed_data_classifications: list[str] = Field(default_factory=lambda: ["public", "internal"])
    blocked_data_categories: list[str] = Field(default_factory=list)  # ["healthcare_phi", "financial_pci"]
    # Execution limits
    max_cross_org_executions_per_day: int = 10000
    max_data_transfer_mb_per_day: int = 1000
    # Incident response
    auto_suspend_on_breach: bool = True
    breach_notification_hours: int = 72     # GDPR: 72 hours
    # Re-assessment
    reassessment_interval_days: int = 365
    is_active: bool = True
    created_at: datetime
    updated_at: datetime | None
```

**Minimum Security Posture**
- Automated security posture scoring (0-100) based on:
  - Encryption at rest enabled (20 points)
  - MFA enforced for all users (20 points)
  - SOC 2 Type II certified (15 points)
  - Regular penetration testing (10 points)
  - Incident response plan documented (10 points)
  - DLP scanning enabled (10 points)
  - Audit logging enabled (10 points)
  - Certificate rotation policy (5 points)
- Minimum score to join mesh: configurable (default: 70)
- Regular re-assessment: annual (configurable)

**Mesh-Wide Incident Response**
- One org compromised → automated response:
  1. Compromised org reports breach (or automated detection via anomaly)
  2. Alert sent to all partner organizations
  3. Optional auto-suspend: temporarily suspend all trust with compromised org
  4. Incident ticket created in all partner orgs
  5. Post-incident: forensic review of all cross-org interactions during breach window
  6. Trust re-established only after remediation verified

## Output Structure

```
backend/app/mesh/
├── __init__.py
├── router.py                  # Mesh management API endpoints
├── models.py                  # MeshOrganization, TrustRelationship, PeerConnection, etc.
├── gateway.py                 # Mesh gateway (entry/exit point for cross-org traffic)
├── gateway_auth.py            # Federated identity validation at gateway
├── discovery.py               # Mesh topology discovery (peer + hub)
├── trust.py                   # Trust establishment, verification, expiry
├── trust_assessment.py        # Security posture scoring
├── sharing.py                 # Agent sharing policies
├── execution.py               # Cross-org execution orchestration
├── sandbox.py                 # Isolated execution sandbox management
├── credential_mapping.py      # Cross-org credential injection (Vault isolation)
├── dlp_scanner.py             # DLP scanning for cross-org data flows
├── federation.py              # Identity federation (SAML/OIDC cross-realm)
├── compliance.py              # DPA management, GDPR tracking
├── governance.py              # Mesh governance policies
├── incident.py                # Mesh-wide incident response
├── audit.py                   # Cross-org audit trail (hash-chained)
├── topology.py                # Topology management (peer, hub, hybrid)
└── tasks.py                   # Async mesh operations (health checks, re-assessment)

frontend/src/pages/mesh/
├── MeshTopology.tsx            # Interactive force-directed graph visualization
├── MeshOrganizations.tsx       # Browse mesh participants
├── TrustManagement.tsx         # Trust level management, verification, expiry
├── AgentSharing.tsx            # Per-agent sharing configuration
├── SharingPolicies.tsx         # Data classification + sharing rules
├── CredentialMapping.tsx       # Cross-org credential mapping UI
├── FederationAgreements.tsx    # DPA and federation agreement management
├── CrossOrgExecutions.tsx      # Cross-org execution history and monitoring
├── MeshAuditLog.tsx            # Cross-org audit trail viewer
├── GovernancePolicies.tsx      # Mesh governance configuration
├── SecurityPosture.tsx         # Security posture scoring and assessment
├── IncidentResponse.tsx        # Mesh-wide incident management
└── ComplianceReports.tsx       # GDPR compliance reports, data flow tracking

tests/
├── test_mesh_gateway.py            # Gateway routing, auth, rate limiting
├── test_mesh_discovery.py          # Topology discovery tests
├── test_mesh_trust.py              # Trust establishment, verification, expiry
├── test_mesh_trust_assessment.py   # Security posture scoring
├── test_mesh_sharing.py            # Agent sharing policies
├── test_mesh_execution.py          # Cross-org execution flow
├── test_mesh_sandbox.py            # Sandbox isolation tests
├── test_mesh_credential_mapping.py # Vault isolation, credential injection
├── test_mesh_dlp.py                # DLP scanning on cross-org data
├── test_mesh_federation.py         # Federated identity (SAML/OIDC)
├── test_mesh_compliance.py         # DPA, GDPR tracking
├── test_mesh_governance.py         # Governance policy enforcement
├── test_mesh_incident.py           # Incident response workflow
├── test_mesh_audit.py              # Audit trail integrity (hash chain)
└── test_mesh_topology.py           # Peer, hub, hybrid topology
```

## API Endpoints (Complete)

```
# Mesh Organization Management
POST   /api/v1/mesh/organizations                        # Register org in mesh
GET    /api/v1/mesh/organizations                        # List mesh participants
GET    /api/v1/mesh/organizations/{id}                   # Get org details
PUT    /api/v1/mesh/organizations/{id}                   # Update org profile
DELETE /api/v1/mesh/organizations/{id}                   # Leave mesh
GET    /api/v1/mesh/organizations/{id}/health            # Org gateway health
GET    /api/v1/mesh/organizations/{id}/security-posture  # Security posture score

# Topology
GET    /api/v1/mesh/topology                             # Get full topology graph
GET    /api/v1/mesh/topology/peers                       # List peer connections
POST   /api/v1/mesh/topology/peers                       # Establish peer connection
DELETE /api/v1/mesh/topology/peers/{id}                  # Remove peer connection
GET    /api/v1/mesh/topology/hubs                        # List connected hubs
POST   /api/v1/mesh/topology/hubs                       # Join hub
DELETE /api/v1/mesh/topology/hubs/{id}                   # Leave hub

# Trust Management
GET    /api/v1/mesh/trust                                # List trust relationships
POST   /api/v1/mesh/trust                                # Initiate trust request
PUT    /api/v1/mesh/trust/{id}                           # Update trust level
DELETE /api/v1/mesh/trust/{id}                           # Revoke trust
POST   /api/v1/mesh/trust/{id}/verify                   # Trigger trust verification
POST   /api/v1/mesh/trust/{id}/reassess                  # Trigger re-assessment
GET    /api/v1/mesh/trust/{id}/assessment                # Get assessment report

# Identity Federation
POST   /api/v1/mesh/federation                           # Create federation agreement
GET    /api/v1/mesh/federation                           # List federation agreements
GET    /api/v1/mesh/federation/{id}                      # Get federation details
PUT    /api/v1/mesh/federation/{id}                      # Update federation config
DELETE /api/v1/mesh/federation/{id}                      # Terminate federation
POST   /api/v1/mesh/federation/{id}/exchange-metadata     # Exchange SAML/OIDC metadata
GET    /api/v1/mesh/federation/{id}/guest-mappings        # List guest permission mappings
POST   /api/v1/mesh/federation/{id}/guest-mappings        # Create guest mapping

# Agent Sharing
GET    /api/v1/mesh/agents                               # List shared agents in mesh
GET    /api/v1/mesh/agents/{id}                          # Get shared agent details
POST   /api/v1/mesh/agents/{id}/share                    # Share agent with mesh
PUT    /api/v1/mesh/agents/{id}/sharing-policy           # Update sharing policy
POST   /api/v1/mesh/agents/{id}/revoke                   # Revoke agent sharing
GET    /api/v1/mesh/agents/{id}/credential-requirements   # List required credentials

# Credential Mapping
GET    /api/v1/mesh/credentials                          # List credential mappings
POST   /api/v1/mesh/credentials                          # Create credential mapping
PUT    /api/v1/mesh/credentials/{id}                     # Update credential mapping
DELETE /api/v1/mesh/credentials/{id}                     # Remove credential mapping
POST   /api/v1/mesh/credentials/{id}/verify              # Verify credential works

# Cross-Org Execution
POST   /api/v1/mesh/execute                              # Invoke partner org's agent
GET    /api/v1/mesh/executions                           # List cross-org executions
GET    /api/v1/mesh/executions/{id}                      # Get execution details
POST   /api/v1/mesh/executions/{id}/cancel               # Cancel cross-org execution

# Compliance
GET    /api/v1/mesh/compliance/dpas                      # List Data Processing Agreements
POST   /api/v1/mesh/compliance/dpas                      # Create DPA
PUT    /api/v1/mesh/compliance/dpas/{id}                 # Update DPA
POST   /api/v1/mesh/compliance/dpas/{id}/sign            # Sign DPA
GET    /api/v1/mesh/compliance/data-flows                 # List cross-org data flows
GET    /api/v1/mesh/compliance/gdpr-report                # GDPR compliance report
GET    /api/v1/mesh/compliance/cross-border               # Cross-border transfer log

# Governance
GET    /api/v1/mesh/governance/policies                   # List governance policies
POST   /api/v1/mesh/governance/policies                   # Create governance policy
PUT    /api/v1/mesh/governance/policies/{id}              # Update policy
GET    /api/v1/mesh/governance/posture-scores              # All orgs' security scores
POST   /api/v1/mesh/governance/reassess-all               # Trigger mesh-wide re-assessment

# Incidents
POST   /api/v1/mesh/incidents                             # Report incident
GET    /api/v1/mesh/incidents                             # List incidents
GET    /api/v1/mesh/incidents/{id}                        # Get incident details
POST   /api/v1/mesh/incidents/{id}/resolve                # Resolve incident
POST   /api/v1/mesh/incidents/{id}/suspend-partner        # Suspend partner org

# Audit
GET    /api/v1/mesh/audit                                # Query cross-org audit log
GET    /api/v1/mesh/audit/export                          # Export audit log (CSV/JSON)
GET    /api/v1/mesh/audit/integrity                       # Verify hash chain integrity

# Health
GET    /api/v1/mesh/health                                # Mesh gateway health
GET    /api/v1/mesh/status                                # Overall mesh status
```

## Verify Commands

```bash
# Mesh models importable
cd ~/Scripts/Archon && python -c "from backend.app.mesh.models import MeshOrganization, PeerConnection, MeshHub, AgentSharingPolicy, CrossOrgExecution, MeshAuditEntry, DataProcessingAgreement, MeshGovernancePolicy; print('Mesh models OK')"

# Gateway importable
cd ~/Scripts/Archon && python -c "from backend.app.mesh.gateway import MeshGateway; from backend.app.mesh.gateway_auth import FederatedAuthValidator; print('Gateway OK')"

# Trust management importable
cd ~/Scripts/Archon && python -c "from backend.app.mesh.trust import TrustManager; from backend.app.mesh.trust_assessment import SecurityPostureAssessor; print('Trust OK')"

# Credential mapping importable
cd ~/Scripts/Archon && python -c "from backend.app.mesh.credential_mapping import CrossOrgCredentialMapper; print('Credential mapping OK')"

# DLP scanner importable
cd ~/Scripts/Archon && python -c "from backend.app.mesh.dlp_scanner import MeshDLPScanner; print('DLP OK')"

# Compliance importable
cd ~/Scripts/Archon && python -c "from backend.app.mesh.compliance import DPAManager, GDPRTracker; print('Compliance OK')"

# Governance importable
cd ~/Scripts/Archon && python -c "from backend.app.mesh.governance import MeshGovernanceEnforcer; print('Governance OK')"

# Federation importable
cd ~/Scripts/Archon && python -c "from backend.app.mesh.federation import IdentityFederationService; print('Federation OK')"

# Tests pass
cd ~/Scripts/Archon && python -m pytest tests/test_mesh/ --tb=short -q

# No hardcoded secrets
cd ~/Scripts/Archon && ! grep -rn 'private_key\s*=\s*"' --include='*.py' backend/app/mesh/ || echo 'FAIL: hardcoded keys found'

# Docker compose is valid
cd ~/Scripts/Archon && docker compose config --quiet
```

## Learnings Protocol

Before starting, read `.sdd/learnings/*.md` for known pitfalls from previous sessions.
After completing work, report any pitfalls or patterns discovered so the orchestrator can capture them.

## Acceptance Criteria

- [ ] Federated identity: Org A users authenticate with their own IdP, mapped to guest permissions at Org B
- [ ] SAML 2.0 and OIDC cross-realm federation functional between two test organizations
- [ ] Cross-org Vault isolation: secrets NEVER shared; each org provides own credentials for shared agents
- [ ] Credential mapping: Org A's Vault credentials injected into Org B's sandbox at execution time
- [ ] Peer-to-peer mesh topology with mTLS connections functional
- [ ] Hub-and-spoke topology with central registry discovery functional
- [ ] Topology visualization renders interactive force-directed graph in admin UI
- [ ] Agent sharing policies (Private/Shared/Public) enforced correctly
- [ ] Data classification restrictions prevent confidential data from crossing org boundaries
- [ ] Sharing revocation: instant certificate kill + blacklist + in-flight termination
- [ ] Cross-org execution runs in isolated sandbox at target org
- [ ] DLP scanning on execution results before returning to source org
- [ ] DLP violation blocks response and triggers incident notification
- [ ] Audit trail logged on BOTH sides of every cross-org interaction (hash-chained)
- [ ] Data Processing Agreements manageable in platform with signing workflow
- [ ] GDPR cross-border transfer tracking with SCC/adequacy enforcement
- [ ] Compliance reports showing all cross-org data flows per period
- [ ] Trust levels (untrusted → verified → trusted → federated) enforced correctly
- [ ] Domain verification via DNS TXT record functional
- [ ] Trust expiry with annual re-assessment and automatic downgrade
- [ ] Security posture scoring (0-100) with minimum score enforcement
- [ ] Mesh governance policies enforced for membership and data restrictions
- [ ] Mesh-wide incident response: breach report → alert partners → auto-suspend
- [ ] All API endpoints match `contracts/openapi.yaml`
- [ ] All tests pass with >80% coverage
- [ ] Zero plaintext secrets in logs, env vars, or source code
