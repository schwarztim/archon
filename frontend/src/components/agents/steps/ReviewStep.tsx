
import {
  Bot,
  Brain,
  Wrench,
  Database,
  Shield,
  Plug,
  Play,
  Loader2,
  CheckCircle2,
} from "lucide-react";
import type { IdentityData } from "./IdentityStep";
import type { ModelData } from "./ModelStep";
import type { ToolsData } from "./ToolsStep";
import type { KnowledgeData } from "./KnowledgeStep";
import type { SecurityData } from "./SecurityStep";
import type { ConnectorsData } from "./ConnectorsStep";

// ─── Types ───────────────────────────────────────────────────────────

interface ReviewStepProps {
  identity: IdentityData;
  model: ModelData;
  tools: ToolsData;
  knowledge: KnowledgeData;
  security: SecurityData;
  connectors: ConnectorsData;
  onTest: () => void;
  isTesting: boolean;
  testResult: string | null;
}

// ─── Summary Card ────────────────────────────────────────────────────

function SummaryCard({
  icon: Icon,
  title,
  children,
}: {
  icon: React.ElementType;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-lg border border-[#2a2d37] bg-[#1a1d27] p-4">
      <div className="mb-2 flex items-center gap-2">
        <Icon size={16} className="text-purple-400" />
        <h4 className="text-sm font-medium text-white">{title}</h4>
      </div>
      <div className="space-y-1 text-xs text-gray-400">{children}</div>
    </div>
  );
}

// ─── Mini Graph Preview ──────────────────────────────────────────────

function GraphPreview({
  model,
  tools,
  knowledge,
  connectors,
}: {
  model: ModelData;
  tools: ToolsData;
  knowledge: KnowledgeData;
  connectors: ConnectorsData;
}) {
  const nodes: { label: string; color: string }[] = [
    { label: "Input", color: "bg-blue-500" },
    { label: `LLM (${model.provider})`, color: "bg-purple-500" },
  ];
  if (knowledge.enabled) nodes.push({ label: "RAG", color: "bg-emerald-500" });
  if (tools.selectedTools.length > 0) nodes.push({ label: `${tools.selectedTools.length} Tools`, color: "bg-amber-500" });
  if (connectors.selectedConnectors.length > 0) nodes.push({ label: `${connectors.selectedConnectors.length} Connectors`, color: "bg-cyan-500" });
  nodes.push({ label: "Output", color: "bg-blue-500" });

  return (
    <div className="rounded-lg border border-[#2a2d37] bg-[#12141e] p-4">
      <h4 className="mb-3 text-sm font-medium text-white">Agent Graph Preview</h4>
      <div className="flex items-center gap-2 overflow-x-auto">
        {nodes.map((node, i) => (
          <div key={i} className="flex items-center gap-2">
            <div className={`rounded-lg ${node.color} px-3 py-1.5 text-xs font-medium text-white whitespace-nowrap`}>
              {node.label}
            </div>
            {i < nodes.length - 1 && (
              <svg width="24" height="12" viewBox="0 0 24 12" className="text-gray-600 flex-shrink-0">
                <path d="M0 6H20M20 6L16 2M20 6L16 10" stroke="currentColor" strokeWidth="1.5" fill="none" />
              </svg>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Component ───────────────────────────────────────────────────────

export function ReviewStep({
  identity,
  model,
  tools,
  knowledge,
  security,
  connectors,
  onTest,
  isTesting,
  testResult,
}: ReviewStepProps) {
  return (
    <div className="space-y-4">
      {/* Graph Preview */}
      <GraphPreview
        model={model}
        tools={tools}
        knowledge={knowledge}
        connectors={connectors}
      />

      {/* Summary Cards */}
      <div className="grid gap-3 sm:grid-cols-2">
        <SummaryCard icon={Bot} title="Identity">
          <p><span className="text-white">{identity.icon} {identity.name}</span></p>
          <p>{identity.description || "No description"}</p>
          {identity.tags.length > 0 && (
            <div className="mt-1 flex flex-wrap gap-1">
              {identity.tags.map((t) => (
                <span key={t} className="rounded bg-purple-500/20 px-1.5 py-0.5 text-purple-300">{t}</span>
              ))}
            </div>
          )}
          {identity.group_id && <p>Group: {identity.group_id}</p>}
        </SummaryCard>

        <SummaryCard icon={Brain} title="Model Configuration">
          <p>Provider: <span className="text-white">{model.provider}</span></p>
          <p>Model: <span className="text-white">{model.modelId}</span></p>
          <p>Temperature: {model.temperature.toFixed(1)} · Max Tokens: {model.maxTokens.toLocaleString()}</p>
          {model.systemPrompt && (
            <p className="mt-1 line-clamp-2 italic">"{model.systemPrompt}"</p>
          )}
        </SummaryCard>

        <SummaryCard icon={Wrench} title="Tools & MCP">
          {tools.selectedTools.length === 0 ? (
            <p>No tools configured</p>
          ) : (
            <p>{tools.selectedTools.length} tool{tools.selectedTools.length !== 1 ? "s" : ""} enabled: {tools.selectedTools.map((t) => t.id).join(", ")}</p>
          )}
        </SummaryCard>

        <SummaryCard icon={Database} title="Knowledge / RAG">
          {knowledge.enabled ? (
            <>
              <p>Collection: <span className="text-white">{knowledge.collection || "Not set"}</span></p>
              <p>Embedding: {knowledge.embeddingModel} · Strategy: {knowledge.chunkStrategy}</p>
              <p>Top-K: {knowledge.topK}</p>
            </>
          ) : (
            <p>RAG disabled</p>
          )}
        </SummaryCard>

        <SummaryCard icon={Shield} title="Security & Guardrails">
          <p>DLP: <span className={security.dlpEnabled ? "text-green-400" : "text-gray-500"}>{security.dlpEnabled ? "Enabled" : "Disabled"}</span></p>
          <p>Cost Limit: ${security.maxCostPerRun.toFixed(2)}/run</p>
          <p>PII Handling: {security.piiHandling}</p>
          {security.guardrailPolicies.length > 0 && (
            <p>Guardrails: {security.guardrailPolicies.join(", ")}</p>
          )}
          {security.allowedDomains.length > 0 && (
            <p>Domains: {security.allowedDomains.join(", ")}</p>
          )}
        </SummaryCard>

        <SummaryCard icon={Plug} title="Connectors">
          {connectors.selectedConnectors.length === 0 ? (
            <p>No connectors attached</p>
          ) : (
            <p>{connectors.selectedConnectors.length} connector{connectors.selectedConnectors.length !== 1 ? "s" : ""} attached</p>
          )}
        </SummaryCard>
      </div>

      {/* Test Button */}
      <div className="rounded-lg border border-[#2a2d37] bg-[#1a1d27] p-4">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-medium text-white">Test Agent</p>
            <p className="text-xs text-gray-500">Send a test message to verify configuration</p>
          </div>
          <button
            type="button"
            onClick={onTest}
            disabled={isTesting}
            className="flex items-center gap-2 rounded-lg bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50"
          >
            {isTesting ? (
              <>
                <Loader2 size={16} className="animate-spin" />
                Testing...
              </>
            ) : (
              <>
                <Play size={16} />
                Run Test
              </>
            )}
          </button>
        </div>

        {testResult && (
          <div className="mt-3 rounded-lg border border-green-500/30 bg-green-500/10 p-3">
            <div className="mb-1 flex items-center gap-1 text-sm font-medium text-green-400">
              <CheckCircle2 size={14} />
              Test Result
            </div>
            <pre className="whitespace-pre-wrap text-xs text-green-300">{testResult}</pre>
          </div>
        )}
      </div>
    </div>
  );
}
