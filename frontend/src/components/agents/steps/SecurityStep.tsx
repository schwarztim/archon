import { useState, useCallback } from "react";
import { X } from "lucide-react";

// ─── Types ───────────────────────────────────────────────────────────

export interface SecurityData {
  dlpEnabled: boolean;
  guardrailPolicies: string[];
  maxCostPerRun: number;
  allowedDomains: string[];
  piiHandling: string;
}

interface SecurityStepProps {
  data: SecurityData;
  onChange: (data: SecurityData) => void;
}

// ─── Constants ───────────────────────────────────────────────────────

const GUARDRAIL_OPTIONS = [
  { id: "content-safety", label: "Content Safety", description: "Block harmful or inappropriate content" },
  { id: "pii-detection", label: "PII Detection", description: "Detect personally identifiable information" },
  { id: "prompt-injection", label: "Prompt Injection Guard", description: "Protect against prompt injection attacks" },
  { id: "output-validation", label: "Output Validation", description: "Validate output format and content" },
  { id: "rate-limiting", label: "Rate Limiting", description: "Limit request frequency per user" },
  { id: "topic-guardrail", label: "Topic Guardrail", description: "Keep conversations on-topic" },
];

const PII_MODES = [
  { value: "block", label: "Block", description: "Reject requests containing PII" },
  { value: "redact", label: "Redact", description: "Replace PII with placeholders" },
  { value: "mask", label: "Mask", description: "Partially mask PII values" },
  { value: "log", label: "Log Only", description: "Allow but log PII occurrences" },
  { value: "allow", label: "Allow", description: "No PII handling" },
];

const inputClass =
  "w-full rounded-lg border border-[#2a2d37] bg-[#1a1d27] px-3 py-2 text-sm text-white placeholder-gray-500 focus:border-purple-500 focus:outline-none";
const labelClass = "mb-1 block text-xs font-medium text-gray-400";

// ─── Component ───────────────────────────────────────────────────────

export function SecurityStep({ data, onChange }: SecurityStepProps) {
  const [domainInput, setDomainInput] = useState("");

  const addDomain = useCallback(() => {
    const d = domainInput.trim().toLowerCase();
    if (d && !data.allowedDomains.includes(d)) {
      onChange({ ...data, allowedDomains: [...data.allowedDomains, d] });
    }
    setDomainInput("");
  }, [domainInput, data, onChange]);

  const toggleGuardrail = (id: string) => {
    onChange({
      ...data,
      guardrailPolicies: data.guardrailPolicies.includes(id)
        ? data.guardrailPolicies.filter((g) => g !== id)
        : [...data.guardrailPolicies, id],
    });
  };

  return (
    <div className="space-y-5">
      {/* DLP Toggle */}
      <div className="flex items-center justify-between rounded-lg border border-[#2a2d37] bg-[#1a1d27] p-4">
        <div>
          <p className="text-sm font-medium text-white">Data Loss Prevention (DLP)</p>
          <p className="text-xs text-gray-500">Scan inputs and outputs for sensitive data</p>
        </div>
        <button
          type="button"
          onClick={() => onChange({ ...data, dlpEnabled: !data.dlpEnabled })}
          className={`relative h-6 w-11 rounded-full transition-colors ${
            data.dlpEnabled ? "bg-purple-600" : "bg-gray-700"
          }`}
        >
          <span
            className={`absolute left-0.5 top-0.5 h-5 w-5 rounded-full bg-white transition-transform ${
              data.dlpEnabled ? "translate-x-5" : ""
            }`}
          />
        </button>
      </div>

      {/* Guardrail Policies */}
      <div>
        <label className={labelClass}>Guardrail Policies</label>
        <div className="grid gap-2 sm:grid-cols-2">
          {GUARDRAIL_OPTIONS.map((g) => {
            const isSelected = data.guardrailPolicies.includes(g.id);
            return (
              <button
                key={g.id}
                type="button"
                onClick={() => toggleGuardrail(g.id)}
                className={`flex items-start gap-3 rounded-lg border p-3 text-left transition-colors ${
                  isSelected
                    ? "border-purple-500 bg-purple-500/10"
                    : "border-[#2a2d37] bg-[#1a1d27] hover:border-gray-600"
                }`}
              >
                <div
                  className={`mt-0.5 h-4 w-4 flex-shrink-0 rounded border ${
                    isSelected
                      ? "border-purple-500 bg-purple-500"
                      : "border-gray-600 bg-transparent"
                  } flex items-center justify-center`}
                >
                  {isSelected && (
                    <svg viewBox="0 0 12 12" className="h-3 w-3 text-white">
                      <path d="M10 3L4.5 8.5L2 6" stroke="currentColor" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  )}
                </div>
                <div>
                  <span className="text-sm font-medium text-white">{g.label}</span>
                  <p className="text-xs text-gray-500">{g.description}</p>
                </div>
              </button>
            );
          })}
        </div>
      </div>

      {/* Cost Limit */}
      <div>
        <label className={labelClass}>Max Cost Per Run ($): {data.maxCostPerRun.toFixed(2)}</label>
        <input
          type="range"
          min={0.01}
          max={10}
          step={0.01}
          value={data.maxCostPerRun}
          onChange={(e) => onChange({ ...data, maxCostPerRun: parseFloat(e.target.value) })}
          className="w-full accent-purple-500"
        />
        <div className="flex justify-between text-xs text-gray-600">
          <span>$0.01</span>
          <span>$10.00</span>
        </div>
      </div>

      {/* PII Handling Mode */}
      <div>
        <label className={labelClass}>PII Handling Mode</label>
        <div className="grid gap-2 sm:grid-cols-3">
          {PII_MODES.map((mode) => (
            <button
              key={mode.value}
              type="button"
              onClick={() => onChange({ ...data, piiHandling: mode.value })}
              className={`rounded-lg border p-3 text-left text-sm transition-colors ${
                data.piiHandling === mode.value
                  ? "border-purple-500 bg-purple-500/10"
                  : "border-[#2a2d37] bg-[#1a1d27] hover:border-gray-600"
              }`}
            >
              <span className="font-medium text-white">{mode.label}</span>
              <p className="text-xs text-gray-500">{mode.description}</p>
            </button>
          ))}
        </div>
      </div>

      {/* Allowed Domains */}
      <div>
        <label className={labelClass}>Allowed Domains</label>
        <div className="mb-2 flex flex-wrap gap-1">
          {data.allowedDomains.map((d) => (
            <span
              key={d}
              className="flex items-center gap-1 rounded-full bg-blue-500/20 px-2 py-0.5 text-xs text-blue-300"
            >
              {d}
              <button
                type="button"
                onClick={() => onChange({ ...data, allowedDomains: data.allowedDomains.filter((x) => x !== d) })}
                className="hover:text-white"
              >
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
            onKeyDown={(e) => {
              if (e.key === "Enter") { e.preventDefault(); addDomain(); }
            }}
            className={`flex-1 ${inputClass}`}
            placeholder="example.com"
          />
          <button
            type="button"
            onClick={addDomain}
            className="rounded-lg border border-[#2a2d37] px-3 py-2 text-sm text-gray-400 hover:bg-white/5"
          >
            Add
          </button>
        </div>
      </div>
    </div>
  );
}
