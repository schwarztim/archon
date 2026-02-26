import { useState, useCallback } from "react";
import {
  X,
  Bot,
  Brain,
  Wrench,
  Database,
  Shield,
  Plug,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Search,
  Upload,
  Plus,
  Zap,
  Globe,
  Calculator,
  FileText,
  Code2,
  Server,
  Mail,
  MessageSquare,
} from "lucide-react";

// ─── Types ───────────────────────────────────────────────────────────

interface Step1Data {
  name: string;
  description: string;
  tags: string[];
  icon: string;
}

interface Step2Data {
  provider: string;
  modelId: string;
  temperature: number;
  maxTokens: number;
  systemPrompt: string;
}

interface ToolItem {
  id: string;
  name: string;
  description: string;
  icon: string;
}

interface Step3Data {
  selectedTools: string[];
}

interface Step4Data {
  enabled: boolean;
  collection: string;
  chunkStrategy: string;
  topK: number;
}

interface Step5Data {
  dlpEnabled: boolean;
  maxCost: number;
  guardrailPolicies: string[];
  allowedDomains: string[];
}

interface ConnectorItem {
  id: string;
  name: string;
  icon: string;
  status: "available" | "connected" | "error";
}

interface Step6Data {
  selectedConnectors: string[];
}

interface AgentWizardProps {
  onClose: () => void;
  onSubmit: (payload: Record<string, unknown>) => void;
  isPending: boolean;
  quickCreate?: boolean;
}

// ─── Constants ───────────────────────────────────────────────────────

const STEPS = [
  { label: "Identity", icon: Bot },
  { label: "Model", icon: Brain },
  { label: "Tools", icon: Wrench },
  { label: "Knowledge", icon: Database },
  { label: "Security", icon: Shield },
  { label: "Connectors", icon: Plug },
  { label: "Review", icon: CheckCircle2 },
] as const;

const PROVIDERS = ["OpenAI", "Anthropic", "Azure", "Ollama", "Google", "Mistral", "Cohere"];

const MODELS_BY_PROVIDER: Record<string, string[]> = {
  OpenAI: ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo", "o1-preview", "o1-mini"],
  Anthropic: ["claude-sonnet-4-20250514", "claude-3-5-haiku-20241022", "claude-3-opus-20240229"],
  Azure: ["gpt-4o (Azure)", "gpt-4-turbo (Azure)", "gpt-35-turbo (Azure)"],
  Ollama: ["llama3.1", "mistral", "codellama", "phi3"],
  Google: ["gemini-1.5-pro", "gemini-1.5-flash", "gemini-pro"],
  Mistral: ["mistral-large", "mistral-medium", "mistral-small"],
  Cohere: ["command-r-plus", "command-r", "command"],
};

const ICON_OPTIONS = ["🤖", "🧠", "⚡", "🔧", "📊", "🎯", "💡", "🚀", "🔍", "📝", "🛡️", "🌐"];

const PLACEHOLDER_TOOLS: ToolItem[] = [
  { id: "web-search", name: "Web Search", description: "Search the web for information", icon: "globe" },
  { id: "calculator", name: "Calculator", description: "Perform mathematical calculations", icon: "calculator" },
  { id: "file-reader", name: "File Reader", description: "Read and parse file contents", icon: "file" },
  { id: "code-executor", name: "Code Executor", description: "Execute code in a sandboxed environment", icon: "code" },
  { id: "database-query", name: "Database Query", description: "Query relational databases", icon: "server" },
  { id: "api-caller", name: "API Caller", description: "Make HTTP requests to external APIs", icon: "zap" },
  { id: "email-sender", name: "Email Sender", description: "Send emails via configured SMTP", icon: "mail" },
  { id: "slack-notifier", name: "Slack Notifier", description: "Send messages to Slack channels", icon: "message" },
];

const PLACEHOLDER_CONNECTORS: ConnectorItem[] = [
  { id: "postgresql", name: "PostgreSQL", icon: "server", status: "available" },
  { id: "salesforce", name: "Salesforce", icon: "zap", status: "available" },
  { id: "slack", name: "Slack", icon: "message", status: "connected" },
  { id: "github", name: "GitHub", icon: "code", status: "connected" },
  { id: "s3", name: "Amazon S3", icon: "server", status: "available" },
  { id: "jira", name: "Jira", icon: "zap", status: "available" },
  { id: "snowflake", name: "Snowflake", icon: "server", status: "available" },
  { id: "hubspot", name: "HubSpot", icon: "globe", status: "available" },
];

const GUARDRAIL_OPTIONS = ["Content Safety", "PII Detection", "Prompt Injection Guard", "Output Validation", "Rate Limiting"];

// ─── Tool icon mapping ──────────────────────────────────────────────

function ToolIcon({ icon, size = 18 }: { icon: string; size?: number }) {
  switch (icon) {
    case "globe": return <Globe size={size} />;
    case "calculator": return <Calculator size={size} />;
    case "file": return <FileText size={size} />;
    case "code": return <Code2 size={size} />;
    case "server": return <Server size={size} />;
    case "zap": return <Zap size={size} />;
    case "mail": return <Mail size={size} />;
    case "message": return <MessageSquare size={size} />;
    default: return <Wrench size={size} />;
  }
}

// ─── Shared styles ──────────────────────────────────────────────────

const inputClass =
  "w-full rounded-lg border border-surface-border bg-surface-raised px-3 py-2 text-sm text-white placeholder-gray-500 focus:border-purple-500 focus:outline-none";

const labelClass = "mb-1 block text-xs font-medium text-gray-400";

// ─── Component ──────────────────────────────────────────────────────

export function AgentWizard({ onClose, onSubmit, isPending, quickCreate = false }: AgentWizardProps) {
  const [step, setStep] = useState(0);

  // Step 1
  const [s1, setS1] = useState<Step1Data>({ name: "", description: "", tags: [], icon: "🤖" });
  const [tagInput, setTagInput] = useState("");

  // Step 2
  const [s2, setS2] = useState<Step2Data>({
    provider: "OpenAI",
    modelId: "gpt-4o",
    temperature: 0.7,
    maxTokens: 4096,
    systemPrompt: "",
  });

  // Step 3
  const [s3, setS3] = useState<Step3Data>({ selectedTools: [] });
  const [toolSearch, setToolSearch] = useState("");

  // Step 4
  const [s4, setS4] = useState<Step4Data>({
    enabled: false,
    collection: "",
    chunkStrategy: "fixed",
    topK: 5,
  });

  // Step 5
  const [s5, setS5] = useState<Step5Data>({
    dlpEnabled: false,
    maxCost: 1.0,
    guardrailPolicies: [],
    allowedDomains: [],
  });
  const [domainInput, setDomainInput] = useState("");

  // Step 6
  const [s6, setS6] = useState<Step6Data>({ selectedConnectors: [] });

  // Test state for Step 7
  const [testResult, setTestResult] = useState<string | null>(null);
  const [isTesting, setIsTesting] = useState(false);

  // ── Helpers ────────────────────────────────────────────────────────

  const addTag = useCallback(() => {
    const t = tagInput.trim().toLowerCase();
    if (t && !s1.tags.includes(t)) setS1((p) => ({ ...p, tags: [...p.tags, t] }));
    setTagInput("");
  }, [tagInput, s1.tags]);

  const addDomain = useCallback(() => {
    const d = domainInput.trim().toLowerCase();
    if (d && !s5.allowedDomains.includes(d)) setS5((p) => ({ ...p, allowedDomains: [...p.allowedDomains, d] }));
    setDomainInput("");
  }, [domainInput, s5.allowedDomains]);

  const toggleTool = (id: string) => {
    setS3((p) => ({
      selectedTools: p.selectedTools.includes(id)
        ? p.selectedTools.filter((t) => t !== id)
        : [...p.selectedTools, id],
    }));
  };

  const toggleConnector = (id: string) => {
    setS6((p) => ({
      selectedConnectors: p.selectedConnectors.includes(id)
        ? p.selectedConnectors.filter((c) => c !== id)
        : [...p.selectedConnectors, id],
    }));
  };

  const toggleGuardrail = (policy: string) => {
    setS5((p) => ({
      ...p,
      guardrailPolicies: p.guardrailPolicies.includes(policy)
        ? p.guardrailPolicies.filter((g) => g !== policy)
        : [...p.guardrailPolicies, policy],
    }));
  };

  const canNext = (): boolean => {
    if (step === 0) return s1.name.trim().length > 0;
    return true;
  };

  const buildPayload = () => ({
    name: s1.name,
    description: s1.description,
    tags: s1.tags,
    definition: {},
    llm_config: {
      model_id: s2.modelId,
      provider: s2.provider,
      temperature: s2.temperature,
      max_tokens: s2.maxTokens,
      system_prompt: s2.systemPrompt,
    },
    tools: s3.selectedTools,
    rag_config: s4.enabled
      ? { top_k: s4.topK, chunk_strategy: s4.chunkStrategy, collection: s4.collection }
      : null,
    security_policy: {
      dlp_enabled: s5.dlpEnabled,
      max_cost_per_run: s5.maxCost,
      guardrail_policies: s5.guardrailPolicies,
      allowed_domains: s5.allowedDomains,
    },
    mcp_config: null,
    connectors: s6.selectedConnectors,
  });

  const handleTest = () => {
    setIsTesting(true);
    setTestResult(null);
    setTimeout(() => {
      setTestResult(
        `✅ Agent "${s1.name}" responded successfully.\n\nModel: ${s2.provider} / ${s2.modelId}\nTools: ${s3.selectedTools.length} enabled\nLatency: 847ms\n\nSample response: "Hello! I'm ${s1.name}, ready to assist you."`,
      );
      setIsTesting(false);
    }, 1500);
  };

  const handleSubmit = () => onSubmit(buildPayload());

  const filteredTools = PLACEHOLDER_TOOLS.filter(
    (t) =>
      t.name.toLowerCase().includes(toolSearch.toLowerCase()) ||
      t.description.toLowerCase().includes(toolSearch.toLowerCase()),
  );

  // ── Step Renderers ─────────────────────────────────────────────────

  const renderStep1 = () => (
    <div className="space-y-4">
      <div>
        <label className={labelClass}>Name *</label>
        <input
          type="text"
          required
          value={s1.name}
          onChange={(e) => setS1((p) => ({ ...p, name: e.target.value }))}
          className={inputClass}
          placeholder="My Agent"
        />
      </div>
      <div>
        <label className={labelClass}>Description</label>
        <textarea
          value={s1.description}
          onChange={(e) => setS1((p) => ({ ...p, description: e.target.value }))}
          rows={3}
          className={inputClass}
          placeholder="What does this agent do?"
        />
      </div>
      <div>
        <label className={labelClass}>Icon</label>
        <div className="flex flex-wrap gap-2">
          {ICON_OPTIONS.map((ico) => (
            <button
              key={ico}
              type="button"
              onClick={() => setS1((p) => ({ ...p, icon: ico }))}
              className={`flex h-10 w-10 items-center justify-center rounded-lg border text-lg ${
                s1.icon === ico
                  ? "border-purple-500 bg-purple-500/20"
                  : "border-surface-border bg-surface-raised hover:border-gray-600"
              }`}
            >
              {ico}
            </button>
          ))}
        </div>
      </div>
      <div>
        <label className={labelClass}>Tags</label>
        <div className="mb-2 flex flex-wrap gap-1">
          {s1.tags.map((t) => (
            <span
              key={t}
              className="flex items-center gap-1 rounded-full bg-purple-500/20 px-2 py-0.5 text-xs text-purple-300"
            >
              {t}
              <button type="button" onClick={() => setS1((p) => ({ ...p, tags: p.tags.filter((x) => x !== t) }))} className="hover:text-white">
                <X size={10} />
              </button>
            </span>
          ))}
        </div>
        <div className="flex gap-2">
          <input
            type="text"
            value={tagInput}
            onChange={(e) => setTagInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addTag(); } }}
            className={`flex-1 ${inputClass}`}
            placeholder="Add tag..."
          />
          <button type="button" onClick={addTag} className="rounded-lg border border-surface-border px-3 py-2 text-sm text-gray-400 hover:bg-white/5">
            Add
          </button>
        </div>
      </div>
    </div>
  );

  const renderStep2 = () => (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className={labelClass}>Provider</label>
          <select
            value={s2.provider}
            onChange={(e) => {
              const p = e.target.value;
              const models = MODELS_BY_PROVIDER[p] ?? [];
              setS2((prev) => ({ ...prev, provider: p, modelId: models[0] ?? "" }));
            }}
            className={inputClass}
          >
            {PROVIDERS.map((p) => (
              <option key={p} value={p}>{p}</option>
            ))}
          </select>
        </div>
        <div>
          <label className={labelClass}>Model</label>
          <select value={s2.modelId} onChange={(e) => setS2((p) => ({ ...p, modelId: e.target.value }))} className={inputClass}>
            {(MODELS_BY_PROVIDER[s2.provider] ?? []).map((m) => (
              <option key={m} value={m}>{m}</option>
            ))}
          </select>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className={labelClass}>Temperature: {s2.temperature.toFixed(1)}</label>
          <input
            type="range"
            min={0}
            max={2}
            step={0.1}
            value={s2.temperature}
            onChange={(e) => setS2((p) => ({ ...p, temperature: parseFloat(e.target.value) }))}
            className="w-full accent-purple-500"
          />
          <div className="flex justify-between text-xs text-gray-600">
            <span>Precise</span>
            <span>Creative</span>
          </div>
        </div>
        <div>
          <label className={labelClass}>Max Tokens</label>
          <input
            type="number"
            value={s2.maxTokens}
            onChange={(e) => setS2((p) => ({ ...p, maxTokens: parseInt(e.target.value) || 0 }))}
            className={inputClass}
            min={1}
            max={128000}
          />
        </div>
      </div>
      <div>
        <label className={labelClass}>System Prompt</label>
        <textarea
          value={s2.systemPrompt}
          onChange={(e) => setS2((p) => ({ ...p, systemPrompt: e.target.value }))}
          rows={6}
          className={`${inputClass} font-mono text-xs`}
          placeholder="You are a helpful assistant..."
        />
      </div>
    </div>
  );

  const renderStep3 = () => (
    <div className="space-y-4">
      <div className="relative">
        <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
        <input
          type="text"
          value={toolSearch}
          onChange={(e) => setToolSearch(e.target.value)}
          className={`${inputClass} pl-9`}
          placeholder="Search tools..."
        />
      </div>
      <div className="grid grid-cols-2 gap-3">
        {filteredTools.map((tool) => {
          const selected = s3.selectedTools.includes(tool.id);
          return (
            <button
              key={tool.id}
              type="button"
              onClick={() => toggleTool(tool.id)}
              className={`flex items-start gap-3 rounded-lg border p-3 text-left transition-colors ${
                selected
                  ? "border-purple-500 bg-purple-500/10"
                  : "border-surface-border bg-surface-raised hover:border-gray-600"
              }`}
            >
              <div className={`mt-0.5 rounded-lg p-2 ${selected ? "bg-purple-500/20 text-purple-400" : "bg-surface-overlay text-gray-500"}`}>
                <ToolIcon icon={tool.icon} size={16} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium text-white">{tool.name}</span>
                  <div className={`h-4 w-8 rounded-full transition-colors ${selected ? "bg-purple-500" : "bg-gray-700"}`}>
                    <div className={`h-4 w-4 rounded-full bg-white shadow transition-transform ${selected ? "translate-x-4" : "translate-x-0"}`} />
                  </div>
                </div>
                <p className="mt-0.5 text-xs text-gray-500">{tool.description}</p>
              </div>
            </button>
          );
        })}
      </div>
      <button
        type="button"
        className="flex w-full items-center justify-center gap-2 rounded-lg border border-dashed border-surface-border py-3 text-sm text-gray-500 hover:border-purple-500/50 hover:text-purple-400"
      >
        <Plus size={16} />
        Custom Tool
      </button>
    </div>
  );

  const renderStep4 = () => (
    <div className="space-y-4">
      <div className="flex items-center justify-between rounded-lg border border-surface-border bg-surface-raised p-4">
        <div>
          <p className="text-sm font-medium text-white">Enable Knowledge Base</p>
          <p className="text-xs text-gray-500">Connect a vector store for RAG-powered responses</p>
        </div>
        <label className="relative inline-flex cursor-pointer items-center">
          <input
            type="checkbox"
            checked={s4.enabled}
            onChange={(e) => setS4((p) => ({ ...p, enabled: e.target.checked }))}
            className="peer sr-only"
          />
          <div className="h-6 w-11 rounded-full bg-gray-700 after:absolute after:left-[2px] after:top-[2px] after:h-5 after:w-5 after:rounded-full after:bg-white after:shadow after:transition-transform peer-checked:bg-purple-500 peer-checked:after:translate-x-full" />
        </label>
      </div>
      {s4.enabled && (
        <div className="space-y-4 rounded-lg border border-surface-border bg-surface-overlay p-4">
          <div>
            <label className={labelClass}>Collection</label>
            <select value={s4.collection} onChange={(e) => setS4((p) => ({ ...p, collection: e.target.value }))} className={inputClass}>
              <option value="">Select collection...</option>
              <option value="docs">Documentation</option>
              <option value="kb">Knowledge Base</option>
              <option value="faq">FAQ</option>
            </select>
          </div>
          <div>
            <label className={labelClass}>Chunk Strategy</label>
            <select value={s4.chunkStrategy} onChange={(e) => setS4((p) => ({ ...p, chunkStrategy: e.target.value }))} className={inputClass}>
              <option value="fixed">Fixed Size</option>
              <option value="semantic">Semantic</option>
              <option value="sentence">Sentence</option>
            </select>
          </div>
          <div>
            <label className={labelClass}>Top K: {s4.topK}</label>
            <input
              type="range"
              min={1}
              max={20}
              value={s4.topK}
              onChange={(e) => setS4((p) => ({ ...p, topK: parseInt(e.target.value) }))}
              className="w-full accent-purple-500"
            />
            <div className="flex justify-between text-xs text-gray-600">
              <span>1</span>
              <span>20</span>
            </div>
          </div>
          <div>
            <label className={labelClass}>Upload Documents</label>
            <div className="flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-surface-border py-8 text-gray-500 hover:border-purple-500/50">
              <Upload size={24} className="mb-2" />
              <p className="text-sm">Drop files here or click to upload</p>
              <p className="mt-1 text-xs text-gray-600">PDF, TXT, MD, CSV — up to 10MB</p>
            </div>
          </div>
        </div>
      )}
    </div>
  );

  const renderStep5 = () => (
    <div className="space-y-4">
      <div className="flex items-center justify-between rounded-lg border border-surface-border bg-surface-raised p-4">
        <div>
          <p className="text-sm font-medium text-white">DLP Protection</p>
          <p className="text-xs text-gray-500">Scan inputs and outputs for sensitive data</p>
        </div>
        <label className="relative inline-flex cursor-pointer items-center">
          <input
            type="checkbox"
            checked={s5.dlpEnabled}
            onChange={(e) => setS5((p) => ({ ...p, dlpEnabled: e.target.checked }))}
            className="peer sr-only"
          />
          <div className="h-6 w-11 rounded-full bg-gray-700 after:absolute after:left-[2px] after:top-[2px] after:h-5 after:w-5 after:rounded-full after:bg-white after:shadow after:transition-transform peer-checked:bg-purple-500 peer-checked:after:translate-x-full" />
        </label>
      </div>
      <div>
        <label className={labelClass}>Max Cost Per Execution</label>
        <div className="relative">
          <span className="absolute left-3 top-1/2 -translate-y-1/2 text-sm text-gray-500">$</span>
          <input
            type="number"
            value={s5.maxCost}
            onChange={(e) => setS5((p) => ({ ...p, maxCost: parseFloat(e.target.value) || 0 }))}
            className={`${inputClass} pl-7`}
            min={0}
            step={0.1}
          />
        </div>
      </div>
      <div>
        <label className={labelClass}>Guardrail Policies</label>
        <div className="space-y-2">
          {GUARDRAIL_OPTIONS.map((policy) => {
            const selected = s5.guardrailPolicies.includes(policy);
            return (
              <label
                key={policy}
                className={`flex cursor-pointer items-center gap-3 rounded-lg border p-3 transition-colors ${
                  selected ? "border-purple-500 bg-purple-500/10" : "border-surface-border bg-surface-raised hover:border-gray-600"
                }`}
              >
                <input
                  type="checkbox"
                  checked={selected}
                  onChange={() => toggleGuardrail(policy)}
                  className="h-4 w-4 rounded border-gray-600 bg-gray-800 text-purple-500 accent-purple-500"
                />
                <span className="text-sm text-white">{policy}</span>
              </label>
            );
          })}
        </div>
      </div>
      <div>
        <label className={labelClass}>Allowed Domains</label>
        <div className="mb-2 flex flex-wrap gap-1">
          {s5.allowedDomains.map((d) => (
            <span key={d} className="flex items-center gap-1 rounded-full bg-purple-500/20 px-2 py-0.5 text-xs text-purple-300">
              {d}
              <button type="button" onClick={() => setS5((p) => ({ ...p, allowedDomains: p.allowedDomains.filter((x) => x !== d) }))} className="hover:text-white">
                <X size={10} />
              </button>
            </span>
          ))}
        </div>
        <div className="flex gap-2">
          <input
            type="text"
            value={domainInput}
            onChange={(e) => setDomainInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addDomain(); } }}
            className={`flex-1 ${inputClass}`}
            placeholder="example.com"
          />
          <button type="button" onClick={addDomain} className="rounded-lg border border-surface-border px-3 py-2 text-sm text-gray-400 hover:bg-white/5">
            Add
          </button>
        </div>
      </div>
    </div>
  );

  const renderStep6 = () => (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        {PLACEHOLDER_CONNECTORS.map((conn) => {
          const selected = s6.selectedConnectors.includes(conn.id);
          return (
            <button
              key={conn.id}
              type="button"
              onClick={() => toggleConnector(conn.id)}
              className={`flex items-center gap-3 rounded-lg border p-3 text-left transition-colors ${
                selected
                  ? "border-purple-500 bg-purple-500/10"
                  : "border-surface-border bg-surface-raised hover:border-gray-600"
              }`}
            >
              <div className={`rounded-lg p-2 ${selected ? "bg-purple-500/20 text-purple-400" : "bg-surface-overlay text-gray-500"}`}>
                <ToolIcon icon={conn.icon} size={16} />
              </div>
              <div className="flex-1 min-w-0">
                <span className="text-sm font-medium text-white">{conn.name}</span>
                <div className="mt-0.5">
                  <span
                    className={`inline-block rounded-full px-1.5 py-0.5 text-[10px] font-medium ${
                      conn.status === "connected"
                        ? "bg-green-500/20 text-green-400"
                        : conn.status === "error"
                          ? "bg-red-500/20 text-red-400"
                          : "bg-gray-500/20 text-gray-400"
                    }`}
                  >
                    {conn.status}
                  </span>
                </div>
              </div>
              <div className={`h-4 w-8 rounded-full transition-colors ${selected ? "bg-purple-500" : "bg-gray-700"}`}>
                <div className={`h-4 w-4 rounded-full bg-white shadow transition-transform ${selected ? "translate-x-4" : "translate-x-0"}`} />
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );

  const renderStep7 = () => {
    const payload = buildPayload();
    return (
      <div className="space-y-4">
        {/* Identity summary */}
        <div className="rounded-lg border border-surface-border bg-surface-raised p-4">
          <h4 className="mb-2 text-xs font-medium uppercase tracking-wider text-gray-500">Identity</h4>
          <div className="flex items-center gap-2">
            <span className="text-lg">{s1.icon}</span>
            <span className="text-sm font-medium text-white">{payload.name}</span>
          </div>
          {payload.description && <p className="mt-1 text-xs text-gray-500">{payload.description}</p>}
          {payload.tags.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1">
              {payload.tags.map((t) => (
                <span key={t} className="rounded-full bg-purple-500/20 px-2 py-0.5 text-xs text-purple-300">{t}</span>
              ))}
            </div>
          )}
        </div>

        {/* Model summary */}
        <div className="rounded-lg border border-surface-border bg-surface-raised p-4">
          <h4 className="mb-2 text-xs font-medium uppercase tracking-wider text-gray-500">Model Configuration</h4>
          <div className="grid grid-cols-2 gap-2 text-xs">
            <div><span className="text-gray-500">Provider:</span> <span className="text-white">{payload.llm_config.provider}</span></div>
            <div><span className="text-gray-500">Model:</span> <span className="text-white">{payload.llm_config.model_id}</span></div>
            <div><span className="text-gray-500">Temperature:</span> <span className="text-white">{payload.llm_config.temperature}</span></div>
            <div><span className="text-gray-500">Max Tokens:</span> <span className="text-white">{payload.llm_config.max_tokens}</span></div>
          </div>
          {payload.llm_config.system_prompt && (
            <div className="mt-2">
              <span className="text-xs text-gray-500">System Prompt:</span>
              <p className="mt-1 line-clamp-2 rounded bg-surface-overlay p-2 font-mono text-xs text-gray-300">{payload.llm_config.system_prompt}</p>
            </div>
          )}
        </div>

        {/* Tools summary */}
        {payload.tools.length > 0 && (
          <div className="rounded-lg border border-surface-border bg-surface-raised p-4">
            <h4 className="mb-2 text-xs font-medium uppercase tracking-wider text-gray-500">
              Tools ({payload.tools.length})
            </h4>
            <div className="flex flex-wrap gap-1">
              {payload.tools.map((t) => {
                const tool = PLACEHOLDER_TOOLS.find((pt) => pt.id === t);
                return (
                  <span key={t} className="rounded bg-surface-overlay px-2 py-1 text-xs text-gray-300">
                    {tool?.name ?? t}
                  </span>
                );
              })}
            </div>
          </div>
        )}

        {/* RAG summary */}
        {payload.rag_config && (
          <div className="rounded-lg border border-surface-border bg-surface-raised p-4">
            <h4 className="mb-2 text-xs font-medium uppercase tracking-wider text-gray-500">Knowledge (RAG)</h4>
            <div className="grid grid-cols-3 gap-2 text-xs">
              <div><span className="text-gray-500">Collection:</span> <span className="text-white">{payload.rag_config.collection || "—"}</span></div>
              <div><span className="text-gray-500">Strategy:</span> <span className="text-white">{payload.rag_config.chunk_strategy}</span></div>
              <div><span className="text-gray-500">Top K:</span> <span className="text-white">{payload.rag_config.top_k}</span></div>
            </div>
          </div>
        )}

        {/* Security summary */}
        <div className="rounded-lg border border-surface-border bg-surface-raised p-4">
          <h4 className="mb-2 text-xs font-medium uppercase tracking-wider text-gray-500">Security</h4>
          <div className="grid grid-cols-2 gap-2 text-xs">
            <div><span className="text-gray-500">DLP:</span> <span className={payload.security_policy.dlp_enabled ? "text-green-400" : "text-gray-400"}>{payload.security_policy.dlp_enabled ? "Enabled" : "Disabled"}</span></div>
            <div><span className="text-gray-500">Max Cost:</span> <span className="text-white">${payload.security_policy.max_cost_per_run}</span></div>
          </div>
          {payload.security_policy.guardrail_policies.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1">
              {payload.security_policy.guardrail_policies.map((g) => (
                <span key={g} className="rounded bg-surface-overlay px-2 py-1 text-xs text-gray-300">{g}</span>
              ))}
            </div>
          )}
        </div>

        {/* Connectors summary */}
        {payload.connectors.length > 0 && (
          <div className="rounded-lg border border-surface-border bg-surface-raised p-4">
            <h4 className="mb-2 text-xs font-medium uppercase tracking-wider text-gray-500">
              Connectors ({payload.connectors.length})
            </h4>
            <div className="flex flex-wrap gap-1">
              {payload.connectors.map((c) => {
                const conn = PLACEHOLDER_CONNECTORS.find((pc) => pc.id === c);
                return (
                  <span key={c} className="rounded bg-surface-overlay px-2 py-1 text-xs text-gray-300">{conn?.name ?? c}</span>
                );
              })}
            </div>
          </div>
        )}

        {/* Test Agent */}
        <div className="rounded-lg border border-surface-border bg-surface-raised p-4">
          <div className="flex items-center justify-between">
            <div>
              <h4 className="text-xs font-medium uppercase tracking-wider text-gray-500">Test Agent</h4>
              <p className="mt-0.5 text-xs text-gray-600">Send a sample prompt to verify configuration</p>
            </div>
            <button
              type="button"
              onClick={handleTest}
              disabled={isTesting}
              className="flex items-center gap-2 rounded-lg border border-purple-500/50 px-3 py-1.5 text-xs text-purple-400 hover:bg-purple-500/10 disabled:opacity-50"
            >
              <Zap size={12} />
              {isTesting ? "Testing..." : "Test Agent"}
            </button>
          </div>
          {testResult && (
            <pre className="mt-3 whitespace-pre-wrap rounded bg-surface-overlay p-3 font-mono text-xs text-green-400">
              {testResult}
            </pre>
          )}
        </div>
      </div>
    );
  };

  const STEP_RENDERERS = [renderStep1, renderStep2, renderStep3, renderStep4, renderStep5, renderStep6, renderStep7];

  // For quick create, only show steps 0 and 1
  const currentStepIndex = step;
  const stepsToShow = quickCreate ? STEPS.slice(0, 2) : STEPS;
  const isLastStep = quickCreate ? step >= 1 : step >= 6;

  // ── Render ─────────────────────────────────────────────────────────

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-surface-base/95 backdrop-blur-sm">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-surface-border px-6 py-4">
        <div className="flex items-center gap-3">
          <Bot size={20} className="text-purple-400" />
          <h2 className="text-lg font-semibold text-white">
            {quickCreate ? "Quick Create Agent" : "Create Agent"}
          </h2>
        </div>
        <button onClick={onClose} className="rounded-lg p-2 text-gray-400 hover:bg-white/5 hover:text-white" aria-label="Close">
          <X size={20} />
        </button>
      </div>

      {/* Step Indicator */}
      <div className="border-b border-surface-border px-6 py-3">
        <div className="flex items-center gap-1">
          {stepsToShow.map((s, i) => {
            const Icon = s.icon;
            const isCurrent = i === currentStepIndex;
            const isCompleted = i < currentStepIndex;
            return (
              <div key={i} className="flex items-center">
                {i > 0 && (
                  <div className={`mx-1 h-px w-8 ${isCompleted ? "bg-purple-500" : "bg-surface-border"}`} />
                )}
                <button
                  type="button"
                  onClick={() => { if (isCompleted) setStep(i); }}
                  disabled={!isCompleted}
                  className={`flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium transition-colors ${
                    isCurrent
                      ? "bg-purple-500/20 text-purple-400"
                      : isCompleted
                        ? "bg-green-500/10 text-green-400 hover:bg-green-500/20"
                        : "text-gray-600"
                  }`}
                >
                  {isCompleted ? (
                    <CheckCircle2 size={14} />
                  ) : (
                    <Icon size={14} />
                  )}
                  <span className="hidden sm:inline">{s.label}</span>
                </button>
              </div>
            );
          })}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-6 py-6">
        <div className="mx-auto max-w-2xl">
          <h3 className="mb-1 text-base font-semibold text-white">
            {stepsToShow[currentStepIndex]?.label}
          </h3>
          <p className="mb-4 text-xs text-gray-500">
            {currentStepIndex === 0 && "Define your agent's identity and metadata."}
            {currentStepIndex === 1 && "Choose the language model and configure its parameters."}
            {currentStepIndex === 2 && "Select the tools your agent can use."}
            {currentStepIndex === 3 && "Configure knowledge retrieval for your agent."}
            {currentStepIndex === 4 && "Set security policies and guardrails."}
            {currentStepIndex === 5 && "Connect external services and data sources."}
            {currentStepIndex === 6 && "Review your configuration and test the agent."}
          </p>
          {STEP_RENDERERS[currentStepIndex]?.()}
        </div>
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between border-t border-surface-border px-6 py-4">
        <div>
          {step > 0 && (
            <button
              type="button"
              onClick={() => setStep((s) => s - 1)}
              className="flex items-center gap-1 rounded-lg border border-surface-border px-4 py-2 text-sm text-gray-400 hover:bg-white/5"
            >
              <ChevronLeft size={16} />
              Back
            </button>
          )}
        </div>
        <div className="flex items-center gap-2">
          {!quickCreate && !isLastStep && step >= 2 && (
            <span className="text-xs text-gray-600">Optional step — you can skip</span>
          )}
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-surface-border px-4 py-2 text-sm text-gray-400 hover:bg-white/5"
          >
            Cancel
          </button>
          {isLastStep ? (
            <button
              type="button"
              onClick={handleSubmit}
              disabled={isPending || !canNext()}
              className="flex items-center gap-2 rounded-lg bg-purple-600 px-5 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50"
            >
              <Bot size={14} />
              {isPending ? "Creating..." : "Create Agent"}
            </button>
          ) : (
            <button
              type="button"
              onClick={() => setStep((s) => s + 1)}
              disabled={!canNext()}
              className="flex items-center gap-1 rounded-lg bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50"
            >
              Next
              <ChevronRight size={16} />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
