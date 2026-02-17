import { useState } from "react";
import { Shield, Plus, Trash2, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/Button";
import type { ApprovalGate } from "@/types/models";

interface ApprovalGateConfigProps {
  gates: ApprovalGate[];
  onSave: (gates: Partial<ApprovalGate>[]) => Promise<void>;
  saving: boolean;
}

const STAGE_OPTIONS = [
  { value: "dev", label: "Draft" },
  { value: "staging", label: "Review" },
  { value: "canary", label: "Staging" },
  { value: "production", label: "Production" },
];

interface GateDraft {
  from_stage: string;
  to_stage: string;
  required_approvers: number;
  require_health_check: boolean;
  require_tests_pass: boolean;
  enabled: boolean;
}

export function ApprovalGateConfig({ gates, onSave, saving }: ApprovalGateConfigProps) {
  const [drafts, setDrafts] = useState<GateDraft[]>(
    gates.length > 0
      ? gates.map((g) => ({
          from_stage: g.from_stage,
          to_stage: g.to_stage,
          required_approvers: g.required_approvers,
          require_health_check: g.require_health_check,
          require_tests_pass: g.require_tests_pass,
          enabled: g.enabled,
        }))
      : [
          { from_stage: "dev", to_stage: "staging", required_approvers: 1, require_health_check: true, require_tests_pass: true, enabled: true },
          { from_stage: "staging", to_stage: "canary", required_approvers: 1, require_health_check: true, require_tests_pass: true, enabled: true },
          { from_stage: "canary", to_stage: "production", required_approvers: 2, require_health_check: true, require_tests_pass: true, enabled: true },
        ],
  );

  function addGate() {
    setDrafts([
      ...drafts,
      { from_stage: "dev", to_stage: "staging", required_approvers: 1, require_health_check: true, require_tests_pass: true, enabled: true },
    ]);
  }

  function removeGate(idx: number) {
    setDrafts(drafts.filter((_, i) => i !== idx));
  }

  function updateGate(idx: number, field: keyof GateDraft, value: unknown) {
    setDrafts(drafts.map((g, i) => (i === idx ? { ...g, [field]: value } : g)));
  }

  return (
    <div className="rounded-lg border border-[#2a2d37] bg-[#1a1d27] p-4">
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Shield size={14} className="text-purple-400" />
          <span className="text-sm font-medium text-white">Approval Gates</span>
        </div>
        <Button size="sm" variant="ghost" onClick={addGate}>
          <Plus size={12} className="mr-1" />
          Add Gate
        </Button>
      </div>

      <div className="space-y-3">
        {drafts.map((gate, idx) => (
          <div key={idx} className="rounded-md bg-black/20 p-3">
            <div className="flex items-start justify-between">
              <div className="grid flex-1 grid-cols-2 gap-3 sm:grid-cols-4">
                <div>
                  <label className="mb-1 block text-[10px] text-gray-500">From</label>
                  <select
                    value={gate.from_stage}
                    onChange={(e) => updateGate(idx, "from_stage", e.target.value)}
                    className="h-7 w-full rounded border border-[#2a2d37] bg-[#0f1117] px-2 text-[11px] text-white"
                  >
                    {STAGE_OPTIONS.map((s) => (
                      <option key={s.value} value={s.value}>{s.label}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="mb-1 block text-[10px] text-gray-500">To</label>
                  <select
                    value={gate.to_stage}
                    onChange={(e) => updateGate(idx, "to_stage", e.target.value)}
                    className="h-7 w-full rounded border border-[#2a2d37] bg-[#0f1117] px-2 text-[11px] text-white"
                  >
                    {STAGE_OPTIONS.map((s) => (
                      <option key={s.value} value={s.value}>{s.label}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="mb-1 block text-[10px] text-gray-500">Approvers</label>
                  <input
                    type="number"
                    min={1}
                    max={10}
                    value={gate.required_approvers}
                    onChange={(e) => updateGate(idx, "required_approvers", parseInt(e.target.value) || 1)}
                    className="h-7 w-full rounded border border-[#2a2d37] bg-[#0f1117] px-2 text-[11px] text-white"
                  />
                </div>
                <div className="space-y-1 pt-3">
                  <label className="flex items-center gap-1 text-[10px] text-gray-400">
                    <input
                      type="checkbox"
                      checked={gate.require_health_check}
                      onChange={(e) => updateGate(idx, "require_health_check", e.target.checked)}
                      className="h-3 w-3 accent-purple-500"
                    />
                    Health check
                  </label>
                  <label className="flex items-center gap-1 text-[10px] text-gray-400">
                    <input
                      type="checkbox"
                      checked={gate.require_tests_pass}
                      onChange={(e) => updateGate(idx, "require_tests_pass", e.target.checked)}
                      className="h-3 w-3 accent-purple-500"
                    />
                    Tests pass
                  </label>
                </div>
              </div>
              <div className="ml-2 flex items-center gap-1">
                <input
                  type="checkbox"
                  checked={gate.enabled}
                  onChange={(e) => updateGate(idx, "enabled", e.target.checked)}
                  title="Enabled"
                  className="h-3 w-3 accent-purple-500"
                />
                <Button variant="ghost" size="sm" className="h-6 w-6 p-0" onClick={() => removeGate(idx)}>
                  <Trash2 size={12} className="text-red-400" />
                </Button>
              </div>
            </div>
          </div>
        ))}
      </div>

      <div className="mt-3">
        <Button
          size="sm"
          className="bg-purple-600 hover:bg-purple-700"
          onClick={() => onSave(drafts)}
          disabled={saving}
        >
          {saving ? <Loader2 size={14} className="mr-1.5 animate-spin" /> : <Shield size={14} className="mr-1.5" />}
          Save Gates
        </Button>
      </div>
    </div>
  );
}
