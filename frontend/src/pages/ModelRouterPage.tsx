import { useState, useEffect } from "react";
import {
  GitFork,
  Plus,
  X,
  Cpu,
  Globe,
  Zap,
  CircleDot,
  Server,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import { apiGet, apiPost } from "@/api/client";

interface Provider {
  id: string;
  name: string;
  api_type: string;
  model_ids: string[];
  capabilities: string[];
  cost_per_1k_tokens: number;
  avg_latency_ms: number;
  data_classification_level: string;
  geo_residency: string;
  is_active: boolean;
}

interface ProviderHealth {
  provider_id: string;
  name: string;
  status: string;
  latency_ms?: number;
}

const PROVIDER_TYPES = [
  { value: "openai", label: "OpenAI" },
  { value: "anthropic", label: "Anthropic" },
  { value: "azure_openai", label: "Azure OpenAI" },
  { value: "ollama", label: "Ollama" },
  { value: "litellm", label: "LiteLLM" },
  { value: "google", label: "Google" },
  { value: "mistral", label: "Mistral" },
  { value: "cohere", label: "Cohere" },
  { value: "local", label: "Local" },
  { value: "custom", label: "Custom" },
];

interface ModelEntry {
  id: string;
  name: string;
  provider: string;
  model_id: string;
  capabilities: string[];
  context_window: number;
  cost_per_input_token: number;
  cost_per_output_token: number;
  speed_tier: string;
  is_active: boolean;
  created_at: string;
}

interface RoutingRule {
  id: string;
  name: string;
  conditions: Record<string, unknown>;
  target_model_id: string;
  priority: number;
  is_active: boolean;
  created_at: string;
}

function StatusBadge({ active }: { active: boolean }) {
  return active ? (
    <span className="inline-flex items-center gap-1 rounded-full bg-green-500/20 px-2 py-0.5 text-xs font-medium text-green-400">
      <CircleDot size={10} /> Active
    </span>
  ) : (
    <span className="inline-flex items-center gap-1 rounded-full bg-red-500/20 px-2 py-0.5 text-xs font-medium text-red-400">
      <CircleDot size={10} /> Inactive
    </span>
  );
}

export function ModelRouterPage() {
  const [models, setModels] = useState<ModelEntry[]>([]);
  const [rules, setRules] = useState<RoutingRule[]>([]);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [providerHealth, setProviderHealth] = useState<ProviderHealth[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showModelForm, setShowModelForm] = useState(false);
  const [showRuleForm, setShowRuleForm] = useState(false);
  const [showProviderForm, setShowProviderForm] = useState(false);
  const [creatingModel, setCreatingModel] = useState(false);
  const [creatingRule, setCreatingRule] = useState(false);
  const [creatingProvider, setCreatingProvider] = useState(false);
  const [modelForm, setModelForm] = useState({
    name: "", provider: "", model_id: "", capabilities: "",
    context_window: "128000", cost_per_input_token: "", cost_per_output_token: "",
    speed_tier: "standard",
  });
  const [ruleForm, setRuleForm] = useState({
    name: "", conditions: "{}", target_model_id: "", priority: "1",
  });
  const [providerForm, setProviderForm] = useState({
    name: "", api_type: "openai", model_ids: "",
    capabilities: "", cost_per_1k_tokens: "", avg_latency_ms: "500",
  });

  async function fetchAll() {
    setLoading(true);
    setError(null);
    try {
      const [modelsRes, rulesRes, providersRes, healthRes] = await Promise.allSettled([
        apiGet<ModelEntry[]>("/router/models"),
        apiGet<RoutingRule[]>("/router/rules"),
        apiGet<Provider[]>("/router/providers"),
        apiGet<ProviderHealth[]>("/router/providers/health"),
      ]);
      if (modelsRes.status === "fulfilled") setModels(Array.isArray(modelsRes.value.data) ? modelsRes.value.data : []);
      if (rulesRes.status === "fulfilled") setRules(Array.isArray(rulesRes.value.data) ? rulesRes.value.data : []);
      if (providersRes.status === "fulfilled") setProviders(Array.isArray(providersRes.value.data) ? providersRes.value.data : []);
      if (healthRes.status === "fulfilled") setProviderHealth(Array.isArray(healthRes.value.data) ? healthRes.value.data : []);
    } catch {
      setError("Failed to load router data.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void fetchAll(); }, []);

  async function handleCreateModel(e: React.FormEvent) {
    e.preventDefault();
    if (!modelForm.name || !modelForm.provider || !modelForm.model_id) return;
    setCreatingModel(true);
    try {
      await apiPost("/router/models", {
        name: modelForm.name,
        provider: modelForm.provider,
        model_id: modelForm.model_id,
        capabilities: modelForm.capabilities.split(",").map((c) => c.trim()).filter(Boolean),
        context_window: parseInt(modelForm.context_window, 10) || 128000,
        cost_per_input_token: parseFloat(modelForm.cost_per_input_token) || 0,
        cost_per_output_token: parseFloat(modelForm.cost_per_output_token) || 0,
        speed_tier: modelForm.speed_tier,
        is_active: true,
      });
      setModelForm({ name: "", provider: "", model_id: "", capabilities: "", context_window: "128000", cost_per_input_token: "", cost_per_output_token: "", speed_tier: "standard" });
      setShowModelForm(false);
      await fetchAll();
    } catch {
      setError("Failed to create model.");
    } finally {
      setCreatingModel(false);
    }
  }

  async function handleCreateRule(e: React.FormEvent) {
    e.preventDefault();
    if (!ruleForm.name || !ruleForm.target_model_id) return;
    setCreatingRule(true);
    try {
      let conditions = {};
      try { conditions = JSON.parse(ruleForm.conditions); } catch { /* use empty */ }
      await apiPost("/router/rules", {
        name: ruleForm.name,
        conditions,
        target_model_id: ruleForm.target_model_id,
        priority: parseInt(ruleForm.priority, 10) || 1,
        is_active: true,
      });
      setRuleForm({ name: "", conditions: "{}", target_model_id: "", priority: "1" });
      setShowRuleForm(false);
      await fetchAll();
    } catch {
      setError("Failed to create rule.");
    } finally {
      setCreatingRule(false);
    }
  }

  async function handleCreateProvider(e: React.FormEvent) {
    e.preventDefault();
    if (!providerForm.name || !providerForm.api_type) return;
    setCreatingProvider(true);
    try {
      await apiPost("/router/providers", {
        name: providerForm.name,
        api_type: providerForm.api_type,
        model_ids: providerForm.model_ids.split(",").map((s) => s.trim()).filter(Boolean),
        capabilities: providerForm.capabilities.split(",").map((s) => s.trim()).filter(Boolean),
        cost_per_1k_tokens: parseFloat(providerForm.cost_per_1k_tokens) || 0,
        avg_latency_ms: parseFloat(providerForm.avg_latency_ms) || 500,
        is_active: true,
      });
      setProviderForm({ name: "", api_type: "openai", model_ids: "", capabilities: "", cost_per_1k_tokens: "", avg_latency_ms: "500" });
      setShowProviderForm(false);
      await fetchAll();
    } catch {
      setError("Failed to create provider.");
    } finally {
      setCreatingProvider(false);
    }
  }

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <p className="text-gray-400">Loading...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6">
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-4 text-red-400">{error}</div>
      </div>
    );
  }

  return (
    <div className="p-6">
      <div className="mb-6 flex items-center gap-3">
        <GitFork size={24} className="text-purple-400" />
        <div>
          <h1 className="text-2xl font-bold text-white">Model Router</h1>
          <p className="text-sm text-gray-400">Configure intelligent routing rules to direct requests to the optimal LLM.</p>
        </div>
      </div>

      {/* Stats */}
      <div className="mb-8 grid grid-cols-1 gap-4 sm:grid-cols-4">
        <div className="rounded-lg border border-[#2a2d37] bg-[#1a1d27] p-4">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-sm text-gray-400">Providers</span>
            <Server size={20} className="text-purple-400" />
          </div>
          <p className="text-2xl font-bold text-white">{providers.length}</p>
          <p className="mt-1 text-xs text-gray-500">{providers.filter((p) => p.is_active).length} active</p>
        </div>
        <div className="rounded-lg border border-[#2a2d37] bg-[#1a1d27] p-4">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-sm text-gray-400">Models</span>
            <Cpu size={20} className="text-purple-400" />
          </div>
          <p className="text-2xl font-bold text-white">{models.length}</p>
          <p className="mt-1 text-xs text-gray-500">{models.filter((m) => m.is_active).length} active</p>
        </div>
        <div className="rounded-lg border border-[#2a2d37] bg-[#1a1d27] p-4">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-sm text-gray-400">Unique Sources</span>
            <Globe size={20} className="text-purple-400" />
          </div>
          <p className="text-2xl font-bold text-white">{new Set(models.map((m) => m.provider)).size}</p>
        </div>
        <div className="rounded-lg border border-[#2a2d37] bg-[#1a1d27] p-4">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-sm text-gray-400">Routing Rules</span>
            <Zap size={20} className="text-purple-400" />
          </div>
          <p className="text-2xl font-bold text-white">{rules.length}</p>
          <p className="mt-1 text-xs text-gray-500">{rules.filter((r) => r.is_active).length} active</p>
        </div>
      </div>

      {/* Providers */}
      <div className="mb-6 rounded-lg border border-[#2a2d37] bg-[#1a1d27]">
        <div className="flex items-center justify-between border-b border-[#2a2d37] px-4 py-3">
          <h2 className="text-sm font-semibold text-white">Providers</h2>
          <Button size="sm" className="bg-purple-600 hover:bg-purple-700" onClick={() => setShowProviderForm(!showProviderForm)}>
            {showProviderForm ? <><X size={14} className="mr-1.5" /> Cancel</> : <><Plus size={14} className="mr-1.5" /> Add Provider</>}
          </Button>
        </div>

        {showProviderForm && (
          <form onSubmit={handleCreateProvider} className="border-b border-[#2a2d37] bg-[#0f1117] px-4 py-4">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <div>
                <label className="mb-1 block text-xs text-gray-400">Name *</label>
                <input className="h-9 w-full rounded-md border border-[#2a2d37] bg-[#0f1117] px-3 text-sm text-white" placeholder="My OpenAI" value={providerForm.name} onChange={(e) => setProviderForm({ ...providerForm, name: e.target.value })} />
              </div>
              <div>
                <label className="mb-1 block text-xs text-gray-400">Type *</label>
                <select className="h-9 w-full rounded-md border border-[#2a2d37] bg-[#0f1117] px-3 text-sm text-white" value={providerForm.api_type} onChange={(e) => setProviderForm({ ...providerForm, api_type: e.target.value })}>
                  {PROVIDER_TYPES.map((pt) => (
                    <option key={pt.value} value={pt.value}>{pt.label}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="mb-1 block text-xs text-gray-400">Supported Models (comma-sep)</label>
                <input className="h-9 w-full rounded-md border border-[#2a2d37] bg-[#0f1117] px-3 text-sm text-white" placeholder="gpt-4o, gpt-4o-mini" value={providerForm.model_ids} onChange={(e) => setProviderForm({ ...providerForm, model_ids: e.target.value })} />
              </div>
              <div>
                <label className="mb-1 block text-xs text-gray-400">Capabilities (comma-sep)</label>
                <input className="h-9 w-full rounded-md border border-[#2a2d37] bg-[#0f1117] px-3 text-sm text-white" placeholder="chat, code, vision" value={providerForm.capabilities} onChange={(e) => setProviderForm({ ...providerForm, capabilities: e.target.value })} />
              </div>
              <div>
                <label className="mb-1 block text-xs text-gray-400">Cost / 1K Tokens</label>
                <input type="number" step="0.001" className="h-9 w-full rounded-md border border-[#2a2d37] bg-[#0f1117] px-3 text-sm text-white" placeholder="0.03" value={providerForm.cost_per_1k_tokens} onChange={(e) => setProviderForm({ ...providerForm, cost_per_1k_tokens: e.target.value })} />
              </div>
              <div>
                <label className="mb-1 block text-xs text-gray-400">Avg Latency (ms)</label>
                <input type="number" className="h-9 w-full rounded-md border border-[#2a2d37] bg-[#0f1117] px-3 text-sm text-white" placeholder="500" value={providerForm.avg_latency_ms} onChange={(e) => setProviderForm({ ...providerForm, avg_latency_ms: e.target.value })} />
              </div>
              <div className="flex items-end sm:col-span-2">
                <Button type="submit" size="sm" className="w-full bg-purple-600 hover:bg-purple-700" disabled={creatingProvider}>
                  {creatingProvider ? "Adding…" : "Add Provider"}
                </Button>
              </div>
            </div>
          </form>
        )}

        <div className="overflow-x-auto">
          {providers.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12">
              <Server size={32} className="mb-2 text-gray-600" />
              <p className="text-sm text-gray-500">No providers registered yet. Add a provider to define model sources.</p>
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[#2a2d37] text-left text-xs text-gray-500">
                  <th className="px-4 py-2 font-medium">Name</th>
                  <th className="px-4 py-2 font-medium">Type</th>
                  <th className="px-4 py-2 font-medium">Models</th>
                  <th className="px-4 py-2 font-medium">Status</th>
                  <th className="px-4 py-2 font-medium">Health</th>
                  <th className="px-4 py-2 font-medium text-right">Cost/1K</th>
                  <th className="px-4 py-2 font-medium text-right">Latency</th>
                </tr>
              </thead>
              <tbody>
                {providers.map((p) => {
                  const health = providerHealth.find((h) => h.provider_id === p.id);
                  return (
                    <tr key={p.id} className="border-b border-[#2a2d37] hover:bg-white/5">
                      <td className="px-4 py-2 font-medium text-white">{p.name}</td>
                      <td className="px-4 py-2 text-gray-400">{PROVIDER_TYPES.find((pt) => pt.value === p.api_type)?.label ?? p.api_type}</td>
                      <td className="px-4 py-2">
                        <div className="flex flex-wrap gap-1">
                          {(p.model_ids ?? []).map((mid) => (
                            <span key={mid} className="rounded bg-purple-500/20 px-1.5 py-0.5 text-[10px] font-medium text-purple-300 font-mono">{mid}</span>
                          ))}
                        </div>
                      </td>
                      <td className="px-4 py-2"><StatusBadge active={p.is_active} /></td>
                      <td className="px-4 py-2">
                        {health ? (
                          <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${health.status === "healthy" ? "bg-green-500/20 text-green-400" : "bg-yellow-500/20 text-yellow-400"}`}>
                            <CircleDot size={10} /> {health.status}
                          </span>
                        ) : (
                          <span className="text-xs text-gray-500">—</span>
                        )}
                      </td>
                      <td className="px-4 py-2 text-right text-gray-400">${p.cost_per_1k_tokens.toFixed(3)}</td>
                      <td className="px-4 py-2 text-right text-gray-400">{p.avg_latency_ms}ms</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* Models */}
      <div className="mb-6 rounded-lg border border-[#2a2d37] bg-[#1a1d27]">
        <div className="flex items-center justify-between border-b border-[#2a2d37] px-4 py-3">
          <h2 className="text-sm font-semibold text-white">Model Registry</h2>
          <Button size="sm" className="bg-purple-600 hover:bg-purple-700" onClick={() => setShowModelForm(!showModelForm)}>
            {showModelForm ? <><X size={14} className="mr-1.5" /> Cancel</> : <><Plus size={14} className="mr-1.5" /> Register Model</>}
          </Button>
        </div>

        {showModelForm && (
          <form onSubmit={handleCreateModel} className="border-b border-[#2a2d37] bg-[#0f1117] px-4 py-4">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <div>
                <label className="mb-1 block text-xs text-gray-400">Name *</label>
                <input className="h-9 w-full rounded-md border border-[#2a2d37] bg-[#0f1117] px-3 text-sm text-white" placeholder="GPT-4o" value={modelForm.name} onChange={(e) => setModelForm({ ...modelForm, name: e.target.value })} />
              </div>
              <div>
                <label className="mb-1 block text-xs text-gray-400">Provider *</label>
                <select className="h-9 w-full rounded-md border border-[#2a2d37] bg-[#0f1117] px-3 text-sm text-white" value={modelForm.provider} onChange={(e) => setModelForm({ ...modelForm, provider: e.target.value })}>
                  <option value="">Select provider…</option>
                  {providers.map((p) => (
                    <option key={p.id} value={p.name}>{p.name} ({PROVIDER_TYPES.find((pt) => pt.value === p.api_type)?.label ?? p.api_type})</option>
                  ))}
                  <option value="__custom__">Custom…</option>
                </select>
                {modelForm.provider === "__custom__" && (
                  <input className="mt-1 h-9 w-full rounded-md border border-[#2a2d37] bg-[#0f1117] px-3 text-sm text-white" placeholder="Custom provider name" onChange={(e) => setModelForm({ ...modelForm, provider: e.target.value || "__custom__" })} />
                )}
              </div>
              <div>
                <label className="mb-1 block text-xs text-gray-400">Model ID *</label>
                <input className="h-9 w-full rounded-md border border-[#2a2d37] bg-[#0f1117] px-3 text-sm text-white" placeholder="gpt-4o" value={modelForm.model_id} onChange={(e) => setModelForm({ ...modelForm, model_id: e.target.value })} />
              </div>
              <div>
                <label className="mb-1 block text-xs text-gray-400">Capabilities (comma-sep)</label>
                <input className="h-9 w-full rounded-md border border-[#2a2d37] bg-[#0f1117] px-3 text-sm text-white" placeholder="chat, code" value={modelForm.capabilities} onChange={(e) => setModelForm({ ...modelForm, capabilities: e.target.value })} />
              </div>
              <div>
                <label className="mb-1 block text-xs text-gray-400">Context Window</label>
                <input type="number" className="h-9 w-full rounded-md border border-[#2a2d37] bg-[#0f1117] px-3 text-sm text-white" value={modelForm.context_window} onChange={(e) => setModelForm({ ...modelForm, context_window: e.target.value })} />
              </div>
              <div>
                <label className="mb-1 block text-xs text-gray-400">Cost/Input Token</label>
                <input type="number" step="0.0001" className="h-9 w-full rounded-md border border-[#2a2d37] bg-[#0f1117] px-3 text-sm text-white" placeholder="0.0025" value={modelForm.cost_per_input_token} onChange={(e) => setModelForm({ ...modelForm, cost_per_input_token: e.target.value })} />
              </div>
              <div>
                <label className="mb-1 block text-xs text-gray-400">Cost/Output Token</label>
                <input type="number" step="0.0001" className="h-9 w-full rounded-md border border-[#2a2d37] bg-[#0f1117] px-3 text-sm text-white" placeholder="0.01" value={modelForm.cost_per_output_token} onChange={(e) => setModelForm({ ...modelForm, cost_per_output_token: e.target.value })} />
              </div>
              <div className="flex items-end">
                <Button type="submit" size="sm" className="w-full bg-purple-600 hover:bg-purple-700" disabled={creatingModel}>
                  {creatingModel ? "Registering…" : "Register"}
                </Button>
              </div>
            </div>
          </form>
        )}

        <div className="overflow-x-auto">
          {models.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12">
              <Cpu size={32} className="mb-2 text-gray-600" />
              <p className="text-sm text-gray-500">No models registered yet. Register a model to get started.</p>
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[#2a2d37] text-left text-xs text-gray-500">
                  <th className="px-4 py-2 font-medium">Name</th>
                  <th className="px-4 py-2 font-medium">Provider</th>
                  <th className="px-4 py-2 font-medium">Model ID</th>
                  <th className="px-4 py-2 font-medium">Status</th>
                  <th className="px-4 py-2 font-medium text-right">Cost/1K In</th>
                  <th className="px-4 py-2 font-medium text-right">Cost/1K Out</th>
                  <th className="px-4 py-2 font-medium">Capabilities</th>
                </tr>
              </thead>
              <tbody>
                {models.map((m) => (
                  <tr key={m.id} className="border-b border-[#2a2d37] hover:bg-white/5">
                    <td className="px-4 py-2 font-medium text-white">{m.name}</td>
                    <td className="px-4 py-2 text-gray-400">{m.provider}</td>
                    <td className="px-4 py-2 text-gray-400 font-mono text-xs">{m.model_id}</td>
                    <td className="px-4 py-2"><StatusBadge active={m.is_active} /></td>
                    <td className="px-4 py-2 text-right text-gray-400">${(m.cost_per_input_token * 1000).toFixed(2)}</td>
                    <td className="px-4 py-2 text-right text-gray-400">${(m.cost_per_output_token * 1000).toFixed(2)}</td>
                    <td className="px-4 py-2">
                      <div className="flex flex-wrap gap-1">
                        {(m.capabilities ?? []).map((c) => (
                          <span key={c} className="rounded bg-purple-500/20 px-1.5 py-0.5 text-[10px] font-medium text-purple-300">{c}</span>
                        ))}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* Rules */}
      <div className="rounded-lg border border-[#2a2d37] bg-[#1a1d27]">
        <div className="flex items-center justify-between border-b border-[#2a2d37] px-4 py-3">
          <h2 className="text-sm font-semibold text-white">Routing Rules</h2>
          <Button size="sm" className="bg-purple-600 hover:bg-purple-700" onClick={() => setShowRuleForm(!showRuleForm)}>
            {showRuleForm ? <><X size={14} className="mr-1.5" /> Cancel</> : <><Plus size={14} className="mr-1.5" /> Create Rule</>}
          </Button>
        </div>

        {showRuleForm && (
          <form onSubmit={handleCreateRule} className="border-b border-[#2a2d37] bg-[#0f1117] px-4 py-4">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <div>
                <label className="mb-1 block text-xs text-gray-400">Rule Name *</label>
                <input className="h-9 w-full rounded-md border border-[#2a2d37] bg-[#0f1117] px-3 text-sm text-white" placeholder="Cost-Optimized" value={ruleForm.name} onChange={(e) => setRuleForm({ ...ruleForm, name: e.target.value })} />
              </div>
              <div>
                <label className="mb-1 block text-xs text-gray-400">Conditions (JSON)</label>
                <input className="h-9 w-full rounded-md border border-[#2a2d37] bg-[#0f1117] px-3 text-sm text-white font-mono" placeholder='{"strategy":"cost"}' value={ruleForm.conditions} onChange={(e) => setRuleForm({ ...ruleForm, conditions: e.target.value })} />
              </div>
              <div>
                <label className="mb-1 block text-xs text-gray-400">Target Model ID *</label>
                <select value={ruleForm.target_model_id} onChange={(e) => setRuleForm({ ...ruleForm, target_model_id: e.target.value })} className="h-9 w-full rounded-md border border-[#2a2d37] bg-[#0f1117] px-3 text-sm text-white">
                  <option value="">Select model…</option>
                  {models.map((m) => (
                    <option key={m.id} value={m.id}>{m.name}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="mb-1 block text-xs text-gray-400">Priority</label>
                <input type="number" min="1" className="h-9 w-full rounded-md border border-[#2a2d37] bg-[#0f1117] px-3 text-sm text-white" value={ruleForm.priority} onChange={(e) => setRuleForm({ ...ruleForm, priority: e.target.value })} />
              </div>
              <div className="flex items-end sm:col-span-2 lg:col-span-4">
                <Button type="submit" size="sm" className="bg-purple-600 hover:bg-purple-700" disabled={creatingRule}>
                  {creatingRule ? "Creating…" : "Create Rule"}
                </Button>
              </div>
            </div>
          </form>
        )}

        <div className="overflow-x-auto">
          {rules.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12">
              <Zap size={32} className="mb-2 text-gray-600" />
              <p className="text-sm text-gray-500">No routing rules defined. Create rules to control model selection.</p>
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[#2a2d37] text-left text-xs text-gray-500">
                  <th className="px-4 py-2 font-medium">Name</th>
                  <th className="px-4 py-2 font-medium">Conditions</th>
                  <th className="px-4 py-2 font-medium">Target Model</th>
                  <th className="px-4 py-2 font-medium">Status</th>
                  <th className="px-4 py-2 font-medium text-right">Priority</th>
                </tr>
              </thead>
              <tbody>
                {rules.map((r) => (
                  <tr key={r.id} className="border-b border-[#2a2d37] hover:bg-white/5">
                    <td className="px-4 py-2 font-medium text-white">{r.name}</td>
                    <td className="px-4 py-2 text-gray-400 font-mono text-xs">{JSON.stringify(r.conditions)}</td>
                    <td className="px-4 py-2 text-gray-400">{r.target_model_id}</td>
                    <td className="px-4 py-2"><StatusBadge active={r.is_active} /></td>
                    <td className="px-4 py-2 text-right text-gray-400">{r.priority}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}
