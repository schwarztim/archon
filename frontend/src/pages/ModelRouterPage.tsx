import React, { useState, useEffect, useCallback } from "react";
import {
  GitFork,
  Plus,
  X,
  Cpu,
  Globe,
  Zap,
  CircleDot,
  Server,
  Loader2,
  ChevronUp,
  ChevronDown,
  ArrowRight,
  Key,
  Wifi,
  Activity,
  Shield,
  Trash2,
  Save,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import { apiGet, apiPost, apiPut } from "@/api/client";
import ProviderForm from "@/components/router/ProviderForm";
import TestConnectionButton from "@/components/router/TestConnectionButton";
import HealthDashboard from "@/components/router/HealthDashboard";
import RuleBuilder from "@/components/router/RuleBuilder";
import FallbackChain from "@/components/router/FallbackChain";
import {
  getVisualRules,
  saveVisualRules,
  getFallbackChain,
  saveFallbackChain as saveFallbackChainApi,
  type VisualRoutingRule,
} from "@/api/router";

/* ─── Types ─────────────────────────────────────────────────────────── */

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
  error_rate?: number;
}

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

interface ConditionRow {
  field: string;
  operator: string;
  value: string;
}

interface TestConnectionResult {
  provider_id: string;
  status: "loading" | "success" | "error";
  latency_ms?: number;
  message?: string;
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

const CONDITION_FIELDS = [
  { value: "capability", label: "Capability" },
  { value: "max_cost", label: "Max Cost" },
  { value: "min_context", label: "Min Context" },
  { value: "sensitivity_level", label: "Sensitivity Level" },
  { value: "tenant_tier", label: "Tenant Tier" },
];

const CONDITION_OPERATORS = [
  { value: "equals", label: "equals" },
  { value: "contains", label: "contains" },
  { value: "greater_than", label: "greater than" },
  { value: "less_than", label: "less than" },
  { value: "in", label: "in" },
];

/* ─── Helpers ───────────────────────────────────────────────────────── */

function conditionsToRows(conditions: Record<string, unknown>): ConditionRow[] {
  const rows: ConditionRow[] = [];
  for (const [key, val] of Object.entries(conditions)) {
    if (typeof val === "object" && val !== null && !Array.isArray(val)) {
      for (const [op, v] of Object.entries(val as Record<string, unknown>)) {
        rows.push({ field: key, operator: op, value: String(v) });
      }
    } else {
      rows.push({ field: key, operator: "equals", value: String(val) });
    }
  }
  return rows.length > 0 ? rows : [{ field: "capability", operator: "equals", value: "" }];
}

function rowsToConditions(rows: ConditionRow[]): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  for (const row of rows) {
    if (!row.value) continue;
    if (row.operator === "equals") {
      result[row.field] = row.value;
    } else {
      result[row.field] = { [row.operator]: row.value };
    }
  }
  return result;
}

/* ─── Sub-components ────────────────────────────────────────────────── */

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

function HealthStatusBadge({ status }: { status: string }) {
  const s = status.toLowerCase();
  if (s === "healthy") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-green-500/20 px-2 py-0.5 text-xs font-medium text-green-400">
        <CircleDot size={10} /> Healthy
      </span>
    );
  }
  if (s === "degraded") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-yellow-500/20 px-2 py-0.5 text-xs font-medium text-yellow-400">
        <CircleDot size={10} /> Degraded
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-red-500/20 px-2 py-0.5 text-xs font-medium text-red-400">
      <CircleDot size={10} /> Down
    </span>
  );
}

const inputCls = "h-9 w-full rounded-md border border-[#2a2d37] bg-[#0f1117] px-3 text-sm text-white";
const selectCls = inputCls;

/* ─── Main Component ────────────────────────────────────────────────── */

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

  // Provider form
  const [providerForm, setProviderForm] = useState({
    name: "", api_type: "openai", model_ids: "",
    capabilities: "", cost_per_1k_tokens: "", avg_latency_ms: "500",
    api_key: "",
  });
  const [apiKeySaved, setApiKeySaved] = useState<Record<string, boolean>>({});

  // Test connection
  const [testResults, setTestResults] = useState<Record<string, TestConnectionResult>>({});

  // Model form
  const [modelForm, setModelForm] = useState({
    name: "", provider: "", model_id: "", capabilities: "",
    context_window: "128000", cost_per_input_token: "", cost_per_output_token: "",
    speed_tier: "standard",
  });

  // Visual rule builder
  const [ruleFormName, setRuleFormName] = useState("");
  const [ruleFormTarget, setRuleFormTarget] = useState("");
  const [ruleFormPriority, setRuleFormPriority] = useState("1");
  const [ruleConditions, setRuleConditions] = useState<ConditionRow[]>([
    { field: "capability", operator: "equals", value: "" },
  ]);

  // Visual rules (new)
  const [visualRules, setVisualRules] = useState<VisualRoutingRule[]>([]);
  const [savingVisualRules, setSavingVisualRules] = useState(false);

  // Fallback chain
  const [fallbackChain, setFallbackChain] = useState<string[]>([]);
  const [savingFallback, setSavingFallback] = useState(false);

  // Expanded provider for credential form
  const [expandedProviderId, setExpandedProviderId] = useState<string | null>(null);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [modelsRes, rulesRes, providersRes, healthRes, visualRulesRes, fallbackRes] = await Promise.allSettled([
        apiGet<ModelEntry[]>("/router/models"),
        apiGet<RoutingRule[]>("/router/rules"),
        apiGet<Provider[]>("/router/providers"),
        apiGet<ProviderHealth[]>("/router/providers/health"),
        getVisualRules(),
        getFallbackChain(),
      ]);
      if (modelsRes.status === "fulfilled") setModels(Array.isArray(modelsRes.value.data) ? modelsRes.value.data : []);
      if (rulesRes.status === "fulfilled") setRules(Array.isArray(rulesRes.value.data) ? rulesRes.value.data : []);
      if (providersRes.status === "fulfilled") setProviders(Array.isArray(providersRes.value.data) ? providersRes.value.data : []);
      if (healthRes.status === "fulfilled") setProviderHealth(Array.isArray(healthRes.value.data) ? healthRes.value.data : []);
      if (visualRulesRes.status === "fulfilled") setVisualRules(Array.isArray(visualRulesRes.value.data) ? visualRulesRes.value.data : []);
      if (fallbackRes.status === "fulfilled" && fallbackRes.value.data) setFallbackChain(fallbackRes.value.data.model_ids ?? []);
    } catch {
      setError("Failed to load router data.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void fetchAll(); }, [fetchAll]);

  /* ── Handlers ──────────────────────────────────────────────────────── */

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
    if (!ruleFormName || !ruleFormTarget) return;
    setCreatingRule(true);
    try {
      const conditions = rowsToConditions(ruleConditions);
      await apiPost("/router/rules", {
        name: ruleFormName,
        conditions,
        target_model_id: ruleFormTarget,
        priority: parseInt(ruleFormPriority, 10) || 1,
        is_active: true,
      });
      setRuleFormName("");
      setRuleFormTarget("");
      setRuleFormPriority("1");
      setRuleConditions([{ field: "capability", operator: "equals", value: "" }]);
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
      const res = await apiPost<Provider>("/router/providers", {
        name: providerForm.name,
        api_type: providerForm.api_type,
        model_ids: providerForm.model_ids.split(",").map((s) => s.trim()).filter(Boolean),
        capabilities: providerForm.capabilities.split(",").map((s) => s.trim()).filter(Boolean),
        cost_per_1k_tokens: parseFloat(providerForm.cost_per_1k_tokens) || 0,
        avg_latency_ms: parseFloat(providerForm.avg_latency_ms) || 500,
        is_active: true,
      });
      // Save API key if provided
      if (providerForm.api_key && res.data?.id) {
        try {
          await apiPost(`/router/providers/${res.data.id}/api-key`, { api_key: providerForm.api_key });
          setApiKeySaved((prev) => ({ ...prev, [res.data!.id]: true }));
        } catch { /* key save failed silently */ }
      }
      setProviderForm({ name: "", api_type: "openai", model_ids: "", capabilities: "", cost_per_1k_tokens: "", avg_latency_ms: "500", api_key: "" });
      setShowProviderForm(false);
      await fetchAll();
    } catch {
      setError("Failed to create provider.");
    } finally {
      setCreatingProvider(false);
    }
  }

  async function handleSaveApiKey(providerId: string, key: string) {
    try {
      await apiPost(`/router/providers/${providerId}/api-key`, { api_key: key });
      setApiKeySaved((prev) => ({ ...prev, [providerId]: true }));
    } catch {
      setError("Failed to save API key.");
    }
  }

  async function handleTestConnection(providerId: string) {
    setTestResults((prev) => ({
      ...prev,
      [providerId]: { provider_id: providerId, status: "loading" },
    }));
    try {
      const res = await apiPost<{ latency_ms?: number; message?: string }>(
        `/router/providers/${providerId}/test-connection`,
        {},
      );
      setTestResults((prev) => ({
        ...prev,
        [providerId]: {
          provider_id: providerId,
          status: "success",
          latency_ms: res.data?.latency_ms,
          message: res.data?.message ?? "Connection successful",
        },
      }));
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Connection failed";
      setTestResults((prev) => ({
        ...prev,
        [providerId]: { provider_id: providerId, status: "error", message: msg },
      }));
    }
  }

  async function handleSaveFallbackChain() {
    const chain = fallbackChain.filter(Boolean);
    if (chain.length === 0) return;
    setSavingFallback(true);
    try {
      await saveFallbackChainApi({ model_ids: chain });
    } catch {
      setError("Failed to save fallback chain.");
    } finally {
      setSavingFallback(false);
    }
  }

  async function handleSaveVisualRules() {
    setSavingVisualRules(true);
    try {
      const res = await saveVisualRules(visualRules);
      setVisualRules(res.data);
    } catch {
      setError("Failed to save routing rules.");
    } finally {
      setSavingVisualRules(false);
    }
  }

  // Condition row helpers
  function updateCondition(idx: number, patch: Partial<ConditionRow>) {
    setRuleConditions((prev) => prev.map((c, i) => (i === idx ? { ...c, ...patch } : c)));
  }
  function addCondition() {
    setRuleConditions((prev) => [...prev, { field: "capability", operator: "equals", value: "" }]);
  }
  function removeCondition(idx: number) {
    setRuleConditions((prev) => prev.length > 1 ? prev.filter((_, i) => i !== idx) : prev);
  }

  // Rule reorder
  function moveRule(idx: number, direction: "up" | "down") {
    setRules((prev) => {
      const arr = [...prev];
      const swapIdx = direction === "up" ? idx - 1 : idx + 1;
      if (swapIdx < 0 || swapIdx >= arr.length) return prev;
      const tmp = arr[idx]!;
      arr[idx] = arr[swapIdx]!;
      arr[swapIdx] = tmp;
      return arr;
    });
  }

  /* ── Render ────────────────────────────────────────────────────────── */

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 size={24} className="animate-spin text-purple-400" />
        <p className="ml-2 text-gray-400">Loading...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6">
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-4 text-red-400">{error}</div>
        <Button size="sm" className="mt-3" onClick={() => { setError(null); void fetchAll(); }}>Retry</Button>
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

      {/* ── Provider Health Dashboard ────────────────────────────────── */}
      <div className="mb-6 rounded-lg border border-[#2a2d37] bg-[#1a1d27] p-4">
        <HealthDashboard />
      </div>

      {/* ── Providers ────────────────────────────────────────────────── */}
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
                <input className={inputCls} placeholder="My OpenAI" value={providerForm.name} onChange={(e) => setProviderForm({ ...providerForm, name: e.target.value })} />
              </div>
              <div>
                <label className="mb-1 block text-xs text-gray-400">Type *</label>
                <select className={selectCls} value={providerForm.api_type} onChange={(e) => setProviderForm({ ...providerForm, api_type: e.target.value })}>
                  {PROVIDER_TYPES.map((pt) => (
                    <option key={pt.value} value={pt.value}>{pt.label}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="mb-1 block text-xs text-gray-400">Supported Models (comma-sep)</label>
                <input className={inputCls} placeholder="gpt-4o, gpt-4o-mini" value={providerForm.model_ids} onChange={(e) => setProviderForm({ ...providerForm, model_ids: e.target.value })} />
              </div>
              <div>
                <label className="mb-1 block text-xs text-gray-400">Capabilities (comma-sep)</label>
                <input className={inputCls} placeholder="chat, code, vision" value={providerForm.capabilities} onChange={(e) => setProviderForm({ ...providerForm, capabilities: e.target.value })} />
              </div>
              <div>
                <label className="mb-1 block text-xs text-gray-400">Cost / 1K Tokens</label>
                <input type="number" step="0.001" className={inputCls} placeholder="0.03" value={providerForm.cost_per_1k_tokens} onChange={(e) => setProviderForm({ ...providerForm, cost_per_1k_tokens: e.target.value })} />
              </div>
              <div>
                <label className="mb-1 block text-xs text-gray-400">Avg Latency (ms)</label>
                <input type="number" className={inputCls} placeholder="500" value={providerForm.avg_latency_ms} onChange={(e) => setProviderForm({ ...providerForm, avg_latency_ms: e.target.value })} />
              </div>
              {/* API Key field */}
              <div>
                <label className="mb-1 flex items-center gap-1 text-xs text-gray-400">
                  <Key size={12} /> API Key
                </label>
                <input
                  type="password"
                  className={inputCls}
                  placeholder="sk-…"
                  value={providerForm.api_key}
                  onChange={(e) => setProviderForm({ ...providerForm, api_key: e.target.value })}
                  autoComplete="new-password"
                />
              </div>
              <div className="flex items-end">
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
                  <th className="px-4 py-2 font-medium">API Key</th>
                  <th className="px-4 py-2 font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {providers.map((p) => {
                  const health = providerHealth.find((h) => h.provider_id === p.id);
                  const testResult = testResults[p.id];
                  return (
                    <React.Fragment key={p.id}>
                    <tr className="border-b border-[#2a2d37] hover:bg-white/5">
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
                          <HealthStatusBadge status={health.status} />
                        ) : (
                          <span className="text-xs text-gray-500">—</span>
                        )}
                      </td>
                      <td className="px-4 py-2 text-right text-gray-400">${p.cost_per_1k_tokens.toFixed(3)}</td>
                      <td className="px-4 py-2 text-right text-gray-400">{p.avg_latency_ms}ms</td>
                      {/* API Key column */}
                      <td className="px-4 py-2">
                        <ProviderApiKeyCell
                          providerId={p.id}
                          saved={!!apiKeySaved[p.id]}
                          onSave={(key) => handleSaveApiKey(p.id, key)}
                        />
                      </td>
                      {/* Test Connection + Expand */}
                      <td className="px-4 py-2">
                        <div className="flex items-center gap-2">
                          <TestConnectionButton providerId={p.id} />
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-7 text-xs text-gray-400"
                            onClick={() => setExpandedProviderId(expandedProviderId === p.id ? null : p.id)}
                            aria-label="Configure credentials"
                          >
                            <Key size={12} className="mr-1" />
                            Credentials
                          </Button>
                        </div>
                      </td>
                    </tr>
                    {/* Expanded credential form */}
                    {expandedProviderId === p.id && (
                      <tr className="border-b border-[#2a2d37] bg-[#0f1117]">
                        <td colSpan={9} className="px-8 py-4">
                          <ProviderForm
                            providerId={p.id}
                            providerType={p.api_type}
                            hasCredentialsSaved={!!apiKeySaved[p.id]}
                            onCredentialsSaved={() => {
                              setApiKeySaved((prev) => ({ ...prev, [p.id]: true }));
                            }}
                          />
                        </td>
                      </tr>
                    )}
                    </React.Fragment>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* ── Models ───────────────────────────────────────────────────── */}
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
                <input className={inputCls} placeholder="GPT-4o" value={modelForm.name} onChange={(e) => setModelForm({ ...modelForm, name: e.target.value })} />
              </div>
              <div>
                <label className="mb-1 block text-xs text-gray-400">Provider *</label>
                <select className={selectCls} value={modelForm.provider} onChange={(e) => setModelForm({ ...modelForm, provider: e.target.value })}>
                  <option value="">Select provider…</option>
                  {providers.map((p) => (
                    <option key={p.id} value={p.name}>{p.name} ({PROVIDER_TYPES.find((pt) => pt.value === p.api_type)?.label ?? p.api_type})</option>
                  ))}
                  <option value="__custom__">Custom…</option>
                </select>
                {modelForm.provider === "__custom__" && (
                  <input className={"mt-1 " + inputCls} placeholder="Custom provider name" onChange={(e) => setModelForm({ ...modelForm, provider: e.target.value || "__custom__" })} />
                )}
              </div>
              <div>
                <label className="mb-1 block text-xs text-gray-400">Model ID *</label>
                <input className={inputCls} placeholder="gpt-4o" value={modelForm.model_id} onChange={(e) => setModelForm({ ...modelForm, model_id: e.target.value })} />
              </div>
              <div>
                <label className="mb-1 block text-xs text-gray-400">Capabilities (comma-sep)</label>
                <input className={inputCls} placeholder="chat, code" value={modelForm.capabilities} onChange={(e) => setModelForm({ ...modelForm, capabilities: e.target.value })} />
              </div>
              <div>
                <label className="mb-1 block text-xs text-gray-400">Context Window</label>
                <input type="number" className={inputCls} value={modelForm.context_window} onChange={(e) => setModelForm({ ...modelForm, context_window: e.target.value })} />
              </div>
              <div>
                <label className="mb-1 block text-xs text-gray-400">Cost/Input Token</label>
                <input type="number" step="0.0001" className={inputCls} placeholder="0.0025" value={modelForm.cost_per_input_token} onChange={(e) => setModelForm({ ...modelForm, cost_per_input_token: e.target.value })} />
              </div>
              <div>
                <label className="mb-1 block text-xs text-gray-400">Cost/Output Token</label>
                <input type="number" step="0.0001" className={inputCls} placeholder="0.01" value={modelForm.cost_per_output_token} onChange={(e) => setModelForm({ ...modelForm, cost_per_output_token: e.target.value })} />
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

      {/* ── Visual Routing Rules ────────────────────────────────────── */}
      <div className="mb-6 rounded-lg border border-[#2a2d37] bg-[#1a1d27]">
        <div className="flex items-center justify-between border-b border-[#2a2d37] px-4 py-3">
          <h2 className="text-sm font-semibold text-white">Visual Routing Rules</h2>
          <Button
            size="sm"
            className="bg-purple-600 hover:bg-purple-700 gap-1"
            onClick={handleSaveVisualRules}
            disabled={savingVisualRules}
          >
            <Save size={14} />
            {savingVisualRules ? "Saving…" : "Save Rules"}
          </Button>
        </div>
        <div className="p-4">
          <RuleBuilder
            rules={visualRules}
            models={models.map((m) => ({ id: m.id, name: m.name }))}
            onRulesChange={setVisualRules}
          />
        </div>
      </div>

      {/* ── Legacy Routing Rules ────────────────────────────────────── */}
      <div className="mb-6 rounded-lg border border-[#2a2d37] bg-[#1a1d27]">
        <div className="flex items-center justify-between border-b border-[#2a2d37] px-4 py-3">
          <h2 className="text-sm font-semibold text-white">Routing Rules</h2>
          <Button size="sm" className="bg-purple-600 hover:bg-purple-700" onClick={() => setShowRuleForm(!showRuleForm)}>
            {showRuleForm ? <><X size={14} className="mr-1.5" /> Cancel</> : <><Plus size={14} className="mr-1.5" /> Add Rule</>}
          </Button>
        </div>

        {showRuleForm && (
          <form onSubmit={handleCreateRule} className="border-b border-[#2a2d37] bg-[#0f1117] px-4 py-4">
            <div className="mb-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
              <div>
                <label className="mb-1 block text-xs text-gray-400">Rule Name *</label>
                <input className={inputCls} placeholder="Cost-Optimized" value={ruleFormName} onChange={(e) => setRuleFormName(e.target.value)} />
              </div>
              <div>
                <label className="mb-1 block text-xs text-gray-400">Route to Model *</label>
                <select className={selectCls} value={ruleFormTarget} onChange={(e) => setRuleFormTarget(e.target.value)}>
                  <option value="">Select model…</option>
                  {models.map((m) => (
                    <option key={m.id} value={m.id}>{m.name}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="mb-1 block text-xs text-gray-400">Priority</label>
                <input type="number" min="1" className={inputCls} value={ruleFormPriority} onChange={(e) => setRuleFormPriority(e.target.value)} />
              </div>
            </div>

            {/* Visual Condition Rows */}
            <div className="mb-3">
              <label className="mb-2 block text-xs font-medium text-gray-300">Conditions</label>
              <div className="space-y-2">
                {ruleConditions.map((cond, idx) => (
                  <div key={idx} className="flex items-center gap-2">
                    <span className="w-6 text-xs text-gray-500">{idx === 0 ? "IF" : "AND"}</span>
                    <select className={selectCls + " max-w-[160px]"} value={cond.field} onChange={(e) => updateCondition(idx, { field: e.target.value })}>
                      {CONDITION_FIELDS.map((f) => (
                        <option key={f.value} value={f.value}>{f.label}</option>
                      ))}
                    </select>
                    <select className={selectCls + " max-w-[140px]"} value={cond.operator} onChange={(e) => updateCondition(idx, { operator: e.target.value })}>
                      {CONDITION_OPERATORS.map((o) => (
                        <option key={o.value} value={o.value}>{o.label}</option>
                      ))}
                    </select>
                    <input className={inputCls + " max-w-[200px]"} placeholder="value" value={cond.value} onChange={(e) => updateCondition(idx, { value: e.target.value })} />
                    {ruleConditions.length > 1 && (
                      <button type="button" onClick={() => removeCondition(idx)} className="text-gray-500 hover:text-red-400">
                        <Trash2 size={14} />
                      </button>
                    )}
                  </div>
                ))}
              </div>
              <Button type="button" size="sm" variant="ghost" className="mt-2 gap-1 text-xs text-purple-400" onClick={addCondition}>
                <Plus size={12} /> Add Condition
              </Button>
            </div>

            <Button type="submit" size="sm" className="bg-purple-600 hover:bg-purple-700" disabled={creatingRule}>
              {creatingRule ? "Creating…" : "Create Rule"}
            </Button>
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
                  <th className="w-16 px-4 py-2 font-medium">Order</th>
                  <th className="px-4 py-2 font-medium">Name</th>
                  <th className="px-4 py-2 font-medium">Conditions</th>
                  <th className="px-4 py-2 font-medium">Target Model</th>
                  <th className="px-4 py-2 font-medium">Status</th>
                  <th className="px-4 py-2 font-medium text-right">Priority</th>
                </tr>
              </thead>
              <tbody>
                {rules.map((r, idx) => {
                  const condRows = conditionsToRows(r.conditions as Record<string, unknown>);
                  const targetModel = models.find((m) => m.id === r.target_model_id);
                  return (
                    <tr key={r.id} className="border-b border-[#2a2d37] hover:bg-white/5">
                      <td className="px-4 py-2">
                        <div className="flex gap-0.5">
                          <button
                            className="text-gray-500 hover:text-purple-400 disabled:opacity-30"
                            disabled={idx === 0}
                            onClick={() => moveRule(idx, "up")}
                          >
                            <ChevronUp size={14} />
                          </button>
                          <button
                            className="text-gray-500 hover:text-purple-400 disabled:opacity-30"
                            disabled={idx === rules.length - 1}
                            onClick={() => moveRule(idx, "down")}
                          >
                            <ChevronDown size={14} />
                          </button>
                        </div>
                      </td>
                      <td className="px-4 py-2 font-medium text-white">{r.name}</td>
                      <td className="px-4 py-2">
                        <div className="space-y-0.5">
                          {condRows.map((c, ci) => (
                            <div key={ci} className="flex items-center gap-1 text-xs">
                              <span className="text-gray-500">{ci === 0 ? "IF" : "AND"}</span>
                              <span className="rounded bg-purple-500/20 px-1.5 py-0.5 text-purple-300">{c.field}</span>
                              <span className="text-gray-500">{c.operator}</span>
                              <span className="font-mono text-white">{c.value}</span>
                            </div>
                          ))}
                        </div>
                      </td>
                      <td className="px-4 py-2 text-gray-400">{targetModel?.name ?? r.target_model_id}</td>
                      <td className="px-4 py-2"><StatusBadge active={r.is_active} /></td>
                      <td className="px-4 py-2 text-right text-gray-400">{r.priority}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* ── Fallback Chain ───────────────────────────────────────────── */}
      <div className="rounded-lg border border-[#2a2d37] bg-[#1a1d27]">
        <div className="flex items-center justify-between border-b border-[#2a2d37] px-4 py-3">
          <div className="flex items-center gap-2">
            <Shield size={16} className="text-purple-400" />
            <h2 className="text-sm font-semibold text-white">Fallback Chain</h2>
          </div>
          <Button
            size="sm"
            className="bg-purple-600 hover:bg-purple-700 gap-1"
            onClick={handleSaveFallbackChain}
            disabled={savingFallback}
          >
            <Save size={14} />
            {savingFallback ? "Saving…" : "Save Chain"}
          </Button>
        </div>
        <div className="p-4">
          <FallbackChain
            modelIds={fallbackChain}
            availableModels={models.map((m) => ({ id: m.id, name: m.name, provider: m.provider }))}
            onChange={setFallbackChain}
          />
        </div>
      </div>
    </div>
  );
}

/* ─── Inline API Key Cell ───────────────────────────────────────────── */

function ProviderApiKeyCell({
  saved,
  onSave,
}: {
  providerId: string;
  saved: boolean;
  onSave: (key: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState("");

  if (saved && !editing) {
    return (
      <span className="inline-flex items-center gap-1 text-xs text-green-400">
        ••••••••
        <span title="Key saved">✅</span>
      </span>
    );
  }

  if (!editing) {
    return (
      <button
        className="inline-flex items-center gap-1 text-xs text-gray-400 hover:text-purple-400"
        onClick={() => setEditing(true)}
      >
        <Key size={12} /> Set key
      </button>
    );
  }

  return (
    <div className="flex items-center gap-1">
      <input
        type="password"
        className="h-7 w-28 rounded border border-[#2a2d37] bg-[#0f1117] px-2 text-xs text-white"
        placeholder="sk-…"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        autoComplete="new-password"
      />
      <Button
        size="sm"
        className="h-7 bg-purple-600 px-2 text-xs hover:bg-purple-700"
        onClick={() => {
          if (value) {
            onSave(value);
            setValue("");
            setEditing(false);
          }
        }}
      >
        Save
      </Button>
      <button className="text-gray-500 hover:text-red-400" onClick={() => { setEditing(false); setValue(""); }}>
        <X size={12} />
      </button>
    </div>
  );
}
