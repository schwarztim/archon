import { useApiQuery } from "@/hooks/useApi";
import { apiGet } from "@/api/client";
import type { ModelRegistryEntry } from "@/types/models";

// ─── Types ───────────────────────────────────────────────────────────

export interface ModelData {
  provider: string;
  modelId: string;
  temperature: number;
  maxTokens: number;
  systemPrompt: string;
}

interface ModelStepProps {
  data: ModelData;
  onChange: (data: ModelData) => void;
}

// ─── Constants ───────────────────────────────────────────────────────

const PROVIDER_BADGES: Record<string, { color: string; label: string }> = {
  openai: { color: "bg-green-500/20 text-green-400", label: "OpenAI" },
  anthropic: { color: "bg-orange-500/20 text-orange-400", label: "Anthropic" },
  azure: { color: "bg-blue-500/20 text-blue-400", label: "Azure" },
  google: { color: "bg-yellow-500/20 text-yellow-400", label: "Google" },
  mistral: { color: "bg-cyan-500/20 text-cyan-400", label: "Mistral" },
  cohere: { color: "bg-pink-500/20 text-pink-400", label: "Cohere" },
  ollama: { color: "bg-gray-500/20 text-gray-400", label: "Ollama" },
};

const FALLBACK_MODELS = [
  { provider: "openai", model_id: "gpt-4o", name: "GPT-4o", max_tokens: 128000 },
  { provider: "openai", model_id: "gpt-4o-mini", name: "GPT-4o Mini", max_tokens: 128000 },
  { provider: "anthropic", model_id: "claude-sonnet-4-20250514", name: "Claude Sonnet 4", max_tokens: 200000 },
  { provider: "anthropic", model_id: "claude-3-5-haiku-20241022", name: "Claude 3.5 Haiku", max_tokens: 200000 },
  { provider: "google", model_id: "gemini-1.5-pro", name: "Gemini 1.5 Pro", max_tokens: 1000000 },
  { provider: "mistral", model_id: "mistral-large", name: "Mistral Large", max_tokens: 32000 },
  { provider: "ollama", model_id: "llama3.1", name: "Llama 3.1", max_tokens: 8192 },
];

const inputClass =
  "w-full rounded-lg border border-[#2a2d37] bg-[#1a1d27] px-3 py-2 text-sm text-white placeholder-gray-500 focus:border-purple-500 focus:outline-none";
const labelClass = "mb-1 block text-xs font-medium text-gray-400";

// ─── Component ───────────────────────────────────────────────────────

export function ModelStep({ data, onChange }: ModelStepProps) {
  const { data: modelsResp } = useApiQuery<ModelRegistryEntry[]>(
    ["router-models-wizard"],
    () => apiGet<ModelRegistryEntry[]>("/router/models", { limit: 100 }),
  );

  const registeredModels = modelsResp?.data ?? [];
  const models = registeredModels.length > 0
    ? registeredModels.map((m) => ({
        provider: m.provider.toLowerCase(),
        model_id: m.model_id,
        name: m.name,
        max_tokens: m.max_tokens,
      }))
    : FALLBACK_MODELS;

  const providers = [...new Set(models.map((m) => m.provider))];
  const filteredModels = models.filter((m) => m.provider === data.provider);

  const badge = PROVIDER_BADGES[data.provider] ?? { color: "bg-gray-500/20 text-gray-400", label: data.provider };

  return (
    <div className="space-y-4">
      {/* Provider Selector */}
      <div>
        <label className={labelClass}>Provider</label>
        <div className="flex flex-wrap gap-2">
          {providers.map((p) => {
            const b = PROVIDER_BADGES[p] ?? { color: "bg-gray-500/20 text-gray-400", label: p };
            return (
              <button
                key={p}
                type="button"
                onClick={() => {
                  const firstModel = models.find((m) => m.provider === p);
                  onChange({ ...data, provider: p, modelId: firstModel?.model_id ?? "" });
                }}
                className={`rounded-lg border px-3 py-1.5 text-sm font-medium transition-colors ${
                  data.provider === p
                    ? "border-purple-500 bg-purple-500/20 text-white"
                    : `border-[#2a2d37] ${b.color} hover:border-gray-600`
                }`}
              >
                {b.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Model Selector */}
      <div>
        <label className={labelClass}>Model</label>
        <div className="grid gap-2 sm:grid-cols-2">
          {filteredModels.map((m) => (
            <button
              key={m.model_id}
              type="button"
              onClick={() => onChange({ ...data, modelId: m.model_id })}
              className={`flex items-center justify-between rounded-lg border p-3 text-left text-sm transition-colors ${
                data.modelId === m.model_id
                  ? "border-purple-500 bg-purple-500/10"
                  : "border-[#2a2d37] bg-[#1a1d27] hover:border-gray-600"
              }`}
            >
              <div>
                <span className="font-medium text-white">{m.name}</span>
                <p className="text-xs text-gray-500">{m.model_id}</p>
              </div>
              <span className={`rounded-full px-2 py-0.5 text-xs ${badge.color}`}>
                {badge.label}
              </span>
            </button>
          ))}
        </div>
      </div>

      {/* Temperature */}
      <div>
        <label className={labelClass}>Temperature: {data.temperature.toFixed(1)}</label>
        <input
          type="range"
          min={0}
          max={2}
          step={0.1}
          value={data.temperature}
          onChange={(e) => onChange({ ...data, temperature: parseFloat(e.target.value) })}
          className="w-full accent-purple-500"
        />
        <div className="flex justify-between text-xs text-gray-600">
          <span>Precise</span>
          <span>Creative</span>
        </div>
      </div>

      {/* Max Tokens */}
      <div>
        <label className={labelClass}>Max Tokens</label>
        <input
          type="number"
          min={1}
          max={1000000}
          value={data.maxTokens}
          onChange={(e) => onChange({ ...data, maxTokens: parseInt(e.target.value, 10) || 4096 })}
          className={inputClass}
        />
      </div>

      {/* System Prompt */}
      <div>
        <label className={labelClass}>System Prompt</label>
        <textarea
          value={data.systemPrompt}
          onChange={(e) => onChange({ ...data, systemPrompt: e.target.value })}
          rows={5}
          className={inputClass}
          placeholder="You are a helpful assistant..."
        />
      </div>
    </div>
  );
}
