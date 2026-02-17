import { useState } from "react";
import { Button } from "@/components/ui/Button";

interface BudgetWizardProps {
  onSubmit: (data: BudgetFormData) => Promise<void>;
  onCancel: () => void;
}

export interface BudgetFormData {
  name: string;
  scope: string;
  scope_id?: string;
  limit_amount: number;
  period: string;
  enforcement: string;
  alert_thresholds: number[];
}

export function BudgetWizard({ onSubmit, onCancel }: BudgetWizardProps) {
  const [step, setStep] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [form, setForm] = useState<BudgetFormData>({
    name: "",
    scope: "tenant",
    limit_amount: 0,
    period: "monthly",
    enforcement: "soft",
    alert_thresholds: [50, 75, 90, 100],
  });

  async function handleSubmit() {
    if (!form.name || form.limit_amount <= 0) return;
    setSubmitting(true);
    try {
      await onSubmit(form);
    } finally {
      setSubmitting(false);
    }
  }

  const steps = [
    // Step 0: Scope
    <div key="scope" className="space-y-3">
      <h3 className="text-sm font-semibold text-white">1. Select Scope</h3>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {["tenant", "team", "agent", "user"].map((s) => (
          <button
            key={s}
            onClick={() => setForm({ ...form, scope: s })}
            className={`rounded-lg border p-3 text-center text-sm font-medium transition-colors ${
              form.scope === s
                ? "border-purple-500 bg-purple-500/20 text-purple-300"
                : "border-[#2a2d37] bg-[#0f1117] text-gray-400 hover:border-purple-500/50"
            }`}
          >
            {s.charAt(0).toUpperCase() + s.slice(1)}
          </button>
        ))}
      </div>
    </div>,
    // Step 1: Limit & Period
    <div key="limit" className="space-y-3">
      <h3 className="text-sm font-semibold text-white">2. Set Budget</h3>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div>
          <label className="mb-1 block text-xs text-gray-400">Budget Name *</label>
          <input
            className="h-9 w-full rounded-md border border-[#2a2d37] bg-[#0f1117] px-3 text-sm text-white"
            placeholder="Production LLM Budget"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
        </div>
        <div>
          <label className="mb-1 block text-xs text-gray-400">Limit ($) *</label>
          <input
            type="number"
            min="1"
            step="0.01"
            className="h-9 w-full rounded-md border border-[#2a2d37] bg-[#0f1117] px-3 text-sm text-white"
            placeholder="5000"
            value={form.limit_amount || ""}
            onChange={(e) => setForm({ ...form, limit_amount: parseFloat(e.target.value) || 0 })}
          />
        </div>
        <div>
          <label className="mb-1 block text-xs text-gray-400">Period</label>
          <select
            value={form.period}
            onChange={(e) => setForm({ ...form, period: e.target.value })}
            className="h-9 w-full rounded-md border border-[#2a2d37] bg-[#0f1117] px-3 text-sm text-white"
          >
            <option value="daily">Daily</option>
            <option value="weekly">Weekly</option>
            <option value="monthly">Monthly</option>
          </select>
        </div>
      </div>
    </div>,
    // Step 2: Enforcement
    <div key="enforcement" className="space-y-3">
      <h3 className="text-sm font-semibold text-white">3. Enforcement</h3>
      <div className="grid grid-cols-2 gap-3">
        <button
          onClick={() => setForm({ ...form, enforcement: "soft" })}
          className={`rounded-lg border p-4 text-left transition-colors ${
            form.enforcement === "soft"
              ? "border-yellow-500 bg-yellow-500/10"
              : "border-[#2a2d37] bg-[#0f1117] hover:border-yellow-500/50"
          }`}
        >
          <div className="text-sm font-semibold text-white">Soft Limit</div>
          <p className="mt-1 text-xs text-gray-400">Warn when budget thresholds are crossed but allow execution to continue.</p>
        </button>
        <button
          onClick={() => setForm({ ...form, enforcement: "hard" })}
          className={`rounded-lg border p-4 text-left transition-colors ${
            form.enforcement === "hard"
              ? "border-red-500 bg-red-500/10"
              : "border-[#2a2d37] bg-[#0f1117] hover:border-red-500/50"
          }`}
        >
          <div className="text-sm font-semibold text-white">Hard Limit</div>
          <p className="mt-1 text-xs text-gray-400">Block execution with HTTP 429 when budget is exceeded.</p>
        </button>
      </div>
    </div>,
  ];

  return (
    <div className="border-b border-[#2a2d37] bg-[#0f1117] px-4 py-4">
      {steps[step]}
      <div className="mt-4 flex items-center justify-between">
        <div className="flex gap-1">
          {steps.map((_, i) => (
            <div
              key={i}
              className={`h-1.5 w-8 rounded-full transition-colors ${
                i <= step ? "bg-purple-500" : "bg-white/10"
              }`}
            />
          ))}
        </div>
        <div className="flex gap-2">
          <Button size="sm" variant="outline" onClick={step === 0 ? onCancel : () => setStep(step - 1)}>
            {step === 0 ? "Cancel" : "Back"}
          </Button>
          {step < steps.length - 1 ? (
            <Button size="sm" className="bg-purple-600 hover:bg-purple-700" onClick={() => setStep(step + 1)}>
              Next
            </Button>
          ) : (
            <Button
              size="sm"
              className="bg-purple-600 hover:bg-purple-700"
              onClick={handleSubmit}
              disabled={submitting || !form.name || form.limit_amount <= 0}
            >
              {submitting ? "Creating…" : "Create Budget"}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
