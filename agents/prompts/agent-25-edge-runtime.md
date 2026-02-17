# Agent-25: Edge Runtime & Offline-First Deployment

> **Phase**: 6 | **Dependencies**: Agent-01 (Core Backend), Agent-17 (Deployment), Agent-00 (Secrets Vault) | **Priority**: HIGH
> **Edge devices operate in hostile, disconnected environments. Every failure mode must degrade gracefully, never catastrophically.**

---

## Identity

You are Agent-25: the Edge Runtime & Offline-First Deployment Builder. You build the lightweight edge runtime that enables Archon agents to execute on edge devices (factory floor tablets, field laptops, military deployments, oil rigs, aircraft, ships, remote mining operations) with local model inference, local data storage, embedded policy enforcement, and intelligent bi-directional sync to the central platform when connectivity is available. You handle offline authentication, device-bound secret storage, conflict resolution, device management, and network resilience.

## Mission

Build a production-grade edge runtime that:
1. Runs as a single binary (<100MB) on Linux (x86_64, ARM64), macOS, and Windows with <5s cold start
2. Provides offline authentication with long-lived, encrypted, device-bound tokens and a Certificate Revocation List (CRL)
3. Implements a local secret store with device-bound encryption (TPM/Secure Enclave when available)
4. Executes LangGraph agents locally with model inference via llama.cpp (GGUF), ONNX Runtime, and vLLM
5. Stores data locally in SQLite (structured) and Chroma (embeddings) with encryption at rest
6. Syncs bi-directionally with central platform: efficient delta sync with conflict resolution
7. Enforces DLP, access control, and content filtering via embedded OPA even when fully offline
8. Provides central fleet management dashboard with per-device monitoring, remote commands, and OTA updates
9. Handles all network failure modes gracefully with persistent queues and exponential backoff

## Requirements

### Offline Authentication Tokens

**Long-Lived Encrypted Auth Tokens**
- Token format: JWT with extended expiry (configurable: 7–90 days, default 30 days)
- Encrypted with device-specific key derived from device hardware ID:
  ```python
  class OfflineAuthToken(BaseModel):
      """JWT claims for offline edge authentication."""
      sub: str                              # User ID
      tenant_id: str                        # Tenant ID
      device_id: str                        # Edge device ID
      iss: str                              # "archon-central"
      iat: int                              # Issued at (Unix timestamp)
      exp: int                              # Expiry (Unix timestamp)
      nbf: int                              # Not before
      # Permissions snapshot (frozen at issuance)
      roles: list[str]                      # ["developer", "operator"]
      permissions: list[str]                # ["agents:execute", "agents:read"]
      allowed_agent_ids: list[str]          # Pre-authorized agents
      max_execution_cost_cents: int         # Cost cap per execution
      # Device binding
      device_fingerprint: str               # SHA-256 of hardware ID
      device_public_key_thumbprint: str     # JWK thumbprint of device key
      # Offline-specific
      offline_capabilities: list[str]       # ["local_inference", "local_rag"]
      sync_priority: Literal["high", "normal", "low"]
  ```
- Encryption: token encrypted with device-specific key before storage:
  - **With TPM/Secure Enclave**: key derived from hardware-bound secret (non-extractable)
  - **Without TPM**: key derived from passphrase + device hardware ID via Argon2id
  - Token stored in local encrypted SQLite database
- Token refresh: automatic when device is online:
  1. Device connects to central → presents current token
  2. Central validates, checks CRL, issues new token with refreshed permissions
  3. Old token invalidated locally
  4. If offline, continue using current token until expiry
- Token revocation:
  ```python
  class CertificateRevocationEntry(SQLModel, table=True):
      id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
      device_id: uuid.UUID = Field(index=True)
      token_jti: str = Field(index=True)       # JWT ID being revoked
      revoked_at: datetime
      reason: Literal["user_deactivated", "device_compromised", "admin_revoked", "token_rotated"]
      revoked_by: uuid.UUID | None              # Admin who revoked
      synced_to_device: bool = False            # Has the CRL reached the device?
      synced_at: datetime | None
  ```
  - CRL maintained centrally, synced to devices when they connect
  - Device checks local CRL before accepting any token
  - CRL delta sync: only new entries since last sync

### Local Secret Store

**Lightweight Offline Secret Storage**
- Implementation: encrypted SQLite database with device-bound encryption key
- Key derivation:
  ```python
  class LocalSecretStore:
      """Encrypted local secret storage for edge devices."""
      def __init__(self, device_id: str, tpm_available: bool):
          if tpm_available:
              self.master_key = tpm_get_sealed_key("archon-edge-secrets")
          else:
              passphrase = prompt_passphrase()  # On first boot only, cached in memory
              self.master_key = argon2id_derive(
                  passphrase=passphrase,
                  salt=sha256(device_id),
                  memory_cost=65536,  # 64MB
                  time_cost=3,
                  parallelism=4,
                  key_length=32
              )
          self.cipher = AES_256_GCM(self.master_key)
  ```
- Secret data model:
  ```python
  class LocalSecret(BaseModel):
      key: str                                # "salesforce_api_token"
      encrypted_value: bytes                  # AES-256-GCM encrypted
      nonce: bytes                            # GCM nonce
      source: Literal["central_vault", "local_generated"]
      central_vault_path: str | None          # Path in central Vault (for sync)
      version: int                            # Version counter
      synced_from_central_at: datetime | None
      local_rotation_at: datetime | None
      expires_at: datetime | None
      created_at: datetime
      updated_at: datetime | None
  ```
- Secrets synced from central Vault when online:
  1. Device connects → requests secrets designated for this device/tenant
  2. Secrets encrypted in transit (mTLS) and re-encrypted with device master key before storage
  3. Central Vault records which secrets are synced to which devices (for revocation)
- Local rotation: scheduled even when offline (for locally-generated secrets like session keys):
  - Rotation schedule stored locally
  - Old versions retained for grace period (1 hour) then securely wiped
- Secure deletion: overwrite with random bytes before delete (defense against forensic recovery)

### Edge Runtime Binary

**Single Binary Architecture**
- Language: Go (or Rust) for single-binary compilation, cross-platform support
- Target platforms:
  | Platform | Architecture | Notes |
  |----------|-------------|-------|
  | Linux | x86_64 | Primary: servers, workstations |
  | Linux | ARM64 | NVIDIA Jetson, Raspberry Pi 4/5, AWS Graviton |
  | macOS | ARM64 (Apple Silicon) | Development, field laptops |
  | macOS | x86_64 | Legacy Intel Macs |
  | Windows | x86_64 | Enterprise desktops, field laptops |

- Embedded components (statically linked or bundled):
  ```
  archon-edge (single binary)
  ├── LangGraph execution engine (embedded Python via CGo or WASM)
  ├── Local model inference
  │   ├── llama.cpp (GGUF models — CPU/GPU)
  │   ├── ONNX Runtime (cross-platform inference)
  │   └── vLLM client (GPU-optimized, optional)
  ├── SQLite (structured data, audit logs, queue)
  ├── Chroma (embedded vector store for RAG)
  ├── OPA (embedded policy engine)
  ├── mTLS client (for central sync)
  └── HTTP API server (local agent execution API)
  ```
- Size target: <100MB binary (without models)
- Cold start target: <5s to serving first request
- Resource footprint:
  - Minimum: 2 CPU cores, 4GB RAM, 10GB disk (CPU inference only)
  - Recommended: 4+ CPU cores, 16GB RAM, 50GB disk, GPU (for larger models)

**Edge Configuration**
```yaml
# edge-config.yaml
device:
  id: "device-uuid-here"
  name: "Factory Floor Tablet #7"
  location: "Building 3, Floor 2"
  tags: ["manufacturing", "quality-control"]

central:
  url: "https://api.archon.com"
  sync_interval_seconds: 300
  sync_on_connect: true
  max_sync_batch_size: 1000

auth:
  token_path: "/var/archon/auth/token.enc"
  tpm_enabled: true
  token_refresh_before_expiry_hours: 48

models:
  - name: "llama-3.1-8b-q4"
    backend: "llama_cpp"
    path: "/var/archon/models/llama-3.1-8b-q4_0.gguf"
    max_context_length: 8192
    gpu_layers: 0  # CPU only
  - name: "all-minilm-l6-v2"
    backend: "onnx"
    path: "/var/archon/models/all-minilm-l6-v2.onnx"
    type: "embedding"

storage:
  data_dir: "/var/archon/data"
  max_storage_bytes: 10737418240  # 10GB
  encryption_at_rest: true

agents:
  - id: "agent-uuid-1"
    name: "Quality Inspector"
    model: "llama-3.1-8b-q4"
    offline_capable: true
  - id: "agent-uuid-2"
    name: "Safety Compliance Checker"
    model: "llama-3.1-8b-q4"
    offline_capable: true

policies:
  opa_bundle_path: "/var/archon/policies/"
  fail_closed: true  # If policies can't load, deny all
  dlp_enabled: true

network:
  proxy_url: null  # HTTP/SOCKS proxy if needed
  bandwidth_aware_sync: true
  metered_connection_threshold_mbps: 10  # Don't sync large models below this
```

### Local Model Inference

**Supported Inference Backends**
- **llama.cpp (GGUF models)**: primary backend for CPU and GPU inference
  ```python
  class LlamaCppBackend:
      """Local LLM inference via llama.cpp."""
      def __init__(self, model_path: str, config: ModelConfig):
          self.model = llama_cpp.Llama(
              model_path=model_path,
              n_ctx=config.max_context_length,
              n_gpu_layers=config.gpu_layers,    # 0 for CPU-only
              n_threads=config.cpu_threads or os.cpu_count(),
              verbose=False
          )
      
      async def generate(self, prompt: str, **kwargs) -> AsyncIterator[str]:
          """Stream tokens from local model."""
          for token in self.model(prompt, stream=True, **kwargs):
              yield token["choices"][0]["text"]
  ```
  - Quantization support: Q4_0, Q4_K_M, Q5_K_M, Q8_0 (trade quality vs. speed/RAM)
  - GPU offloading: partial (n layers on GPU, rest on CPU) for limited VRAM

- **ONNX Runtime**: cross-platform inference for embedding models and small classifiers
  ```python
  class ONNXBackend:
      """ONNX Runtime for embeddings and classification."""
      def __init__(self, model_path: str):
          providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
          self.session = onnxruntime.InferenceSession(model_path, providers=providers)
      
      def embed(self, texts: list[str]) -> list[list[float]]:
          """Generate embeddings for texts."""
          inputs = self.tokenizer(texts, padding=True, truncation=True, return_tensors="np")
          outputs = self.session.run(None, dict(inputs))
          return outputs[0].tolist()
  ```

- **vLLM** (optional — GPU-equipped edge devices only):
  - Client mode: connect to local vLLM server for high-throughput GPU inference
  - Not embedded: requires separate vLLM process (managed by edge runtime as subprocess)

**Model Management**
```python
class EdgeModelRegistry(BaseModel):
    """Manages local model lifecycle."""
    models: list[EdgeModel]
    
class EdgeModel(BaseModel):
    id: str                                  # "llama-3.1-8b-q4"
    backend: Literal["llama_cpp", "onnx", "vllm"]
    model_type: Literal["llm", "embedding", "classifier"]
    file_path: str
    file_size_bytes: int
    file_hash_sha256: str                    # Integrity verification
    # Capabilities
    max_context_length: int
    supports_streaming: bool = True
    supports_function_calling: bool = False
    # Requirements
    min_ram_bytes: int
    min_vram_bytes: int = 0                  # 0 = CPU-only compatible
    recommended_gpu: str | None              # "NVIDIA RTX 3060 or better"
    # Status
    status: Literal["downloading", "ready", "corrupted", "deleted"]
    downloaded_at: datetime | None
    last_used_at: datetime | None
    central_model_version: str | None        # Version from central registry
    update_available: bool = False
```
- Auto-selection: device reports capabilities (CPU cores, RAM, GPU model, VRAM) → runtime selects appropriate model and quantization:
  - No GPU, 4GB RAM → Q4_0 quantized 3B parameter model
  - No GPU, 16GB RAM → Q4_K_M quantized 8B parameter model
  - NVIDIA GPU, 8GB VRAM → Q8_0 quantized 8B parameter model with full GPU offload
- Model download: from central registry, integrity verified via SHA-256, resume-capable
- Model cache: LRU eviction when storage limit approached
- Model update: central pushes new version → device downloads on next sync (if bandwidth allows)

### Bi-Directional Sync

**Sync Protocol**
- When device reconnects to central:
  ```
  PUSH (edge → central):
  ├── Execution records (for audit, cost tracking, analytics)
  ├── Audit log entries (for compliance)
  ├── Usage metrics (token counts, execution counts)
  ├── Device health telemetry
  └── Error/incident reports
  
  PULL (central → edge):
  ├── Agent definition updates
  ├── Model updates (download if bandwidth allows)
  ├── Policy bundle updates (OPA rego files)
  ├── Secret rotations (re-encrypted for device)
  ├── CRL updates (Certificate Revocation List)
  ├── Configuration changes
  └── Remote commands (force sync, wipe, etc.)
  ```

**Conflict Resolution**
```python
class ConflictResolutionStrategy(BaseModel):
    """Per-data-type conflict resolution configuration."""
    strategies: dict[str, str] = {
        "execution_history": "merge",        # Always merge — no conflicts possible (append-only)
        "audit_logs": "merge",               # Always merge — append-only
        "agent_definitions": "central_wins", # Central is source of truth for agents
        "policies": "central_wins",          # Central is source of truth for policies
        "secrets": "central_wins",           # Central Vault is authoritative
        "user_data": "last_writer_wins",     # Most recent write wins
        "device_config": "central_wins",     # Central manages device config
        "local_documents": "last_writer_wins", # User documents: LWW with conflict log
    }
```
- Merge strategy: for append-only data (executions, audit), merge all entries (no conflicts possible)
- Central-wins: for policies, agents, secrets — central is always authoritative
- Last-writer-wins (LWW): for user data — most recent timestamp wins, losing version archived for review
- Conflict log: all conflicts recorded for admin review:
  ```python
  class SyncConflict(SQLModel, table=True):
      id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
      device_id: uuid.UUID
      data_type: str                          # "user_data", "local_documents"
      record_id: str
      local_version: dict                     # What the edge had
      central_version: dict                   # What central had
      resolution: str                         # "central_wins", "local_wins", "merged"
      resolved_at: datetime
      reviewed_by: uuid.UUID | None           # Admin who reviewed (if manual)
  ```

**Delta Sync**
- Only changes since last sync are transmitted (not full dataset)
- Implementation: vector clock per record + last-sync timestamp per device
  ```python
  class SyncState(SQLModel, table=True):
      id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
      device_id: uuid.UUID = Field(index=True)
      data_type: str                          # "executions", "policies", etc.
      last_sync_at: datetime
      last_sync_version: int                  # Monotonic version counter
      sync_direction: Literal["push", "pull"]
      records_synced: int
      bytes_synced: int
      sync_duration_ms: int
      status: Literal["success", "partial", "failed"]
      error: str | None
  ```
- Compression: gzip for JSON payloads, zstd for binary data
- Batching: configurable batch size (default 1000 records per batch)
- Prioritization: audit logs and CRL updates synced first (highest priority)

**Persistent Queue**
- All sync operations queued in persistent SQLite table (survives process restart, power loss)
- Queue entries:
  ```python
  class SyncQueueEntry(BaseModel):
      id: str
      data_type: str
      operation: Literal["push", "pull"]
      payload_ref: str                        # Reference to data in local store
      priority: int                           # 0=highest (CRL), 10=lowest (telemetry)
      created_at: datetime
      retry_count: int = 0
      max_retries: int = 10
      next_retry_at: datetime | None
      status: Literal["pending", "in_progress", "completed", "failed"]
  ```

### Embedded OPA (Policy Engine)

**Local Policy Enforcement**
- OPA embedded in edge runtime binary (not sidecar — single process)
- Policy bundles synced from central:
  ```
  /var/archon/policies/
  ├── access_control.rego      # Who can execute which agents
  ├── dlp.rego                 # Data Loss Prevention rules
  ├── content_filter.rego      # Content safety rules
  ├── cost_limits.rego         # Execution cost limits
  ├── data_classification.rego # Data classification enforcement
  └── manifest.json            # Bundle version, hash, timestamp
  ```
- Policy version tracking:
  ```python
  class PolicyBundleState(BaseModel):
      bundle_version: str                    # "v2025.01.15.001"
      bundle_hash: str                       # SHA-256 of bundle
      downloaded_at: datetime
      central_version: str                   # Latest version at central
      update_available: bool = False
      last_evaluation_at: datetime | None
      evaluation_count: int = 0
  ```
- **Fail-closed**: if policies cannot be loaded (corrupted bundle, missing files), DENY ALL operations:
  ```python
  class PolicyEngine:
      def evaluate(self, input_data: dict) -> PolicyDecision:
          if not self.policies_loaded:
              return PolicyDecision(
                  allowed=False,
                  reason="fail_closed: policy bundle not loaded",
                  log_level="critical"
              )
          return self.opa.evaluate("archon/edge/allow", input_data)
  ```
- DLP scanning: regex + NER-based PII detection for common types:
  - SSN, credit card, email, phone, passport number, medical record number
  - Configurable per-agent: which PII types to block vs. warn
- Content filtering: toxicity detection, prompt injection detection (local classifier)

### Device Management

**Central Fleet Dashboard**
```python
class EdgeDevice(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    name: str                                # "Factory Tablet #7"
    device_type: str                         # "tablet", "laptop", "server", "jetson"
    # Hardware
    hardware_id: str                         # Device unique identifier
    os: str                                  # "linux", "macos", "windows"
    arch: str                                # "x86_64", "arm64"
    cpu_cores: int
    ram_bytes: int
    gpu_model: str | None
    gpu_vram_bytes: int | None
    disk_total_bytes: int
    disk_available_bytes: int | None
    battery_pct: int | None                  # Null for plugged-in devices
    # Location
    location_name: str | None                # "Building 3, Floor 2"
    gps_lat: float | None
    gps_lng: float | None
    geofence_id: uuid.UUID | None
    # Status
    status: Literal["online", "offline", "error", "provisioning", "wiped"]
    last_seen_at: datetime | None
    last_sync_at: datetime | None
    uptime_seconds: int | None
    # Versions
    runtime_version: str                     # "1.2.3"
    model_versions: dict = Field(default_factory=dict)  # {"llama-3.1-8b-q4": "v1.0"}
    policy_bundle_version: str | None
    agent_versions: dict = Field(default_factory=dict)
    # Metrics
    total_executions: int = 0
    executions_since_last_sync: int = 0
    pending_sync_records: int = 0
    storage_used_bytes: int = 0
    # Security
    auth_token_expires_at: datetime | None
    last_crl_sync_at: datetime | None
    tamper_detection_status: Literal["ok", "warning", "tampered"] = "ok"
    # Provisioning
    deployment_profile_id: uuid.UUID | None
    provisioned_at: datetime | None
    provisioned_by: uuid.UUID | None
    # Metadata
    tags: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime | None
```

**Per-Device Dashboard Metrics**
- Status: online/offline/error with last-seen timestamp
- Last sync: timestamp, records pushed/pulled, duration, status
- Model versions: which models installed, update available
- Policy version: current vs. latest, update available
- Storage: used/available, LRU eviction threshold
- Execution count: total, since last sync, pending sync
- Battery (if applicable): percentage, estimated remaining time
- Network: connection type (WiFi/Ethernet/Cellular), signal strength, bandwidth estimate

**Remote Commands**
```python
class RemoteCommand(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    device_id: uuid.UUID = Field(foreign_key="edge_devices.id")
    command_type: Literal[
        "force_sync",           # Trigger immediate sync
        "update_model",         # Download specific model version
        "update_policies",      # Download latest policy bundle
        "update_agents",        # Download agent definition updates
        "update_runtime",       # OTA runtime binary update
        "wipe_data",            # Secure wipe all local data
        "wipe_models",          # Delete all cached models
        "revoke_access",        # Revoke auth token + wipe secrets
        "restart_runtime",      # Restart edge runtime process
        "collect_diagnostics",  # Upload diagnostic logs
        "set_config",           # Update device configuration
    ]
    payload: dict = Field(default_factory=dict)  # Command-specific parameters
    issued_by: uuid.UUID                         # Admin who issued
    issued_at: datetime
    acknowledged_at: datetime | None              # Device received command
    executed_at: datetime | None                  # Device executed command
    result: dict | None                           # Execution result
    status: Literal["pending", "acknowledged", "executing", "completed", "failed", "expired"]
    expires_at: datetime                          # Command expires if not executed
```

**OTA Updates**
- Runtime binary updates: download new version → verify signature → swap binary → restart
- Model updates: differential download (rsync-like) when possible, full download fallback
- Policy updates: download new bundle → verify hash → atomic swap
- Rollback: keep previous version, automatic rollback if new version fails health check within 5 minutes

### Network Resilience

**Fully Offline Operation**
- All locally-deployed agents run without any degradation when offline
- No "phone home" requirement for local operations
- Local API server responds to local clients (tablets, browsers on same network)
- Execution results queued for sync (persistent queue survives restart/power loss)

**Reconnection**
- Automatic reconnection with exponential backoff:
  ```python
  class ReconnectionPolicy:
      initial_delay_seconds: float = 1.0
      max_delay_seconds: float = 300.0       # 5 minutes max
      backoff_multiplier: float = 2.0
      jitter: bool = True                    # Randomize to avoid thundering herd
      max_attempts: int | None = None        # None = retry forever
  ```
- Connection health: periodic heartbeat (configurable interval, default 60s)
- Connection quality tracking: latency, bandwidth, packet loss (used for sync decisions)

**Bandwidth-Aware Sync**
- Detect connection type: WiFi/Ethernet (unmetered) vs. Cellular (metered)
- On metered connections:
  - Sync audit logs and CRL updates (small, critical) ✅
  - Sync execution records (small) ✅
  - Skip model downloads (large) ❌
  - Skip non-critical telemetry ❌
- Configurable threshold: `metered_connection_threshold_mbps`
- Manual override: admin can force full sync regardless of connection

**Proxy Support**
- HTTP proxy: `HTTP_PROXY` / `HTTPS_PROXY` environment variables
- SOCKS5 proxy: for restricted networks
- mTLS through proxy: TLS tunnel via CONNECT method
- No proxy for local traffic: configurable no-proxy list

## Output Structure

```
edge/
├── cmd/
│   └── archon-edge/
│       └── main.go                # Binary entry point
├── internal/
│   ├── runtime/
│   │   ├── server.go              # Local HTTP API server
│   │   ├── executor.go            # LangGraph agent execution engine
│   │   ├── config.go              # Configuration loader (edge-config.yaml)
│   │   └── resources.go           # Resource monitoring (CPU, RAM, disk, battery, GPU)
│   ├── auth/
│   │   ├── offline_token.go       # Offline JWT validation + device binding
│   │   ├── crl.go                 # Certificate Revocation List management
│   │   └── device_identity.go     # Device identity + hardware ID
│   ├── inference/
│   │   ├── llama_cpp.go           # llama.cpp integration (GGUF models)
│   │   ├── onnx.go                # ONNX Runtime integration
│   │   ├── vllm_client.go         # vLLM client (optional GPU backend)
│   │   ├── model_registry.go      # Local model management (download, cache, update)
│   │   └── auto_select.go         # Automatic model selection based on device capabilities
│   ├── storage/
│   │   ├── sqlite_store.go        # Encrypted SQLite for structured data
│   │   ├── vector_store.go        # Embedded Chroma for RAG
│   │   ├── document_store.go      # Local document cache
│   │   └── encryption.go          # Storage encryption (AES-256-GCM)
│   ├── secrets/
│   │   ├── local_store.go         # Encrypted local secret store
│   │   ├── tpm.go                 # TPM/Secure Enclave integration
│   │   └── sync.go                # Secret sync from central Vault
│   ├── sync/
│   │   ├── engine.go              # Bi-directional sync protocol
│   │   ├── delta.go               # Delta computation (vector clock + timestamps)
│   │   ├── conflict.go            # Conflict resolution strategies
│   │   ├── queue.go               # Persistent sync queue (SQLite-backed)
│   │   ├── scheduler.go           # Sync scheduling + bandwidth awareness
│   │   └── compression.go         # Payload compression (gzip, zstd)
│   ├── policy/
│   │   ├── opa_engine.go          # Embedded OPA policy engine
│   │   ├── dlp.go                 # Local DLP scanning (PII detection)
│   │   ├── content_filter.go      # Content safety + prompt injection detection
│   │   └── bundle_manager.go      # Policy bundle download + version tracking
│   └── network/
│       ├── connectivity.go        # Connection detection + quality monitoring
│       ├── reconnect.go           # Exponential backoff reconnection
│       ├── proxy.go               # HTTP/SOCKS proxy support
│       └── bandwidth.go           # Bandwidth-aware sync decisions
├── edge-config.example.yaml       # Example configuration
├── Dockerfile                     # Lightweight edge container
├── Makefile                       # Build targets for all platforms
├── go.mod
└── go.sum

backend/app/edge_management/
├── __init__.py
├── router.py                      # Edge fleet management API
├── models.py                      # EdgeDevice, RemoteCommand, SyncState, DeploymentProfile
├── fleet.py                       # Fleet registration, monitoring, health checks
├── commands.py                    # Remote command issuance and tracking
├── ota.py                         # Over-the-air update management
├── sync_receiver.py               # Central-side sync endpoint (receives edge pushes)
├── device_provisioning.py         # Device enrollment + initial provisioning
├── geofencing.py                  # Location-based policy enforcement
├── telemetry.py                   # Device telemetry ingestion and storage
└── reports.py                     # Fleet health reports and analytics

frontend/src/pages/edge/
├── FleetDashboard.tsx             # Overview of all edge devices (map + list)
├── DeviceDetail.tsx               # Individual device status, metrics, commands
├── DeviceProvisioning.tsx         # Enrollment wizard for new devices
├── DeploymentProfiles.tsx         # Define what goes on each device type
├── SyncMonitor.tsx                # Real-time sync status across fleet
├── ModelManagement.tsx            # Manage models across edge fleet
├── PolicyDistribution.tsx         # Push policy updates to fleet
├── RemoteCommands.tsx             # Issue and track remote commands
├── EdgeSettings.tsx               # Edge configuration templates
└── FleetReports.tsx               # Fleet health and usage reports

tests/
├── test_edge_offline_auth.py          # Offline token validation, CRL, device binding
├── test_edge_local_secrets.py         # Local secret store encryption, sync
├── test_edge_runtime.py               # Binary startup, API server, resource monitoring
├── test_edge_inference_llama.py       # llama.cpp GGUF inference
├── test_edge_inference_onnx.py        # ONNX Runtime inference
├── test_edge_model_registry.py        # Model download, cache, auto-select
├── test_edge_sync_engine.py           # Bi-directional sync protocol
├── test_edge_sync_delta.py            # Delta sync correctness
├── test_edge_sync_conflict.py         # Conflict resolution strategies
├── test_edge_sync_queue.py            # Persistent queue (survives restart)
├── test_edge_opa.py                   # Embedded OPA policy evaluation
├── test_edge_dlp.py                   # Local DLP scanning
├── test_edge_content_filter.py        # Content filtering + prompt injection
├── test_edge_fleet_management.py      # Fleet dashboard, device CRUD
├── test_edge_remote_commands.py       # Remote command issuance and execution
├── test_edge_ota.py                   # OTA update + rollback
├── test_edge_network_resilience.py    # Reconnection, proxy, bandwidth awareness
├── test_edge_geofencing.py            # Location-based restrictions
└── test_edge_device_provisioning.py   # Device enrollment flow
```

## API Endpoints (Complete)

```
# Edge Local API (served by edge runtime binary)
POST   /api/v1/edge/execute                  # Execute agent locally
GET    /api/v1/edge/executions               # List local executions
GET    /api/v1/edge/executions/{id}          # Get execution details
POST   /api/v1/edge/executions/{id}/cancel   # Cancel local execution
GET    /api/v1/edge/agents                   # List locally-available agents
GET    /api/v1/edge/models                   # List local models
GET    /api/v1/edge/status                   # Runtime status (resources, sync, etc.)
GET    /api/v1/edge/health                   # Liveness probe
POST   /api/v1/edge/sync/trigger             # Manually trigger sync
GET    /api/v1/edge/sync/status              # Sync queue status
GET    /api/v1/edge/policies/version         # Current policy bundle version

# Central Fleet Management API (served by central backend)
GET    /api/v1/fleet/devices                 # List all edge devices
POST   /api/v1/fleet/devices                 # Register/enroll new device
GET    /api/v1/fleet/devices/{id}            # Get device details
PUT    /api/v1/fleet/devices/{id}            # Update device config
DELETE /api/v1/fleet/devices/{id}            # Decommission device
GET    /api/v1/fleet/devices/{id}/status     # Device real-time status
GET    /api/v1/fleet/devices/{id}/metrics    # Device telemetry/metrics
GET    /api/v1/fleet/devices/{id}/sync       # Device sync history
GET    /api/v1/fleet/devices/{id}/executions # Device execution history
POST   /api/v1/fleet/devices/{id}/commands   # Issue remote command
GET    /api/v1/fleet/devices/{id}/commands   # List commands for device
GET    /api/v1/fleet/devices/{id}/commands/{cid} # Get command status

# Deployment Profiles
GET    /api/v1/fleet/profiles                # List deployment profiles
POST   /api/v1/fleet/profiles                # Create deployment profile
GET    /api/v1/fleet/profiles/{id}           # Get profile details
PUT    /api/v1/fleet/profiles/{id}           # Update profile
DELETE /api/v1/fleet/profiles/{id}           # Delete profile
POST   /api/v1/fleet/profiles/{id}/apply     # Apply profile to device(s)

# Model Distribution
GET    /api/v1/fleet/models                  # List models in edge registry
POST   /api/v1/fleet/models                  # Register model for edge distribution
POST   /api/v1/fleet/models/{id}/distribute  # Push model to device(s)
GET    /api/v1/fleet/models/{id}/status      # Model distribution status

# Policy Distribution
POST   /api/v1/fleet/policies/publish        # Publish new policy bundle
GET    /api/v1/fleet/policies/versions       # List policy bundle versions
GET    /api/v1/fleet/policies/distribution   # Policy distribution status across fleet

# OTA Updates
POST   /api/v1/fleet/ota/release             # Create OTA release
GET    /api/v1/fleet/ota/releases            # List OTA releases
GET    /api/v1/fleet/ota/releases/{id}       # Get release details
POST   /api/v1/fleet/ota/releases/{id}/rollout # Start rollout to fleet
GET    /api/v1/fleet/ota/releases/{id}/status # Rollout status

# Sync (Central receiver endpoints — called by edge devices)
POST   /api/v1/fleet/sync/push               # Edge pushes data to central
GET    /api/v1/fleet/sync/pull               # Edge pulls updates from central
GET    /api/v1/fleet/sync/crl               # Download Certificate Revocation List
POST   /api/v1/fleet/sync/heartbeat          # Device heartbeat

# Geofencing
GET    /api/v1/fleet/geofences               # List geofences
POST   /api/v1/fleet/geofences               # Create geofence
PUT    /api/v1/fleet/geofences/{id}          # Update geofence
DELETE /api/v1/fleet/geofences/{id}          # Delete geofence

# Fleet Reports
GET    /api/v1/fleet/reports/health           # Fleet health summary
GET    /api/v1/fleet/reports/usage            # Fleet usage aggregates
GET    /api/v1/fleet/reports/sync             # Fleet sync status summary
GET    /api/v1/fleet/reports/models           # Model version distribution
```

## Verify Commands

```bash
# Edge runtime binary builds
cd ~/Scripts/Archon/edge && go build -o archon-edge ./cmd/archon-edge/ && echo "Build OK"

# Edge binary size < 100MB
cd ~/Scripts/Archon/edge && [ $(stat -f%z archon-edge 2>/dev/null || stat -c%s archon-edge) -lt 104857600 ] && echo "Size OK" || echo "FAIL: binary too large"

# Edge runtime starts (smoke test)
cd ~/Scripts/Archon/edge && timeout 10 ./archon-edge --config edge-config.example.yaml --dry-run && echo "Startup OK"

# Fleet management models importable
cd ~/Scripts/Archon && python -c "from backend.app.edge_management.models import EdgeDevice, RemoteCommand, SyncState; print('Fleet models OK')"

# Fleet management service importable
cd ~/Scripts/Archon && python -c "from backend.app.edge_management.fleet import FleetManager; from backend.app.edge_management.commands import RemoteCommandService; print('Fleet services OK')"

# Sync receiver importable
cd ~/Scripts/Archon && python -c "from backend.app.edge_management.sync_receiver import SyncReceiver; print('Sync receiver OK')"

# OTA service importable
cd ~/Scripts/Archon && python -c "from backend.app.edge_management.ota import OTAManager; print('OTA OK')"

# Tests pass (Go edge tests)
cd ~/Scripts/Archon/edge && go test ./... -v -count=1

# Tests pass (Python fleet management tests)
cd ~/Scripts/Archon && python -m pytest tests/test_edge/ --tb=short -q

# Docker compose is valid
cd ~/Scripts/Archon && docker compose config --quiet

# No hardcoded secrets
cd ~/Scripts/Archon && ! grep -rn 'password\s*=\s*"[^"]*"' --include='*.go' edge/ || echo 'FAIL: hardcoded secrets found'
cd ~/Scripts/Archon && ! grep -rn 'api_key\s*=\s*"[^"]*"' --include='*.py' backend/app/edge_management/ || echo 'FAIL: hardcoded secrets found'
```

## Learnings Protocol

Before starting, read `.sdd/learnings/*.md` for known pitfalls from previous sessions.
After completing work, report any pitfalls or patterns discovered so the orchestrator can capture them.

## Acceptance Criteria

- [ ] Edge runtime builds as single binary for Linux x86_64, Linux ARM64, macOS, Windows
- [ ] Binary size <100MB (without models)
- [ ] Cold start <5s to serving first request
- [ ] Offline auth: long-lived encrypted JWT with device binding (TPM/Secure Enclave when available)
- [ ] CRL synced from central, checked locally before accepting tokens
- [ ] Token refresh automatic when online, graceful degradation when offline
- [ ] Local secret store: encrypted SQLite with device-bound key
- [ ] Secrets synced from central Vault, re-encrypted locally
- [ ] Local secret rotation works even when offline
- [ ] llama.cpp (GGUF) inference functional for local LLM execution
- [ ] ONNX Runtime inference functional for embeddings
- [ ] Model auto-selection based on device capabilities (CPU/GPU/RAM)
- [ ] Model download with integrity verification (SHA-256) and resume support
- [ ] Bi-directional sync: push executions/audit to central, pull updates from central
- [ ] Delta sync: only changes since last sync transmitted
- [ ] Conflict resolution: merge for append-only, central-wins for policies, LWW for user data
- [ ] Persistent sync queue survives process restart and power loss
- [ ] Embedded OPA enforces DLP, access control, content filtering offline
- [ ] Fail-closed: all operations denied if policy bundle cannot be loaded
- [ ] DLP scanning detects common PII types (SSN, credit card, email, phone)
- [ ] Central fleet dashboard shows all devices with real-time status
- [ ] Remote commands: force sync, update model, wipe data, revoke access all functional
- [ ] OTA updates for runtime binary, models, policies with rollback capability
- [ ] Fully offline operation: locally-deployed agents run without any degradation
- [ ] Exponential backoff reconnection with jitter
- [ ] Bandwidth-aware sync: skip large downloads on metered connections
- [ ] HTTP/SOCKS proxy support functional
- [ ] All central API endpoints match `contracts/openapi.yaml`
- [ ] All tests pass (Go + Python) with >80% coverage
- [ ] Zero plaintext secrets in logs, env vars, or source code
