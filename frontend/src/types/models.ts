// ─── Common ──────────────────────────────────────────────────────────
/** UUID represented as a string */
export type UUID = string;

/** ISO-8601 date string */
export type ISODateString = string;

// ─── Agents / Executions ─────────────────────────────────────────────
export interface Agent {
  id: UUID;
  name: string;
  description: string | null;
  status: "active" | "inactive" | "error";
  version: number;
  created_at: ISODateString;
  updated_at: ISODateString;
}

export type ExecutionStatus =
  | "queued"
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "cancelled";

export interface ExecutionStep {
  name?: string;
  step_name?: string;
  step_type?: "llm_call" | "tool_call" | "condition" | "transform" | "retrieval";
  status: string;
  duration_ms?: number;
  token_usage?: number;
  tokens?: number;
  cost?: number;
  input?: Record<string, unknown>;
  output?: Record<string, unknown>;
  error?: string | null;
}

export interface ExecutionMetrics {
  duration_ms?: number;
  total_duration_ms?: number;
  total_tokens?: number;
  estimated_cost?: number;
  total_cost?: number;
}

export interface Execution {
  id: UUID;
  agent_id: UUID;
  status: ExecutionStatus;
  input_data: Record<string, unknown>;
  output_data: Record<string, unknown> | null;
  error: string | null;
  steps: ExecutionStep[] | null;
  metrics: ExecutionMetrics | null;
  started_at: ISODateString | null;
  completed_at: ISODateString | null;
  created_at: ISODateString;
  updated_at: ISODateString;
}

// ─── Model Router ────────────────────────────────────────────────────
export interface ModelRegistryEntry {
  id: UUID;
  name: string;
  provider: string;
  model_id: string;
  capabilities: string[];
  context_window: number;
  cost_per_input_token: number;
  cost_per_output_token: number;
  max_tokens: number;
  is_active: boolean;
  metadata: Record<string, unknown>;
  created_at: ISODateString;
  updated_at: ISODateString;
}

export interface RoutingRule {
  id: UUID;
  name: string;
  description: string | null;
  priority: number;
  conditions: Record<string, unknown>;
  target_model_id: UUID;
  fallback_model_id: UUID | null;
  is_active: boolean;
  created_at: ISODateString;
  updated_at: ISODateString;
}

export interface RouteResponse {
  model_id: UUID;
  model_name: string;
  provider: string;
  rule_id: UUID | null;
  reason: string;
}

// ─── Lifecycle ───────────────────────────────────────────────────────
export type DeploymentStage =
  | "dev"
  | "staging"
  | "canary"
  | "production"
  | "retired";

export type DeploymentStatus =
  | "pending"
  | "deploying"
  | "active"
  | "draining"
  | "retired"
  | "failed";

export interface DeploymentRecord {
  id: UUID;
  agent_id: UUID;
  version: number;
  stage: DeploymentStage;
  status: DeploymentStatus;
  replicas: number;
  metadata: Record<string, unknown>;
  deployed_by: string;
  created_at: ISODateString;
  updated_at: ISODateString;
}

export interface HealthCheck {
  id: UUID;
  deployment_id: UUID;
  status: "healthy" | "degraded" | "unhealthy";
  latency_ms: number;
  details: Record<string, unknown>;
  checked_at: ISODateString;
}

export interface LifecycleEvent {
  id: UUID;
  deployment_id: UUID;
  event_type: string;
  description: string;
  actor: string;
  metadata: Record<string, unknown>;
  created_at: ISODateString;
}

export type DeploymentStrategyType = "rolling" | "blue_green" | "canary" | "shadow";

export interface ApprovalGate {
  from_stage: string;
  to_stage: string;
  required_approvers: number;
  auto_approve_after_hours: number | null;
  require_health_check: boolean;
  require_tests_pass: boolean;
  enabled: boolean;
}

export interface PipelineStageInfo {
  stage: string;
  label: string;
  deployments: Record<string, unknown>[];
  approval_gate: ApprovalGate | null;
}

export interface EnvironmentInfo {
  name: string;
  display_name: string;
  status: string;
  deployed_version: string | null;
  agent_id: UUID | null;
  agent_name: string | null;
  health_status: string;
  instance_count: number;
  last_deploy_at: ISODateString | null;
  created_at: ISODateString;
}

export interface ConfigDiff {
  source_env: string;
  target_env: string;
  differences: Record<string, unknown>[];
  source_version: string | null;
  target_version: string | null;
}

export interface DeploymentHistoryEntry {
  id: UUID;
  agent_id: UUID;
  agent_name: string | null;
  version_id: string;
  environment: string;
  strategy: string;
  status: string;
  deployed_by: string | null;
  started_at: ISODateString | null;
  completed_at: ISODateString | null;
  duration_seconds: number | null;
  rollback_reason: string | null;
}

export interface HealthMetrics {
  deployment_id: UUID;
  status: string;
  response_time_p50: number;
  response_time_p95: number;
  response_time_p99: number;
  error_rate: number;
  throughput_rps: number;
  uptime_pct: number;
  auto_rollback_triggered: boolean;
  auto_rollback_threshold: number;
  checked_at: ISODateString;
}

// ─── Cost Engine ─────────────────────────────────────────────────────
export interface TokenLedger {
  id: UUID;
  tenant_id: UUID;
  agent_id: UUID;
  model_id: UUID;
  input_tokens: number;
  output_tokens: number;
  total_cost: number;
  currency: string;
  recorded_at: ISODateString;
}

export interface Budget {
  id: UUID;
  tenant_id: UUID;
  name: string;
  limit_amount: number;
  spent_amount: number;
  currency: string;
  period: "daily" | "weekly" | "monthly" | "quarterly" | "annual";
  alert_threshold_pct: number;
  is_hard_limit: boolean;
  starts_at: ISODateString;
  ends_at: ISODateString;
  created_at: ISODateString;
  updated_at: ISODateString;
}

export interface CostAlert {
  id: UUID;
  budget_id: UUID;
  alert_type: "threshold" | "overage" | "anomaly";
  message: string;
  severity: "info" | "warning" | "critical";
  acknowledged: boolean;
  triggered_at: ISODateString;
}

export interface ProviderPricing {
  id: UUID;
  provider: string;
  model_id: string;
  input_price_per_1k: number;
  output_price_per_1k: number;
  currency: string;
  effective_from: ISODateString;
  effective_to: ISODateString | null;
}

export interface CostReport {
  total_cost: number;
  currency: string;
  by_agent: Record<string, number>;
  by_model: Record<string, number>;
  by_tenant: Record<string, number>;
  period_start: ISODateString;
  period_end: ISODateString;
}

export interface CostForecast {
  projected_cost: number;
  currency: string;
  confidence: number;
  period_start: ISODateString;
  period_end: ISODateString;
  breakdown: Record<string, number>;
}

// ─── DLP ─────────────────────────────────────────────────────────────
export type DLPAction = "redact" | "mask" | "block" | "log" | "alert";

export interface DLPPolicy {
  id: UUID;
  name: string;
  description: string | null;
  entity_types: string[];
  action: DLPAction;
  is_active: boolean;
  regex_patterns: string[];
  confidence_threshold: number;
  created_at: ISODateString;
  updated_at: ISODateString;
}

export interface DetectedEntity {
  type: string;
  value: string;
  start: number;
  end: number;
  confidence: number;
}

export interface DLPScanResult {
  id: UUID;
  policy_id: UUID;
  input_hash: string;
  entities_found: DetectedEntity[];
  action_taken: DLPAction;
  clean_text: string | null;
  scanned_at: ISODateString;
}

// ─── Governance ──────────────────────────────────────────────────────
export type CompliancePolicyType =
  | "data_residency"
  | "retention"
  | "access_control"
  | "content_safety"
  | "custom";

export interface CompliancePolicy {
  id: UUID;
  name: string;
  description: string | null;
  type: CompliancePolicyType;
  rules: Record<string, unknown>;
  enforcement: "enforce" | "audit" | "disabled";
  is_active: boolean;
  created_at: ISODateString;
  updated_at: ISODateString;
}

export interface ComplianceRecord {
  id: UUID;
  policy_id: UUID;
  agent_id: UUID;
  compliant: boolean;
  violations: string[];
  checked_at: ISODateString;
}

export interface AuditEntry {
  id: UUID;
  actor: string;
  action: string;
  resource_type: string;
  resource_id: UUID;
  details: Record<string, unknown>;
  ip_address: string | null;
  created_at: ISODateString;
}

// ─── SentinelScan ────────────────────────────────────────────────────
export type ScanStatus = "pending" | "running" | "completed" | "failed";

export interface DiscoveryScan {
  id: UUID;
  name: string;
  target: string;
  scan_type: "network" | "api" | "agent" | "full";
  status: ScanStatus;
  progress_pct: number;
  services_found: number;
  started_at: ISODateString | null;
  completed_at: ISODateString | null;
  created_at: ISODateString;
}

export interface RiskClassification {
  level: "critical" | "high" | "medium" | "low" | "info";
  score: number;
  factors: string[];
}

export interface DiscoveredService {
  id: UUID;
  scan_id: UUID;
  name: string;
  service_type: string;
  endpoint: string;
  version: string | null;
  risk: RiskClassification;
  metadata: Record<string, unknown>;
  discovered_at: ISODateString;
}

export interface PostureReport {
  scan_id: UUID;
  total_services: number;
  risk_summary: Record<string, number>;
  top_risks: DiscoveredService[];
  recommendations: string[];
  generated_at: ISODateString;
}

// ─── Multi-Tenancy ───────────────────────────────────────────────────
export type TenantStatus = "active" | "suspended" | "provisioning" | "deleted";

export interface Tenant {
  id: UUID;
  name: string;
  slug: string;
  status: TenantStatus;
  plan: string;
  settings: Record<string, unknown>;
  created_at: ISODateString;
  updated_at: ISODateString;
}

export interface TenantQuota {
  id: UUID;
  tenant_id: UUID;
  resource: string;
  limit: number;
  used: number;
  unit: string;
  resets_at: ISODateString | null;
}

export interface UsageMeteringRecord {
  id: UUID;
  tenant_id: UUID;
  resource: string;
  quantity: number;
  unit: string;
  recorded_at: ISODateString;
}

// ─── Marketplace ─────────────────────────────────────────────────────
export type ListingStatus = "draft" | "published" | "archived" | "rejected";

export interface MarketplaceListing {
  id: UUID;
  name: string;
  description: string;
  author_id: UUID;
  author_name: string;
  category: string;
  tags: string[];
  version: string;
  status: ListingStatus;
  icon_url: string | null;
  install_count: number;
  avg_rating: number;
  price: number;
  currency: string;
  definition: Record<string, unknown>;
  created_at: ISODateString;
  updated_at: ISODateString;
}

export interface MarketplaceReview {
  id: UUID;
  listing_id: UUID;
  reviewer_id: UUID;
  reviewer_name: string;
  rating: number;
  title: string;
  body: string;
  created_at: ISODateString;
  updated_at: ISODateString;
}

// ─── Connectors ──────────────────────────────────────────────────────
export type ConnectorStatus = "connected" | "disconnected" | "error" | "pending";

export interface Connector {
  id: UUID;
  name: string;
  type: string;
  config: Record<string, unknown>;
  status: ConnectorStatus;
  last_health_check: ISODateString | null;
  created_at: ISODateString;
  updated_at: ISODateString;
}

export interface ConnectionTestResult {
  success: boolean;
  latency_ms: number;
  message: string;
  details: Record<string, unknown>;
}

export interface ConnectorHealth {
  connector_id: UUID;
  status: ConnectorStatus;
  uptime_pct: number;
  last_error: string | null;
  checked_at: ISODateString;
}

// ─── Red Team ────────────────────────────────────────────────────────
export type CampaignStatus = "pending" | "running" | "completed" | "failed";

export interface RedTeamCampaign {
  id: UUID;
  name: string;
  target_agent_id: UUID;
  attack_types: string[];
  status: CampaignStatus;
  started_at: ISODateString | null;
  completed_at: ISODateString | null;
  created_at: ISODateString;
}

export interface RedTeamResult {
  campaign_id: UUID;
  total_tests: number;
  passed: number;
  failed: number;
  vulnerabilities: Array<{
    type: string;
    severity: "critical" | "high" | "medium" | "low";
    description: string;
    reproduction: string;
  }>;
  summary: string;
}

// ─── Mesh Gateway ────────────────────────────────────────────────────
export type MeshNodeStatus = "online" | "offline" | "degraded";

export interface MeshNode {
  id: UUID;
  name: string;
  endpoint: string;
  region: string;
  status: MeshNodeStatus;
  capabilities: string[];
  last_heartbeat: ISODateString;
  registered_at: ISODateString;
}

export interface TrustRelationship {
  id: UUID;
  source_node_id: UUID;
  target_node_id: UUID;
  trust_level: "full" | "limited" | "verify";
  established_at: ISODateString;
  expires_at: ISODateString | null;
}

export interface MeshMessage {
  id: UUID;
  source_node_id: UUID;
  target_node_id: UUID;
  payload: Record<string, unknown>;
  status: "sent" | "delivered" | "failed";
  sent_at: ISODateString;
}

// ─── Edge Runtime ────────────────────────────────────────────────────
export type EdgeDeviceStatus = "online" | "offline" | "updating" | "error";

export interface EdgeDevice {
  id: UUID;
  name: string;
  device_type: string;
  status: EdgeDeviceStatus;
  firmware_version: string;
  last_seen: ISODateString;
  metadata: Record<string, unknown>;
  registered_at: ISODateString;
}

export interface EdgeModelDeployment {
  id: UUID;
  device_id: UUID;
  model_id: UUID;
  model_name: string;
  version: string;
  status: "deploying" | "active" | "failed" | "removed";
  deployed_at: ISODateString;
  updated_at: ISODateString;
}

export interface FleetStatus {
  total_devices: number;
  online: number;
  offline: number;
  updating: number;
  error: number;
  deployments: number;
}
