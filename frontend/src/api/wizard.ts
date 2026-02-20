import type { ApiResponse } from "@/types";
import { apiPost } from "./client";

// ─── Request Types ───────────────────────────────────────────────────

export interface WizardDescribeRequest {
  description: string;
  workspace_id?: string;
}

// ─── Response Types ──────────────────────────────────────────────────

export interface TemplateMatchResult {
  template_id: string;
  template_name: string;
  similarity: number;
}

export interface NLAnalysis {
  analysis_id: string;
  original_description: string;
  intents: string[];
  entities: string[];
  connectors_detected: string[];
  template_matches: TemplateMatchResult[];
  confidence: number;
}

export interface PlannedNode {
  node_id: string;
  label: string;
  node_type: string;
  description: string;
  config: Record<string, unknown>;
}

export interface PlannedEdge {
  source: string;
  target: string;
  condition: string;
}

export interface ModelRequirement {
  provider: string;
  model_id: string;
  purpose: string;
}

export interface ConnectorRequirement {
  connector_type: string;
  name: string;
  purpose: string;
}

export interface CredentialRequirement {
  vault_path: string;
  connector_type: string;
  description: string;
}

export interface NLBuildPlan {
  plan_id: string;
  analysis_id: string;
  nodes: PlannedNode[];
  edges: PlannedEdge[];
  models_needed: ModelRequirement[];
  connectors_needed: ConnectorRequirement[];
  credential_requirements: CredentialRequirement[];
  estimated_cost: number;
  security_notes: string[];
}

export interface GeneratedAgent {
  agent_name: string;
  tenant_id: string;
  workspace_id: string;
  owner_id: string;
  graph_definition: Record<string, unknown>;
  python_source: string;
  credential_manifest: CredentialRequirement[];
  plan_id: string;
}

export interface SecurityIssue {
  severity: string;
  code: string;
  message: string;
}

export interface ValidationResult {
  passed: boolean;
  security_issues: SecurityIssue[];
  cost_estimate: number;
  compliance_notes: string[];
}

export interface FullPipelineResult {
  agent: GeneratedAgent;
  validation: ValidationResult;
}

// ─── API Calls ───────────────────────────────────────────────────────
// TODO: Backend wizard.py has prefix="/api/v1/wizard" AND is registered with API_PREFIX — double prefix bug.
// Frontend paths below are correct in intent (/wizard/...) but won't resolve until backend is fixed.

/** Step 1: Describe — NLP analysis of a description */
export async function wizardDescribe(
  description: string,
  workspaceId?: string,
): Promise<ApiResponse<NLAnalysis>> {
  return apiPost<NLAnalysis>("/wizard/describe", {
    description,
    workspace_id: workspaceId,
  });
}

/** Step 2: Plan — structured build plan from analysis */
export async function wizardPlan(
  analysis: NLAnalysis,
): Promise<ApiResponse<NLBuildPlan>> {
  return apiPost<NLBuildPlan>("/wizard/plan", analysis);
}

/** Step 3: Build — generate agent from plan */
export async function wizardBuild(
  plan: NLBuildPlan,
): Promise<ApiResponse<GeneratedAgent>> {
  return apiPost<GeneratedAgent>("/wizard/build", plan);
}

/** Step 4: Validate — security scan & compliance check */
export async function wizardValidate(
  agent: GeneratedAgent,
): Promise<ApiResponse<ValidationResult>> {
  return apiPost<ValidationResult>("/wizard/validate", agent);
}

/** Refine — iterative refinement */
export async function wizardRefine(
  agent: GeneratedAgent,
  feedback: string,
  iteration: number,
): Promise<ApiResponse<GeneratedAgent>> {
  return apiPost<GeneratedAgent>("/wizard/refine", {
    agent,
    feedback,
    iteration,
  });
}

/** Full pipeline — describe → plan → build → validate */
export async function wizardFull(
  description: string,
  workspaceId?: string,
): Promise<ApiResponse<FullPipelineResult>> {
  return apiPost<FullPipelineResult>("/wizard/full", {
    description,
    workspace_id: workspaceId,
  });
}
