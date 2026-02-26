import { Label } from "@/components/ui/Label";
import { Input } from "@/components/ui/Input";
import { Info } from "lucide-react";

export interface WizardConfig {
  model: string;
  temperature: number;
  maxCostPerRun: number;
  guardrails: Record<string, boolean>;
  allowedDomains: string[];
}

const MODELS = [
  { id: "gpt-4o", label: "GPT-4o", provider: "OpenAI" },
  { id: "gpt-4o-mini", label: "GPT-4o Mini", provider: "OpenAI" },
  { id: "claude-3-5-sonnet", label: "Claude 3.5 Sonnet", provider: "Anthropic" },
  { id: "claude-3-opus", label: "Claude 3 Opus", provider: "Anthropic" },
  { id: "gemini-pro", label: "Gemini Pro", provider: "Google" },
  { id: "mistral-large", label: "Mistral Large", provider: "Mistral" },
  { id: "llama-3-70b", label: "Llama 3 70B", provider: "Ollama" },
];

const PROVIDER_COLORS: Record<string, string> = {
  OpenAI: "bg-green-500/20 text-green-400",
  Anthropic: "bg-orange-500/20 text-orange-400",
  Google: "bg-blue-500/20 text-blue-400",
  Mistral: "bg-purple-500/20 text-purple-400",
  Ollama: "bg-gray-500/20 text-gray-400",
};

const GUARDRAILS = [
  { key: "dlpScan", label: "DLP Scanning", tip: "Scans inputs and outputs for sensitive data like PII, secrets, and credentials" },
  { key: "contentSafety", label: "Content Safety", tip: "Filters harmful, inappropriate, or policy-violating content" },
  { key: "costLimit", label: "Cost Limits", tip: "Enforces per-execution cost caps to prevent runaway spending" },
  { key: "rateLimiting", label: "Rate Limiting", tip: "Limits requests per minute to protect against abuse" },
  { key: "humanApproval", label: "Human-in-the-Loop", tip: "Requires human approval for critical or irreversible actions" },
];

function tempLabel(t: number): string {
  if (t <= 0.3) return "Precise";
  if (t <= 0.7) return "Balanced";
  if (t <= 1.3) return "Creative";
  return "Very Creative";
}

interface ConfigFormProps {
  config: WizardConfig;
  onChange: (config: WizardConfig) => void;
}

export function ConfigForm({ config, onChange }: ConfigFormProps) {
  const update = (patch: Partial<WizardConfig>) =>
    onChange({ ...config, ...patch });

  const selectedModel = MODELS.find((m) => m.id === config.model);

  return (
    <div className="space-y-6">
      {/* Model Selection */}
      <div>
        <Label className="mb-2 block text-white">Model</Label>
        <div className="relative">
          <select
            value={config.model}
            onChange={(e) => update({ model: e.target.value })}
            className="h-9 w-full rounded-md border border-surface-border bg-surface-base px-3 text-sm text-white focus:border-purple-500 focus:outline-none"
            aria-label="Model selection"
          >
            {MODELS.map((m) => (
              <option key={m.id} value={m.id}>
                {m.label} ({m.provider})
              </option>
            ))}
          </select>
          {selectedModel && (
            <span
              className={`absolute right-10 top-1/2 -translate-y-1/2 rounded-full px-2 py-0.5 text-[10px] font-medium ${PROVIDER_COLORS[selectedModel.provider] ?? ""}`}
            >
              {selectedModel.provider}
            </span>
          )}
        </div>
      </div>

      {/* Temperature Slider */}
      <div>
        <Label className="mb-2 flex items-center gap-2 text-white">
          Temperature:{" "}
          <span className="text-purple-400">{config.temperature.toFixed(1)}</span>
          <span className="text-xs text-gray-500">({tempLabel(config.temperature)})</span>
        </Label>
        <input
          type="range"
          min={0}
          max={2}
          step={0.1}
          value={config.temperature}
          onChange={(e) => update({ temperature: parseFloat(e.target.value) })}
          className="w-full accent-purple-500"
          aria-label="Temperature"
        />
        <div className="flex justify-between text-[10px] text-gray-500">
          <span>Precise (0)</span>
          <span>Balanced (0.7)</span>
          <span>Creative (2)</span>
        </div>
      </div>

      {/* Guardrails */}
      <div>
        <Label className="mb-3 block text-white">Guardrails</Label>
        <div className="space-y-2">
          {GUARDRAILS.map((g) => (
            <label
              key={g.key}
              className="flex items-center gap-3 rounded-lg border border-surface-border bg-surface-base p-3 cursor-pointer hover:border-purple-500/30 transition-colors"
            >
              <input
                type="checkbox"
                checked={config.guardrails[g.key] ?? false}
                onChange={(e) =>
                  update({
                    guardrails: {
                      ...config.guardrails,
                      [g.key]: e.target.checked,
                    },
                  })
                }
                className="accent-purple-500"
              />
              <div className="flex-1">
                <p className="text-sm text-white">{g.label}</p>
                <p className="text-xs text-gray-500">{g.tip}</p>
              </div>
              <div className="group relative">
                <Info size={14} className="text-gray-600 cursor-help" />
                <div className="absolute bottom-full right-0 mb-2 hidden w-48 rounded-lg border border-surface-border bg-surface-overlay p-2 text-xs text-gray-300 shadow-xl group-hover:block z-10">
                  {g.tip}
                </div>
              </div>
            </label>
          ))}
        </div>
      </div>

      {/* Cost Limit */}
      {config.guardrails.costLimit && (
        <div>
          <Label className="mb-2 block text-white">Max Cost Per Run ($)</Label>
          <Input
            type="number"
            min={0}
            step={0.01}
            value={config.maxCostPerRun}
            onChange={(e) =>
              update({ maxCostPerRun: parseFloat(e.target.value) || 0 })
            }
            className="bg-surface-base text-white border-surface-border w-32"
            aria-label="Max cost per run"
          />
        </div>
      )}

      {/* Allowed Domains */}
      <div>
        <Label className="mb-2 block text-white">
          Allowed Domains{" "}
          <span className="text-xs text-gray-500">(one per line, optional)</span>
        </Label>
        <textarea
          rows={3}
          value={config.allowedDomains.join("\n")}
          onChange={(e) =>
            update({
              allowedDomains: e.target.value
                .split("\n")
                .map((d) => d.trim())
                .filter(Boolean),
            })
          }
          placeholder="example.com&#10;api.myservice.io"
          className="w-full rounded-md border border-surface-border bg-surface-base px-3 py-2 text-sm text-white placeholder:text-gray-600 focus:border-purple-500 focus:outline-none"
          aria-label="Allowed domains"
        />
      </div>
    </div>
  );
}
