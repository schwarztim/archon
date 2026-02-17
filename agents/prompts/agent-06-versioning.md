# Agent-06: Agent Version Control System (Enterprise)

> **Phase**: 1 | **Dependencies**: Agent-01 (Core Backend) | **Priority**: HIGH
> **The safety backbone. Every change tracked, every version signed, every rollback safe. Git-like power for agent lifecycle management with enterprise compliance built in.**

---

## Identity

You are Agent-06: the Agent Version Control Architect. You implement a comprehensive, Git-like version control system for agent definitions — with signed versions, secrets-aware diffs, visual canvas comparison, environment-based deployment promotion, safe rollback with pre-flight checks, and compliance-grade audit trails with version retention policies.

## Mission

Build a production-grade version control system that:
1. Creates immutable, cryptographically signed version snapshots for every agent change, with the creator's identity from Keycloak JWT
2. Tracks credential reference changes between versions — diffs show which secrets were added/removed/modified (paths only, never values)
3. Provides Git-like workflows: branch, merge, diff, cherry-pick for agent definitions with visual diff in React Flow
4. Implements deployment promotion pipelines (dev → staging → prod) with approval gates and environment-specific secrets (different Vault paths per environment)
5. Ensures safe rollback with pre-flight checks: secrets compatibility, connector compatibility, model availability
6. Logs every version change in AuditLog with actor, reason, and diff summary — with required "change reason" for production deployments
7. Enforces compliance: version retention policies (minimum 90 days for regulated industries), exportable version history (JSON + PDF)

## Requirements

### Signed Versions

**Cryptographically Signed Version Snapshots**
- Every version is signed with the creator's identity extracted from the Keycloak JWT:
  ```python
  class VersionSigner:
      """Signs version snapshots with the creator's identity."""
      
      async def sign(self, version: AgentVersion, jwt_claims: dict) -> SignedVersion:
          # 1. Compute content hash
          content = self.canonical_content(version)
          content_hash = hashlib.sha256(content.encode()).hexdigest()
          
          # 2. Build signing payload
          signing_payload = SigningPayload(
              version_id=str(version.id),
              content_hash=content_hash,
              signer_id=jwt_claims["sub"],
              signer_email=jwt_claims["email"],
              signer_roles=jwt_claims.get("roles", []),
              timestamp=datetime.utcnow().isoformat(),
              previous_version_hash=version.previous_hash
          )
          
          # 3. Sign with platform key (stored in Vault)
          signing_key = await self.vault_client.get_signing_key(
              path="archon/platform/signing/agent-versions"
          )
          signature = self.sign_payload(signing_payload, signing_key)
          
          # 4. Store signature alongside version
          return SignedVersion(
              version_id=version.id,
              content_hash=content_hash,
              signature=base64.b64encode(signature).decode(),
              signing_identity=jwt_claims["email"],
              signing_method="ed25519",
              timestamp=datetime.utcnow()
          )
      
      def canonical_content(self, version: AgentVersion) -> str:
          """Deterministic serialization for consistent hashing."""
          return json.dumps({
              "graph_definition": version.graph_definition,
              "python_source": version.python_source,
              "config": version.config,
              "dependencies": sorted(version.dependencies),
              "credential_refs": sorted(version.credential_refs)
          }, sort_keys=True, separators=(",", ":"))
  ```

**Tamper Detection via Hash Chain**
- Each version includes the hash of the previous version, creating an immutable chain:
  ```python
  class VersionHashChain:
      """Maintains a tamper-evident hash chain across all versions of an agent."""
      
      async def compute_entry_hash(self, version: AgentVersion, 
                                    previous_hash: str | None) -> str:
          chain_data = {
              "version_id": str(version.id),
              "content_hash": version.content_hash,
              "signature": version.signature,
              "previous_hash": previous_hash or "GENESIS",
              "timestamp": version.created_at.isoformat()
          }
          return hashlib.sha256(
              json.dumps(chain_data, sort_keys=True).encode()
          ).hexdigest()
      
      async def verify_chain(self, agent_id: uuid.UUID) -> ChainVerificationResult:
          """Verify the entire hash chain for an agent's version history."""
          versions = await self.repo.get_all_versions(agent_id, order="asc")
          previous_hash = None
          
          for version in versions:
              expected_hash = await self.compute_entry_hash(version, previous_hash)
              if version.entry_hash != expected_hash:
                  return ChainVerificationResult(
                      valid=False,
                      broken_at=version.id,
                      expected=expected_hash,
                      actual=version.entry_hash
                  )
              previous_hash = version.entry_hash
          
          return ChainVerificationResult(valid=True, versions_verified=len(versions))
  ```

### Core Data Models

**AgentVersion Model**
```python
class AgentVersion(SQLModel, table=True):
    """An immutable snapshot of an agent at a point in time."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    agent_id: uuid.UUID = Field(foreign_key="agents.id", index=True)
    
    # Semantic version
    version_major: int = 0
    version_minor: int = 0
    version_patch: int = 1
    version_label: str | None                  # "beta", "rc1", etc.
    version_string: str                        # Computed: "0.0.1-beta"
    
    # Immutable content snapshot
    graph_definition: dict                     # Full LangGraph JSON
    python_source: str | None                  # Generated/edited Python code
    config: dict                               # Agent configuration
    dependencies: list[str]                    # pip dependencies
    node_count: int                            # Number of nodes in graph
    edge_count: int                            # Number of edges in graph
    
    # Credential references
    credential_refs: list[CredentialRef] = Field(default_factory=list)
    connector_refs: list[str] = Field(default_factory=list)
    model_refs: list[str] = Field(default_factory=list)
    
    # Signing & integrity
    content_hash: str                          # SHA-256 of canonical content
    signature: str | None                      # Base64-encoded signature
    signing_identity: str | None               # Signer's email from JWT
    signing_method: str | None                 # "ed25519", "rsa", etc.
    previous_hash: str | None                  # Hash chain: previous version's entry_hash
    entry_hash: str                            # Hash chain: this version's entry hash
    
    # Branching
    branch: str = "main"                       # Branch name
    parent_version_id: uuid.UUID | None        # Parent version (for branching/merging)
    merge_source_id: uuid.UUID | None          # If this version is a merge result
    
    # Change metadata
    change_type: Literal["create", "update", "rollback", "merge", "cherry_pick", "promotion"]
    change_reason: str | None                  # Required for production deployments
    change_summary: str | None                 # Auto-generated diff summary
    
    # Deployment state
    deployed_environments: list[str] = Field(default_factory=list)  # ["dev", "staging", "prod"]
    
    # Authorship
    created_by: uuid.UUID = Field(foreign_key="users.id")
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    workspace_id: uuid.UUID = Field(foreign_key="workspaces.id")
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Soft delete (versions are never hard-deleted for compliance)
    deleted_at: datetime | None

class CredentialRef(BaseModel):
    """A reference to a credential used by an agent version (path only, never values)."""
    connector_type: str                        # "salesforce", "slack", etc.
    vault_path_pattern: str                    # "archon/{tenant_id}/connectors/{type}"
    required: bool = True
    auth_method: str                           # "oauth2", "api_key", "iam_role"
    added_in_version: str | None               # Version where this ref was first added
```

**VersionDiff Model**
```python
class VersionDiff(BaseModel):
    """Structured diff between two agent versions."""
    source_version_id: uuid.UUID
    target_version_id: uuid.UUID
    source_version_string: str
    target_version_string: str
    
    # Graph changes
    nodes_added: list[NodeDiff]                # New nodes
    nodes_removed: list[NodeDiff]              # Deleted nodes
    nodes_modified: list[NodeModification]     # Changed nodes (with before/after)
    edges_added: list[EdgeDiff]                # New edges
    edges_removed: list[EdgeDiff]              # Deleted edges
    edges_modified: list[EdgeModification]     # Changed edges
    
    # Config changes
    config_diff: dict                          # JSON patch (RFC 6902)
    
    # Credential changes (paths only, never values)
    credentials_added: list[CredentialRef]     # New credential refs
    credentials_removed: list[CredentialRef]   # Removed credential refs
    credentials_modified: list[CredentialRefChange]  # Changed credential refs
    
    # Connector & model changes
    connectors_added: list[str]
    connectors_removed: list[str]
    models_added: list[str]
    models_removed: list[str]
    
    # Code changes
    python_diff: str | None                    # Unified diff format
    dependency_changes: DependencyDiff
    
    # Summary
    change_magnitude: Literal["trivial", "minor", "major", "breaking"]
    auto_summary: str                          # LLM-generated change summary

class NodeDiff(BaseModel):
    node_id: str
    node_type: str
    label: str
    config: dict

class NodeModification(BaseModel):
    node_id: str
    node_type: str
    label: str
    changes: dict                              # {field: {old: ..., new: ...}}

class EdgeDiff(BaseModel):
    source: str
    target: str
    condition: str | None

class EdgeModification(BaseModel):
    source: str
    target: str
    changes: dict

class CredentialRefChange(BaseModel):
    connector_type: str
    field: str                                 # What changed (e.g., "vault_path_pattern")
    old_value: str
    new_value: str

class DependencyDiff(BaseModel):
    added: list[str]
    removed: list[str]
    upgraded: list[dict]                       # {package, from_version, to_version}
    downgraded: list[dict]
```

**VersionBranch Model**
```python
class VersionBranch(SQLModel, table=True):
    """A branch for parallel agent development."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    agent_id: uuid.UUID = Field(foreign_key="agents.id", index=True)
    name: str                                  # "main", "feature/new-tool", "experiment/v2"
    description: str | None
    
    # Branch state
    head_version_id: uuid.UUID = Field(foreign_key="agent_versions.id")
    base_version_id: uuid.UUID                 # Version this branch was created from
    status: Literal["active", "merged", "abandoned"] = "active"
    
    # Merge metadata
    merged_into: str | None                    # Branch name merged into (if merged)
    merged_at: datetime | None
    merged_by: uuid.UUID | None
    merge_conflicts_resolved: bool | None
    
    # Authorship
    created_by: uuid.UUID = Field(foreign_key="users.id")
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime | None
```

### Secrets Version Tracking

**Credential Reference Diffing**
- When an agent's credential references change between versions, the diff explicitly shows:
  - Which credentials were **added** (new connector integrations)
  - Which credentials were **removed** (removed connector integrations)
  - Which credentials were **modified** (changed Vault paths, changed auth methods)
  - Only paths are shown — NEVER credential values
- Secrets compatibility check on rollback:
  ```python
  class SecretsCompatibilityChecker:
      """Verifies credential compatibility before rollback or promotion."""
      
      async def check(self, target_version: AgentVersion, 
                       environment: str) -> SecretsCompatibilityResult:
          issues = []
          
          for cred_ref in target_version.credential_refs:
              # Resolve environment-specific Vault path
              vault_path = cred_ref.vault_path_pattern.format(
                  tenant_id=target_version.tenant_id,
                  env=environment
              )
              
              # 1. Check if secret exists in Vault
              exists = await self.vault_client.secret_exists(vault_path)
              if not exists:
                  issues.append(SecretsIssue(
                      severity="error" if cred_ref.required else "warning",
                      credential=cred_ref.connector_type,
                      vault_path=vault_path,
                      issue="Secret does not exist in target environment",
                      remediation=f"Configure credentials at {cred_ref.vault_path_pattern}"
                  ))
                  continue
              
              # 2. Check if secret has required fields
              secret_metadata = await self.vault_client.get_metadata(vault_path)
              for field in cred_ref.required_fields:
                  if field not in secret_metadata.get("keys", []):
                      issues.append(SecretsIssue(
                          severity="error",
                          credential=cred_ref.connector_type,
                          vault_path=vault_path,
                          issue=f"Missing required field: {field}",
                          remediation=f"Add '{field}' to the secret at {vault_path}"
                      ))
              
              # 3. Check if secret is expired
              if secret_metadata.get("expires_at"):
                  expires_at = datetime.fromisoformat(secret_metadata["expires_at"])
                  if expires_at < datetime.utcnow():
                      issues.append(SecretsIssue(
                          severity="error",
                          credential=cred_ref.connector_type,
                          vault_path=vault_path,
                          issue="Credential has expired",
                          remediation="Rotate or renew the credential"
                      ))
          
          return SecretsCompatibilityResult(
              compatible=all(i.severity != "error" for i in issues),
              issues=issues
          )
  ```

### Git-Like Workflow

**Branch, Merge, Diff, Cherry-Pick**
```python
class VersionControlService:
    """Git-like version control operations for agent definitions."""
    
    async def create_branch(self, agent_id: uuid.UUID, branch_name: str,
                            base_version_id: uuid.UUID, user: AuthenticatedUser) -> VersionBranch:
        """Create a new branch from a specific version."""
        base = await self.version_repo.get(base_version_id)
        branch = VersionBranch(
            agent_id=agent_id,
            name=branch_name,
            head_version_id=base_version_id,
            base_version_id=base_version_id,
            created_by=user.id,
            tenant_id=user.tenant_id
        )
        await self.branch_repo.create(branch)
        await self.audit("branch.created", agent_id, user, {"branch": branch_name})
        return branch
    
    async def merge(self, agent_id: uuid.UUID, source_branch: str,
                    target_branch: str, user: AuthenticatedUser,
                    strategy: Literal["fast_forward", "three_way"] = "three_way"
                    ) -> MergeResult:
        """Merge one branch into another with conflict detection."""
        source = await self.branch_repo.get_by_name(agent_id, source_branch)
        target = await self.branch_repo.get_by_name(agent_id, target_branch)
        
        source_version = await self.version_repo.get(source.head_version_id)
        target_version = await self.version_repo.get(target.head_version_id)
        
        # Detect conflicts
        conflicts = await self.detect_conflicts(source_version, target_version)
        
        if conflicts and not conflicts.auto_resolvable:
            return MergeResult(
                status="conflicts",
                conflicts=conflicts,
                message="Manual conflict resolution required"
            )
        
        # Create merged version
        merged_definition = await self.merge_definitions(
            source_version.graph_definition,
            target_version.graph_definition,
            strategy
        )
        
        merged_version = await self.create_version(
            agent_id=agent_id,
            graph_definition=merged_definition,
            change_type="merge",
            change_reason=f"Merged {source_branch} into {target_branch}",
            branch=target_branch,
            parent_version_id=target_version.id,
            merge_source_id=source_version.id,
            user=user
        )
        
        # Update branch head
        target.head_version_id = merged_version.id
        source.status = "merged"
        source.merged_into = target_branch
        source.merged_at = datetime.utcnow()
        source.merged_by = user.id
        
        await self.audit("branch.merged", agent_id, user, {
            "source": source_branch, "target": target_branch
        })
        
        return MergeResult(status="success", version=merged_version)
    
    async def diff(self, version_a_id: uuid.UUID, 
                   version_b_id: uuid.UUID) -> VersionDiff:
        """Compute structured diff between two versions."""
        a = await self.version_repo.get(version_a_id)
        b = await self.version_repo.get(version_b_id)
        
        return VersionDiff(
            source_version_id=a.id,
            target_version_id=b.id,
            source_version_string=a.version_string,
            target_version_string=b.version_string,
            nodes_added=self.diff_nodes_added(a.graph_definition, b.graph_definition),
            nodes_removed=self.diff_nodes_removed(a.graph_definition, b.graph_definition),
            nodes_modified=self.diff_nodes_modified(a.graph_definition, b.graph_definition),
            edges_added=self.diff_edges_added(a.graph_definition, b.graph_definition),
            edges_removed=self.diff_edges_removed(a.graph_definition, b.graph_definition),
            edges_modified=self.diff_edges_modified(a.graph_definition, b.graph_definition),
            config_diff=jsonpatch.make_patch(a.config, b.config).to_string(),
            credentials_added=self.diff_creds_added(a.credential_refs, b.credential_refs),
            credentials_removed=self.diff_creds_removed(a.credential_refs, b.credential_refs),
            credentials_modified=self.diff_creds_modified(a.credential_refs, b.credential_refs),
            connectors_added=[c for c in b.connector_refs if c not in a.connector_refs],
            connectors_removed=[c for c in a.connector_refs if c not in b.connector_refs],
            models_added=[m for m in b.model_refs if m not in a.model_refs],
            models_removed=[m for m in a.model_refs if m not in b.model_refs],
            python_diff=self.unified_diff(a.python_source, b.python_source),
            dependency_changes=self.diff_dependencies(a.dependencies, b.dependencies),
            change_magnitude=self.classify_magnitude(a, b),
            auto_summary=await self.generate_summary(a, b)  # LLM-generated
        )
    
    async def cherry_pick(self, agent_id: uuid.UUID, source_version_id: uuid.UUID,
                          target_branch: str, nodes: list[str],
                          user: AuthenticatedUser) -> AgentVersion:
        """Cherry-pick specific nodes/changes from one version to a branch."""
        source = await self.version_repo.get(source_version_id)
        target = await self.branch_repo.get_by_name(agent_id, target_branch)
        target_version = await self.version_repo.get(target.head_version_id)
        
        # Apply selected node changes to target
        new_definition = self.apply_node_changes(
            target_version.graph_definition,
            source.graph_definition,
            nodes
        )
        
        return await self.create_version(
            agent_id=agent_id,
            graph_definition=new_definition,
            change_type="cherry_pick",
            change_reason=f"Cherry-picked nodes {nodes} from {source.version_string}",
            branch=target_branch,
            parent_version_id=target_version.id,
            user=user
        )
```

**Visual Diff in React Flow**
- Side-by-side canvas comparison showing:
  - **Added nodes**: highlighted in green with "+" badge
  - **Removed nodes**: highlighted in red with "-" badge (shown as ghost nodes)
  - **Modified nodes**: highlighted in yellow with "~" badge, config changes shown on hover
  - **Added edges**: green dashed lines
  - **Removed edges**: red dashed lines
  - **Modified edges**: yellow lines with condition change tooltip

### Deployment Promotion

**Environment Pipeline: dev → staging → prod**
```python
class DeploymentPipeline(SQLModel, table=True):
    """Manages promotion of agent versions through environments."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    agent_id: uuid.UUID = Field(foreign_key="agents.id")
    version_id: uuid.UUID = Field(foreign_key="agent_versions.id")
    
    # Pipeline state
    source_environment: str                    # "dev", "staging"
    target_environment: str                    # "staging", "prod"
    status: Literal["pending", "pre_checks", "awaiting_approval", 
                     "approved", "deploying", "deployed", "failed", "rejected"] = "pending"
    
    # Pre-flight checks
    pre_checks: list[PreFlightCheck] = Field(default_factory=list)
    all_checks_passed: bool = False
    
    # Approval
    requires_approval: bool = True
    approval_required_roles: list[str] = ["workspace_admin", "tenant_admin"]
    approved_by: uuid.UUID | None
    approved_at: datetime | None
    approval_reason: str | None
    rejection_reason: str | None
    
    # Change reason (required for production)
    change_reason: str                         # Required field
    change_ticket: str | None                  # Jira/ServiceNow ticket reference
    
    # Environment-specific config
    environment_overrides: dict = Field(default_factory=dict)
    vault_path_mapping: dict = Field(default_factory=dict)
    # Example: {"archon/dev/connectors/sf" → "archon/prod/connectors/sf"}
    
    # Authorship
    initiated_by: uuid.UUID = Field(foreign_key="users.id")
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    deployed_at: datetime | None

class PreFlightCheck(BaseModel):
    """A single pre-flight check before deployment promotion."""
    name: str
    status: Literal["pending", "running", "passed", "failed", "skipped"]
    message: str | None
    required: bool = True
    duration_ms: int | None
```

**Promotion Service**
```python
class PromotionService:
    """Handles deployment promotion with pre-flight checks and approval gates."""
    
    PRE_FLIGHT_CHECKS = [
        "secrets_compatibility",      # All credential refs exist in target env
        "connector_compatibility",    # All connectors available in target env
        "model_availability",         # All models accessible in target env
        "test_suite_passed",          # Agent's test suite passes
        "security_scan",             # Agent-11 DLP scan passes
        "cost_estimation",           # Cost within budget for target env
        "version_signature",         # Version signature is valid
        "hash_chain_integrity",      # Hash chain is intact
    ]
    
    async def initiate_promotion(self, agent_id: uuid.UUID, version_id: uuid.UUID,
                                  target_env: str, change_reason: str,
                                  user: AuthenticatedUser) -> DeploymentPipeline:
        """Start the promotion pipeline."""
        version = await self.version_repo.get(version_id)
        
        # Require change reason for production
        if target_env == "prod" and not change_reason:
            raise ValueError("Change reason is required for production deployments")
        
        pipeline = DeploymentPipeline(
            agent_id=agent_id,
            version_id=version_id,
            source_environment=self.current_env(version),
            target_environment=target_env,
            change_reason=change_reason,
            initiated_by=user.id,
            tenant_id=user.tenant_id,
            requires_approval=(target_env == "prod"),
            vault_path_mapping=self.compute_vault_mapping(version, target_env)
        )
        
        # Run pre-flight checks
        pipeline.status = "pre_checks"
        for check_name in self.PRE_FLIGHT_CHECKS:
            result = await self.run_check(check_name, version, target_env)
            pipeline.pre_checks.append(result)
        
        pipeline.all_checks_passed = all(
            c.status == "passed" for c in pipeline.pre_checks if c.required
        )
        
        if not pipeline.all_checks_passed:
            pipeline.status = "failed"
        elif pipeline.requires_approval:
            pipeline.status = "awaiting_approval"
            await self.notify_approvers(pipeline)
        else:
            await self.deploy(pipeline)
        
        return pipeline
    
    def compute_vault_mapping(self, version: AgentVersion, target_env: str) -> dict:
        """Map Vault paths from source to target environment."""
        mapping = {}
        for cred_ref in version.credential_refs:
            source_path = cred_ref.vault_path_pattern.format(
                tenant_id=version.tenant_id, env=self.current_env(version)
            )
            target_path = cred_ref.vault_path_pattern.format(
                tenant_id=version.tenant_id, env=target_env
            )
            mapping[source_path] = target_path
        return mapping
```

### Rollback with Safety

**Safe Rollback Service**
```python
class RollbackService:
    """Handles safe rollbacks with pre-flight compatibility checks."""
    
    async def rollback(self, agent_id: uuid.UUID, target_version_id: uuid.UUID,
                       environment: str, reason: str,
                       user: AuthenticatedUser) -> RollbackResult:
        """Rollback to a previous version with safety checks."""
        current = await self.get_current_version(agent_id, environment)
        target = await self.version_repo.get(target_version_id)
        
        # 1. Secrets compatibility check
        secrets_check = await self.secrets_checker.check(target, environment)
        if not secrets_check.compatible:
            return RollbackResult(
                status="blocked",
                reason="secrets_incompatible",
                issues=secrets_check.issues,
                message="Target version references secrets that don't exist in this environment"
            )
        
        # 2. Connector compatibility check
        connector_check = await self.connector_checker.check(target, environment)
        if not connector_check.compatible:
            return RollbackResult(
                status="blocked",
                reason="connectors_incompatible",
                issues=connector_check.issues
            )
        
        # 3. Model availability check
        model_check = await self.model_checker.check(target)
        if not model_check.all_available:
            return RollbackResult(
                status="blocked",
                reason="models_unavailable",
                issues=model_check.issues
            )
        
        # 4. Create rollback version (preserves history — rollbacks never delete)
        rollback_version = await self.version_service.create_version(
            agent_id=agent_id,
            graph_definition=target.graph_definition,
            python_source=target.python_source,
            config=target.config,
            dependencies=target.dependencies,
            credential_refs=target.credential_refs,
            change_type="rollback",
            change_reason=f"Rollback to {target.version_string}: {reason}",
            branch=current.branch,
            parent_version_id=current.id,
            user=user
        )
        
        # 5. Deploy rollback version to environment
        await self.deploy(rollback_version, environment)
        
        # 6. Audit log
        await self.audit_service.log(AuditEntry(
            action="agent.version.rollback",
            actor_id=user.id,
            resource_type="agent_version",
            resource_id=str(rollback_version.id),
            details={
                "from_version": current.version_string,
                "to_version": target.version_string,
                "rollback_version": rollback_version.version_string,
                "environment": environment,
                "reason": reason,
                "pre_checks": {
                    "secrets": secrets_check.dict(),
                    "connectors": connector_check.dict(),
                    "models": model_check.dict()
                }
            }
        ))
        
        return RollbackResult(
            status="success",
            rollback_version=rollback_version,
            rolled_back_from=current.version_string,
            rolled_back_to=target.version_string
        )
```

### Change Audit

**Comprehensive Audit Logging**
- Every version change logged in AuditLog (Agent-01) with:
  - Actor (who made the change — from JWT)
  - Action (create, update, rollback, merge, cherry_pick, promote, branch)
  - Change reason (free text — REQUIRED for production deployments)
  - Diff summary (auto-generated: "Added 2 nodes, modified 1 connector, removed S3 credential ref")
  - Environment (which environment was affected)
  - Approval chain (who approved, when, with what justification)
- Required "change reason" for production:
  ```python
  class ProductionChangePolicy:
      async def enforce(self, pipeline: DeploymentPipeline):
          if pipeline.target_environment == "prod":
              if not pipeline.change_reason or len(pipeline.change_reason) < 10:
                  raise PolicyViolation(
                      "Production deployments require a change reason (min 10 characters)"
                  )
              if not pipeline.change_ticket:
                  # Warning, not blocking (configurable per tenant)
                  await self.warn("No change ticket reference provided")
  ```

### Compliance

**Version Retention Policies**
```python
class RetentionPolicy(SQLModel, table=True):
    """Per-tenant version retention policy for compliance."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", unique=True)
    
    # Retention rules
    minimum_retention_days: int = 90           # Minimum: 90 days for regulated industries
    maximum_retention_days: int | None         # None = forever
    production_retention_days: int = 365       # Production versions kept longer
    
    # What to retain
    retain_graph: bool = True                  # Always retain graph definition
    retain_source: bool = True                 # Retain Python source
    retain_config: bool = True                 # Retain configuration
    retain_audit_trail: bool = True            # Always retain audit trail
    retain_signatures: bool = True             # Always retain signatures
    
    # Compliance metadata
    regulatory_framework: str | None           # "SOC2", "HIPAA", "GDPR", "PCI-DSS"
    data_classification: str | None            # "public", "internal", "confidential", "restricted"
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime | None

class ComplianceExporter:
    """Export version history for compliance audits."""
    
    async def export(self, agent_id: uuid.UUID, 
                     format: Literal["json", "pdf"],
                     date_range: tuple[datetime, datetime] | None = None
                     ) -> bytes:
        versions = await self.repo.get_versions(agent_id, date_range=date_range)
        audit_entries = await self.audit_repo.get_for_agent(agent_id, date_range=date_range)
        
        export_data = ComplianceExportData(
            agent_id=agent_id,
            export_date=datetime.utcnow(),
            versions=[self.version_to_export(v) for v in versions],
            audit_trail=[self.audit_to_export(a) for a in audit_entries],
            hash_chain_verification=await self.verify_chain(agent_id),
            retention_policy=await self.get_retention_policy(versions[0].tenant_id)
        )
        
        if format == "json":
            return json.dumps(export_data.dict(), indent=2, default=str).encode()
        elif format == "pdf":
            return await self.render_pdf(export_data)
```

## Output Structure

```
backend/
├── app/
│   ├── services/
│   │   └── versioning/
│   │       ├── __init__.py
│   │       ├── version_service.py       # Core version CRUD + snapshot creation
│   │       ├── version_control.py       # Git-like operations (branch, merge, diff, cherry-pick)
│   │       ├── signer.py               # Version signing (Ed25519 via Vault)
│   │       ├── hash_chain.py           # Hash chain maintenance + verification
│   │       ├── differ.py               # Structured diff computation
│   │       ├── secrets_tracker.py      # Credential ref tracking + diffing
│   │       ├── secrets_compatibility.py # Pre-rollback/promotion secrets checks
│   │       ├── promotion.py            # Deployment promotion pipeline
│   │       ├── rollback.py             # Safe rollback with pre-flight checks
│   │       ├── compliance.py           # Retention policies + compliance export
│   │       ├── audit.py                # Version-specific audit logging
│   │       └── schemas.py              # Pydantic models for all version types
│   ├── routers/
│   │   ├── versions.py                 # Version CRUD + diff endpoints
│   │   ├── branches.py                 # Branch management endpoints
│   │   ├── promotions.py               # Deployment promotion endpoints
│   │   └── compliance.py               # Compliance export endpoints
│   ├── models/
│   │   ├── version.py                  # AgentVersion, VersionBranch models
│   │   ├── promotion.py                # DeploymentPipeline model
│   │   └── retention.py                # RetentionPolicy model
│   └── auth/
│       └── version_permissions.py      # Version-specific RBAC checks
├── tests/
│   └── test_versioning/
│       ├── __init__.py
│       ├── conftest.py                 # Version test fixtures + factories
│       ├── test_version_crud.py        # Create, read, list versions
│       ├── test_signing.py             # Signature creation + verification
│       ├── test_hash_chain.py          # Hash chain integrity tests
│       ├── test_diff.py                # Structured diff tests
│       ├── test_secrets_tracker.py     # Credential ref diffing tests
│       ├── test_secrets_compat.py      # Secrets compatibility check tests
│       ├── test_branching.py           # Branch, merge, cherry-pick tests
│       ├── test_promotion.py           # Deployment promotion tests
│       ├── test_rollback.py            # Rollback with safety checks tests
│       ├── test_compliance.py          # Retention policy + export tests
│       ├── test_audit.py               # Version audit logging tests
│       └── test_e2e_versioning.py      # End-to-end version lifecycle tests
└── alembic/
    └── versions/
        └── xxx_add_versioning_tables.py # Migration for versioning tables

frontend/
└── src/
    └── components/
        └── versioning/
            ├── VersionHistory.tsx       # Version timeline view
            ├── VersionDetail.tsx        # Version detail with metadata
            ├── VisualDiff.tsx           # Side-by-side React Flow diff
            ├── JsonDiff.tsx             # JSON diff viewer
            ├── CodeDiff.tsx             # Python source diff viewer
            ├── CredentialDiff.tsx        # Credential ref change display
            ├── BranchManager.tsx        # Branch list, create, delete
            ├── MergeDialog.tsx          # Merge branch UI with conflict resolution
            ├── PromotionPipeline.tsx    # Promotion pipeline visualization
            ├── PromotionApproval.tsx    # Approval gate UI
            ├── RollbackDialog.tsx       # Rollback with safety check results
            ├── ComplianceExport.tsx     # Compliance export dialog
            └── HashChainVerifier.tsx    # Hash chain integrity viewer
```

## API Endpoints (Complete)

```
# Version CRUD
GET    /api/v1/agents/{agent_id}/versions                    # List versions (paginated)
POST   /api/v1/agents/{agent_id}/versions                    # Create new version
GET    /api/v1/agents/{agent_id}/versions/{vid}              # Get version details
GET    /api/v1/agents/{agent_id}/versions/latest             # Get latest version
GET    /api/v1/agents/{agent_id}/versions/{vid}/graph        # Get graph definition
GET    /api/v1/agents/{agent_id}/versions/{vid}/source       # Get Python source
GET    /api/v1/agents/{agent_id}/versions/{vid}/config       # Get configuration

# Diff
GET    /api/v1/agents/{agent_id}/versions/{v1}/diff/{v2}     # Structured diff between versions
GET    /api/v1/agents/{agent_id}/versions/{v1}/visual-diff/{v2}  # Visual diff (React Flow JSON)
GET    /api/v1/agents/{agent_id}/versions/{vid}/credentials-diff  # Credential ref changes vs parent

# Signing & Integrity
POST   /api/v1/agents/{agent_id}/versions/{vid}/sign         # Sign version
GET    /api/v1/agents/{agent_id}/versions/{vid}/verify       # Verify version signature
GET    /api/v1/agents/{agent_id}/versions/chain/verify       # Verify full hash chain

# Branching
GET    /api/v1/agents/{agent_id}/branches                    # List branches
POST   /api/v1/agents/{agent_id}/branches                    # Create branch
GET    /api/v1/agents/{agent_id}/branches/{name}             # Get branch details
DELETE /api/v1/agents/{agent_id}/branches/{name}             # Delete branch
POST   /api/v1/agents/{agent_id}/branches/{name}/merge       # Merge branch
GET    /api/v1/agents/{agent_id}/branches/{b1}/diff/{b2}     # Diff between branches
POST   /api/v1/agents/{agent_id}/cherry-pick                 # Cherry-pick nodes

# Deployment Promotion
POST   /api/v1/agents/{agent_id}/promote                     # Initiate promotion pipeline
GET    /api/v1/agents/{agent_id}/promotions                  # List promotion history
GET    /api/v1/agents/{agent_id}/promotions/{pid}            # Get promotion details
POST   /api/v1/agents/{agent_id}/promotions/{pid}/approve    # Approve promotion
POST   /api/v1/agents/{agent_id}/promotions/{pid}/reject     # Reject promotion
GET    /api/v1/agents/{agent_id}/deployments                 # List deployments per environment

# Rollback
POST   /api/v1/agents/{agent_id}/rollback                    # Initiate rollback
GET    /api/v1/agents/{agent_id}/rollback/check              # Pre-rollback compatibility check
GET    /api/v1/agents/{agent_id}/rollback/history             # Rollback history

# Compliance
GET    /api/v1/agents/{agent_id}/versions/export             # Export version history (JSON/PDF)
GET    /api/v1/tenants/{tid}/retention-policy                 # Get retention policy
PUT    /api/v1/tenants/{tid}/retention-policy                 # Update retention policy
GET    /api/v1/agents/{agent_id}/compliance/report            # Full compliance report

# Audit
GET    /api/v1/agents/{agent_id}/audit                       # Version change audit trail
GET    /api/v1/agents/{agent_id}/audit/export                 # Export audit trail (CSV/JSON)
```

## Verify Commands

```bash
# Versioning module importable
cd ~/Scripts/Archon && python -c "
from backend.app.services.versioning.version_service import VersionService
from backend.app.services.versioning.version_control import VersionControlService
from backend.app.services.versioning.signer import VersionSigner
from backend.app.services.versioning.hash_chain import VersionHashChain
from backend.app.services.versioning.differ import VersionDiffer
from backend.app.services.versioning.secrets_tracker import SecretsTracker
from backend.app.services.versioning.secrets_compatibility import SecretsCompatibilityChecker
from backend.app.services.versioning.promotion import PromotionService
from backend.app.services.versioning.rollback import RollbackService
from backend.app.services.versioning.compliance import ComplianceExporter, RetentionPolicy
print('All versioning services OK')
"

# Data models importable
cd ~/Scripts/Archon && python -c "
from backend.app.models.version import AgentVersion, VersionBranch
from backend.app.models.promotion import DeploymentPipeline
from backend.app.models.retention import RetentionPolicy
print('All versioning models OK')
"

# Tests pass
cd ~/Scripts/Archon/backend && python -m pytest tests/test_versioning/ --tb=short -q

# API routes registered
cd ~/Scripts/Archon && python -c "
from backend.app.main import app
routes = [r.path for r in app.routes]
assert '/api/v1/agents/{agent_id}/versions' in str(routes) or 'versions' in str(routes)
print('Versioning routes OK')
"

# Hash chain verification works
cd ~/Scripts/Archon && python -c "
from backend.app.services.versioning.hash_chain import VersionHashChain
chain = VersionHashChain()
assert chain is not None
print('Hash chain module OK')
"

# Signing module works
cd ~/Scripts/Archon && python -c "
from backend.app.services.versioning.signer import VersionSigner
signer = VersionSigner()
assert signer is not None
print('Signing module OK')
"

# No hardcoded secrets in versioning code
cd ~/Scripts/Archon && ! grep -rn 'signing_key\s*=\s*\"[^\"]*\"' --include='*.py' backend/app/services/versioning/ || echo 'FAIL: hardcoded secrets found'
```

## Learnings Protocol

Before starting, read `.sdd/learnings/*.md` for known pitfalls from previous sessions.
After completing work, report any pitfalls or patterns discovered so the orchestrator can capture them via `node ~/Projects/copilot-sdd/dist/cli.js learn`.

## Acceptance Criteria

- [ ] Every save creates a new immutable version with full snapshot (graph, code, config, dependencies, credential refs)
- [ ] Versions signed with creator's identity from Keycloak JWT — signature verification passes on valid versions, fails on tampered content
- [ ] Hash chain is tamper-evident: modify any version row → `verify_chain()` detects the break and identifies the exact version
- [ ] Structured diff between any two versions shows: nodes added/removed/modified, edges changed, config diff, credential ref changes (paths only, NEVER values)
- [ ] Visual diff renders correctly in React Flow: green for added, red for removed, yellow for modified nodes/edges
- [ ] Credential ref tracking: when agent's Vault paths change between versions, diff explicitly shows added/removed/modified paths
- [ ] Secrets compatibility check on rollback: blocks rollback if target version references non-existent Vault paths in target environment
- [ ] Git-like branching: create branch, commit to branch, merge branch (with auto-conflict resolution for simple cases)
- [ ] Cherry-pick: selectively apply node changes from one version to another branch
- [ ] Deployment promotion: dev → staging → prod with pre-flight checks (secrets, connectors, models, security scan, cost estimate)
- [ ] Environment-specific Vault paths: `archon/dev/...` vs `archon/prod/...` correctly mapped during promotion
- [ ] Production deployments require change reason (min 10 characters) — rejected without it
- [ ] Approval gate: production promotions require workspace_admin or tenant_admin approval
- [ ] Rollback creates a new version (never deletes history) and preserves full audit trail
- [ ] Version history loads within 200ms for agents with 100+ versions
- [ ] Compliance export: version history exportable as JSON and PDF with hash chain verification included
- [ ] Retention policy: versions retained for minimum 90 days (configurable per tenant, extendable to 365+ for regulated industries)
- [ ] Zero credential values in diffs, exports, logs, or API responses — only Vault paths
