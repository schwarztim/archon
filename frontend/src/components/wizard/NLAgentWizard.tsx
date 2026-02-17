import { useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import {
  X,
  Sparkles,
  ChevronLeft,
  ChevronRight,
  RefreshCw,
  Check,
  Loader2,
  Plus,
  ExternalLink,
  AlertTriangle,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Textarea } from "@/components/ui/Textarea";
import { Label } from "@/components/ui/Label";
import {
  wizardDescribe,
  wizardPlan,
  wizardFull,
  type NLAnalysis,
  type NLBuildPlan,
  type PlannedEdge,
} from "@/api/wizard";
import { PlanCard, type PlanStep } from "./PlanCard";
import { ConfigForm, type WizardConfig } from "./ConfigForm";
import { GraphPreview } from "./GraphPreview";
import { TemplateSuggestions } from "./TemplateSuggestions";
import type { Template } from "@/api/templates";

// ─── Types ───────────────────────────────────────────────────────────

interface NLAgentWizardProps {
  onClose: () => void;
  onCreated?: (agentId: string) => void;
}

// ─── Constants ───────────────────────────────────────────────────────

const INDUSTRIES = [
  "Any",
  "Finance",
  "Healthcare",
  "E-commerce",
  "Education",
  "Legal",
  "Marketing",
  "DevOps",
  "Customer Support",
  "Research",
];

/** Convert backend PlannedNodes to frontend PlanStep format. */
function planNodeToStep(node: { node_id: string; label: string; node_type: string; description: string }): PlanStep {
  const typeMap: Record<string, PlanStep["type"]> = {
    llm: "llm",
    tool: "tool",
    condition: "condition",
    auth: "auth",
  };
  return {
    id: node.node_id,
    name: node.label,
    type: typeMap[node.node_type] ?? "default",
    description: node.description,
  };
}

// ─── Step 1: Describe ────────────────────────────────────────────────

function StepDescribe({
  description,
  setDescription,
  industry,
  setIndustry,
  dataSources,
  setDataSources,
  dsInput,
  setDsInput,
  onGenerate,
  loading,
  error,
}: {
  description: string;
  setDescription: (v: string) => void;
  industry: string;
  setIndustry: (v: string) => void;
  dataSources: string[];
  setDataSources: (v: string[]) => void;
  dsInput: string;
  setDsInput: (v: string) => void;
  onGenerate: () => void;
  loading: boolean;
  error: string | null;
}) {
  const addTag = () => {
    const tag = dsInput.trim();
    if (tag && !dataSources.includes(tag)) {
      setDataSources([...dataSources, tag]);
      setDsInput("");
    }
  };

  return (
    <div className="space-y-5">
      <div>
        <Label className="mb-2 block text-white">What should this agent do?</Label>
        <Textarea
          rows={6}
          placeholder="Describe the agent's purpose in plain language. E.g., 'Build a customer support agent that handles refund requests, checks order status from our API, and escalates complex issues to human agents.'"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          className="bg-[#0f1117] text-white border-[#2a2d37] placeholder:text-gray-500"
        />
      </div>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div>
          <Label className="mb-2 block text-gray-400">Industry (optional)</Label>
          <select
            value={industry}
            onChange={(e) => setIndustry(e.target.value)}
            className="h-9 w-full rounded-md border border-[#2a2d37] bg-[#0f1117] px-3 text-sm text-white focus:border-purple-500 focus:outline-none"
          >
            {INDUSTRIES.map((i) => (
              <option key={i} value={i}>{i}</option>
            ))}
          </select>
        </div>
        <div>
          <Label className="mb-2 block text-gray-400">Data Sources (optional)</Label>
          <div className="flex gap-2">
            <Input
              placeholder="Add data source…"
              value={dsInput}
              onChange={(e) => setDsInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addTag(); } }}
              className="bg-[#0f1117] text-white border-[#2a2d37]"
            />
            <Button type="button" size="sm" variant="outline" onClick={addTag}>
              <Plus size={14} />
            </Button>
          </div>
          {dataSources.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {dataSources.map((ds) => (
                <span
                  key={ds}
                  className="inline-flex items-center gap-1 rounded-full bg-purple-500/15 px-2.5 py-0.5 text-xs text-purple-300"
                >
                  {ds}
                  <button type="button" onClick={() => setDataSources(dataSources.filter((d) => d !== ds))} className="hover:text-white">
                    <X size={10} />
                  </button>
                </span>
              ))}
            </div>
          )}
        </div>
      </div>
      {error && (
        <div className="flex items-center gap-2 rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">
          <AlertTriangle size={16} />
          {error}
        </div>
      )}
      <div className="pt-2">
        <Button
          onClick={onGenerate}
          disabled={!description.trim() || loading}
          className="bg-purple-600 hover:bg-purple-700"
        >
          {loading ? <Loader2 size={14} className="mr-2 animate-spin" /> : <Sparkles size={14} className="mr-2" />}
          Generate Plan
        </Button>
      </div>
    </div>
  );
}

// ─── Main Wizard ─────────────────────────────────────────────────────

const WIZARD_STEPS = ["Describe", "Plan", "Configure", "Preview"] as const;

export function NLAgentWizard({ onClose, onCreated }: NLAgentWizardProps) {
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Step 1 state
  const [description, setDescription] = useState("");
  const [industry, setIndustry] = useState("Any");
  const [dataSources, setDataSources] = useState<string[]>([]);
  const [dsInput, setDsInput] = useState("");
  const [analysis, setAnalysis] = useState<NLAnalysis | null>(null);

  // Step 2 state
  const [planSteps, setPlanSteps] = useState<PlanStep[]>([]);
  const [planEdges, setPlanEdges] = useState<PlannedEdge[]>([]);
  const [buildPlan, setBuildPlan] = useState<NLBuildPlan | null>(null);

  // Step 3 state
  const [config, setConfig] = useState<WizardConfig>({
    model: "gpt-4o",
    temperature: 0.7,
    maxCostPerRun: 1.0,
    guardrails: {
      dlpScan: true,
      contentSafety: true,
      costLimit: false,
      rateLimiting: false,
      humanApproval: false,
    },
    allowedDomains: [],
  });

  // Extract keywords from description for template search
  const descriptionKeywords = description
    .split(/\s+/)
    .filter((w) => w.length > 3)
    .slice(0, 5);

  const generatePlan = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const describeRes = await wizardDescribe(description);
      const nlAnalysis = describeRes.data;
      setAnalysis(nlAnalysis);

      const planRes = await wizardPlan(nlAnalysis);
      const plan = planRes.data;
      setBuildPlan(plan);

      setPlanSteps(plan.nodes.map(planNodeToStep));
      setPlanEdges(plan.edges);
      setStep(1);
    } catch {
      setError("Failed to generate plan. Please try again.");
    } finally {
      setLoading(false);
    }
  }, [description]);

  const handleTemplateSelect = useCallback((template: Template) => {
    // Pre-fill plan steps from the template definition if available
    const def = template.definition as Record<string, unknown>;
    const nodes = (def?.nodes as Array<Record<string, string>>) ?? [];
    if (nodes.length > 0) {
      setPlanSteps(
        nodes.map((n, i) => ({
          id: n.node_id ?? `tpl-${i}`,
          name: n.label ?? n.name ?? `Step ${i + 1}`,
          type: (n.node_type as PlanStep["type"]) ?? "default",
          description: n.description ?? "",
        })),
      );
    }
  }, []);

  const moveStep = useCallback(
    (from: number, to: number) => {
      if (to < 0 || to >= planSteps.length) return;
      const copy = [...planSteps];
      const [item] = copy.splice(from, 1);
      copy.splice(to, 0, item);
      setPlanSteps(copy);
    },
    [planSteps],
  );

  const deleteStep = useCallback(
    (idx: number) => {
      setPlanSteps(planSteps.filter((_, i) => i !== idx));
    },
    [planSteps],
  );

  const updateStep = useCallback(
    (idx: number, patch: Partial<PlanStep>) => {
      setPlanSteps(planSteps.map((s, i) => (i === idx ? { ...s, ...patch } : s)));
    },
    [planSteps],
  );

  const addStep = useCallback(() => {
    setPlanSteps([
      ...planSteps,
      {
        id: `step-${Date.now()}`,
        name: "New Step",
        type: "tool",
        description: "",
      },
    ]);
  }, [planSteps]);

  const handleCreate = useCallback(async () => {
    setCreating(true);
    setError(null);
    try {
      const res = await wizardFull(description);
      const agentName = res.data?.agent?.agent_name;
      if (agentName) {
        onCreated?.(agentName);
      }
      onClose();
    } catch {
      setError("Failed to create agent. Please try again.");
      setCreating(false);
    }
  }, [description, onClose, onCreated]);

  const handleEditInBuilder = useCallback(async () => {
    setCreating(true);
    setError(null);
    try {
      const res = await wizardFull(description);
      const agentName = res.data?.agent?.agent_name;
      onClose();
      navigate(`/builder${agentName ? `?agent=${encodeURIComponent(agentName)}` : ""}`);
    } catch {
      setError("Failed to generate agent for builder.");
      setCreating(false);
    }
  }, [description, onClose, navigate]);

  const enabledGuardrails = Object.entries(config.guardrails)
    .filter(([, v]) => v)
    .map(([k]) => k);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="relative w-full max-w-3xl rounded-xl border border-[#2a2d37] bg-[#12141e] shadow-2xl max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-[#2a2d37] px-6 py-4">
          <div className="flex items-center gap-2">
            <Sparkles size={20} className="text-purple-400" />
            <h2 className="text-lg font-semibold text-white">Create with AI ✨</h2>
          </div>
          <button onClick={onClose} className="rounded p-1 text-gray-400 hover:bg-white/10 hover:text-white" aria-label="Close">
            <X size={18} />
          </button>
        </div>

        {/* Step Indicator */}
        <div className="flex items-center gap-1 border-b border-[#2a2d37] px-6 py-3">
          {WIZARD_STEPS.map((label, idx) => (
            <div key={label} className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => { if (idx <= step) setStep(idx); }}
                disabled={idx > step}
                className={`flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium transition-colors ${
                  idx === step
                    ? "bg-purple-500/20 text-purple-400"
                    : idx < step
                    ? "text-gray-300 hover:bg-white/5"
                    : "text-gray-600"
                }`}
              >
                <span className={`flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-bold ${
                  idx === step
                    ? "bg-purple-500 text-white"
                    : idx < step
                    ? "bg-green-500/30 text-green-400"
                    : "bg-[#2a2d37] text-gray-500"
                }`}>
                  {idx < step ? <Check size={10} /> : idx + 1}
                </span>
                {label}
              </button>
              {idx < WIZARD_STEPS.length - 1 && (
                <ChevronRight size={12} className="text-gray-600" />
              )}
            </div>
          ))}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-6 py-5">
          {step === 0 && (
            <StepDescribe
              description={description}
              setDescription={setDescription}
              industry={industry}
              setIndustry={setIndustry}
              dataSources={dataSources}
              setDataSources={setDataSources}
              dsInput={dsInput}
              setDsInput={setDsInput}
              onGenerate={generatePlan}
              loading={loading}
              error={error}
            />
          )}
          {step === 1 && (
            <div className="flex gap-4">
              <div className="flex-1 space-y-4">
                <div className="flex items-center justify-between">
                  <p className="text-sm text-gray-400">
                    {planSteps.length} steps in the plan. Click pencil to edit, drag to reorder.
                  </p>
                  <div className="flex items-center gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={addStep}
                    >
                      <Plus size={14} className="mr-1" /> Add Step
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={generatePlan}
                      disabled={loading}
                    >
                      {loading ? (
                        <Loader2 size={14} className="mr-1.5 animate-spin" />
                      ) : (
                        <RefreshCw size={14} className="mr-1.5" />
                      )}
                      Regenerate
                    </Button>
                  </div>
                </div>
                <div className="space-y-3">
                  {planSteps.map((s, idx) => (
                    <PlanCard
                      key={s.id}
                      step={s}
                      index={idx}
                      onMove={moveStep}
                      onDelete={deleteStep}
                      onUpdate={updateStep}
                      totalSteps={planSteps.length}
                    />
                  ))}
                </div>
                {error && (
                  <div className="flex items-center gap-2 rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">
                    <AlertTriangle size={16} />
                    {error}
                  </div>
                )}
              </div>
              {/* Template Suggestions sidebar */}
              <div className="hidden lg:block w-56 flex-shrink-0">
                <TemplateSuggestions
                  keywords={descriptionKeywords}
                  onSelect={handleTemplateSelect}
                />
              </div>
            </div>
          )}
          {step === 2 && (
            <ConfigForm config={config} onChange={setConfig} />
          )}
          {step === 3 && (
            <div className="space-y-5">
              {/* Graph Preview */}
              <div>
                <Label className="mb-2 block text-white">Agent Flow</Label>
                <GraphPreview steps={planSteps} edges={planEdges} />
              </div>

              {/* Config Summary */}
              <div className="rounded-lg border border-[#2a2d37] bg-[#0f1117] p-4">
                <h4 className="mb-3 text-sm font-medium text-white">Configuration Summary</h4>
                <div className="grid grid-cols-2 gap-3 text-sm">
                  <div>
                    <span className="text-gray-500">Model:</span>
                    <span className="ml-2 text-white">{config.model}</span>
                  </div>
                  <div>
                    <span className="text-gray-500">Temperature:</span>
                    <span className="ml-2 text-white">{config.temperature.toFixed(1)}</span>
                  </div>
                  <div>
                    <span className="text-gray-500">Steps:</span>
                    <span className="ml-2 text-white">{planSteps.length}</span>
                  </div>
                  <div>
                    <span className="text-gray-500">Guardrails:</span>
                    <span className="ml-2 text-white">{enabledGuardrails.length} active</span>
                  </div>
                </div>
                {description && (
                  <div className="mt-3 border-t border-[#2a2d37] pt-3">
                    <span className="text-xs text-gray-500">Description:</span>
                    <p className="mt-1 text-xs text-gray-300 line-clamp-3">{description}</p>
                  </div>
                )}
              </div>

              {error && (
                <div className="flex items-center gap-2 rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">
                  <AlertTriangle size={16} />
                  {error}
                </div>
              )}

              <div className="flex items-center gap-3">
                <Button
                  onClick={handleCreate}
                  disabled={creating}
                  className="bg-purple-600 hover:bg-purple-700"
                >
                  {creating ? (
                    <Loader2 size={14} className="mr-2 animate-spin" />
                  ) : (
                    <Sparkles size={14} className="mr-2" />
                  )}
                  Create Agent
                </Button>
                <button
                  type="button"
                  onClick={handleEditInBuilder}
                  disabled={creating}
                  className="inline-flex items-center gap-1.5 text-sm text-purple-400 hover:text-purple-300 disabled:opacity-50"
                >
                  <ExternalLink size={14} /> Edit in Builder
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Footer Navigation */}
        {step > 0 && (
          <div className="flex items-center justify-between border-t border-[#2a2d37] px-6 py-4">
            <Button variant="ghost" size="sm" onClick={() => { setStep(step - 1); setError(null); }}>
              <ChevronLeft size={14} className="mr-1" /> Back
            </Button>
            {step < 3 && (
              <Button size="sm" className="bg-purple-600 hover:bg-purple-700" onClick={() => setStep(step + 1)}>
                Next <ChevronRight size={14} className="ml-1" />
              </Button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
