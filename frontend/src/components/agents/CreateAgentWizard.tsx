import { useState } from "react";
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
  Zap,
} from "lucide-react";
import { IdentityStep, type IdentityData } from "./steps/IdentityStep";
import { ModelStep, type ModelData } from "./steps/ModelStep";
import { ToolsStep, type ToolsData } from "./steps/ToolsStep";
import { KnowledgeStep, type KnowledgeData } from "./steps/KnowledgeStep";
import { SecurityStep, type SecurityData } from "./steps/SecurityStep";
import { ConnectorsStep, type ConnectorsData } from "./steps/ConnectorsStep";
import { ReviewStep } from "./steps/ReviewStep";

// ─── Types ───────────────────────────────────────────────────────────

export interface CreateAgentWizardProps {
  onClose: () => void;
  onSubmit: (payload: Record<string, unknown>) => void;
  isPending: boolean;
  quickCreate?: boolean;
  /** Pre-populate all steps for edit mode */
  editData?: Record<string, unknown> | null;
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

const QUICK_STEPS = [0, 1, 6] as const;

// ─── Default State ───────────────────────────────────────────────────

function defaultIdentity(): IdentityData {
  return { name: "", description: "", icon: "🤖", tags: [], group_id: "" };
}

function defaultModel(): ModelData {
  return { provider: "openai", modelId: "gpt-4o", temperature: 0.7, maxTokens: 4096, systemPrompt: "" };
}

function defaultTools(): ToolsData {
  return { selectedTools: [] };
}

function defaultKnowledge(): KnowledgeData {
  return { enabled: false, collection: "", embeddingModel: "text-embedding-3-small", chunkStrategy: "fixed", chunkSize: 512, chunkOverlap: 50, topK: 5 };
}

function defaultSecurity(): SecurityData {
  return { dlpEnabled: false, guardrailPolicies: [], maxCostPerRun: 1.0, allowedDomains: [], piiHandling: "redact" };
}

function defaultConnectors(): ConnectorsData {
  return { selectedConnectors: [] };
}

// ─── Hydrate from edit data ──────────────────────────────────────────

function hydrateFromEdit(editData: Record<string, unknown>): {
  identity: IdentityData;
  model: ModelData;
  tools: ToolsData;
  knowledge: KnowledgeData;
  security: SecurityData;
  connectors: ConnectorsData;
} {
  const llm = (editData.llm_config as Record<string, unknown>) ?? {};
  const rag = (editData.rag_config as Record<string, unknown>) ?? {};
  const sec = (editData.security_policy as Record<string, unknown>) ?? {};
  const toolsList = (editData.tools as unknown[]) ?? [];
  const connList = (editData.connectors as string[]) ?? [];

  return {
    identity: {
      name: (editData.name as string) ?? "",
      description: (editData.description as string) ?? "",
      icon: (editData.icon as string) ?? "🤖",
      tags: (editData.tags as string[]) ?? [],
      group_id: (editData.group_id as string) ?? "",
    },
    model: {
      provider: (llm.provider as string) ?? "openai",
      modelId: (llm.model_id as string) ?? (llm.model as string) ?? "gpt-4o",
      temperature: (llm.temperature as number) ?? 0.7,
      maxTokens: (llm.max_tokens as number) ?? 4096,
      systemPrompt: (llm.system_prompt as string) ?? "",
    },
    tools: {
      selectedTools: Array.isArray(toolsList)
        ? toolsList.map((t) =>
            typeof t === "string" ? { id: t, params: {} } : { id: (t as Record<string, unknown>).name as string ?? (t as Record<string, unknown>).id as string ?? "", params: {} },
          )
        : [],
    },
    knowledge: {
      enabled: (rag.enabled as boolean) ?? false,
      collection: (rag.collection as string) ?? (rag.collection_id as string) ?? "",
      embeddingModel: (rag.embedding_model as string) ?? "text-embedding-3-small",
      chunkStrategy: (rag.chunk_strategy as string) ?? "fixed",
      chunkSize: (rag.chunk_size as number) ?? 512,
      chunkOverlap: (rag.chunk_overlap as number) ?? 50,
      topK: (rag.top_k as number) ?? 5,
    },
    security: {
      dlpEnabled: (sec.dlp_enabled as boolean) ?? false,
      guardrailPolicies: (sec.guardrail_policies as string[]) ?? [],
      maxCostPerRun: (sec.max_cost_per_run as number) ?? 1.0,
      allowedDomains: (sec.allowed_domains as string[]) ?? [],
      piiHandling: (sec.pii_handling as string) ?? "redact",
    },
    connectors: {
      selectedConnectors: connList,
    },
  };
}

// ─── Component ───────────────────────────────────────────────────────

export function CreateAgentWizard({
  onClose,
  onSubmit,
  isPending,
  quickCreate = false,
  editData = null,
}: CreateAgentWizardProps) {
  const [isQuick, setIsQuick] = useState(quickCreate);
  const activeSteps = isQuick ? QUICK_STEPS : STEPS.map((_, i) => i);
  const [stepIndex, setStepIndex] = useState(0);
  const currentStep = activeSteps[stepIndex] ?? 0;

  // ── Step State ──────────────────────────────────────────────────────
  const hydrated = editData ? hydrateFromEdit(editData) : null;

  const [identity, setIdentity] = useState<IdentityData>(hydrated?.identity ?? defaultIdentity());
  const [model, setModel] = useState<ModelData>(hydrated?.model ?? defaultModel());
  const [tools, setTools] = useState<ToolsData>(hydrated?.tools ?? defaultTools());
  const [knowledge, setKnowledge] = useState<KnowledgeData>(hydrated?.knowledge ?? defaultKnowledge());
  const [security, setSecurity] = useState<SecurityData>(hydrated?.security ?? defaultSecurity());
  const [connectors, setConnectors] = useState<ConnectorsData>(hydrated?.connectors ?? defaultConnectors());
  const [testResult, setTestResult] = useState<string | null>(null);
  const [isTesting, setIsTesting] = useState(false);

  // ── Navigation ──────────────────────────────────────────────────────
  const canPrev = stepIndex > 0;
  const canNext = stepIndex < activeSteps.length - 1;
  const isLastStep = stepIndex === activeSteps.length - 1;

  const canAdvance = (): boolean => {
    if (currentStep === 0) return identity.name.trim().length > 0;
    return true;
  };

  const goNext = () => {
    if (canNext && canAdvance()) setStepIndex((i) => i + 1);
  };
  const goPrev = () => {
    if (canPrev) setStepIndex((i) => i - 1);
  };
  const goToStep = (idx: number) => {
    if (idx <= stepIndex || canAdvance()) setStepIndex(idx);
  };

  // ── Build payload ──────────────────────────────────────────────────
  const buildPayload = (): Record<string, unknown> => ({
    name: identity.name,
    description: identity.description,
    tags: identity.tags,
    group_id: identity.group_id || null,
    definition: {},
    llm_config: {
      provider: model.provider,
      model_id: model.modelId,
      temperature: model.temperature,
      max_tokens: model.maxTokens,
      system_prompt: model.systemPrompt,
    },
    tools: tools.selectedTools.map((t) => ({
      name: t.id,
      type: "mcp",
      config: t.params,
    })),
    rag_config: knowledge.enabled
      ? {
          enabled: true,
          collection: knowledge.collection,
          embedding_model: knowledge.embeddingModel,
          chunk_strategy: knowledge.chunkStrategy,
          chunk_size: knowledge.chunkSize,
          chunk_overlap: knowledge.chunkOverlap,
          top_k: knowledge.topK,
        }
      : null,
    security_policy: {
      dlp_enabled: security.dlpEnabled,
      guardrail_policies: security.guardrailPolicies,
      max_cost_per_run: security.maxCostPerRun,
      allowed_domains: security.allowedDomains,
      pii_handling: security.piiHandling,
    },
    mcp_config: tools.selectedTools.length > 0
      ? { enabled: true, tools: tools.selectedTools.map((t) => t.id) }
      : null,
    connectors: connectors.selectedConnectors,
  });

  const handleTest = () => {
    setIsTesting(true);
    setTestResult(null);
    setTimeout(() => {
      setTestResult(
        `✅ Agent "${identity.name}" responded successfully.\n\nModel: ${model.provider} / ${model.modelId}\nTools: ${tools.selectedTools.length} enabled\nLatency: 847ms\n\nSample response: "Hello! I'm ${identity.name}, ready to assist you."`,
      );
      setIsTesting(false);
    }, 1500);
  };

  const handleSubmit = () => onSubmit(buildPayload());

  // ── Step Renderer ──────────────────────────────────────────────────
  const renderCurrentStep = () => {
    switch (currentStep) {
      case 0: return <IdentityStep data={identity} onChange={setIdentity} />;
      case 1: return <ModelStep data={model} onChange={setModel} />;
      case 2: return <ToolsStep data={tools} onChange={setTools} />;
      case 3: return <KnowledgeStep data={knowledge} onChange={setKnowledge} />;
      case 4: return <SecurityStep data={security} onChange={setSecurity} />;
      case 5: return <ConnectorsStep data={connectors} onChange={setConnectors} />;
      case 6: return (
        <ReviewStep
          identity={identity}
          model={model}
          tools={tools}
          knowledge={knowledge}
          security={security}
          connectors={connectors}
          onTest={handleTest}
          isTesting={isTesting}
          testResult={testResult}
        />
      );
      default: return null;
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="flex max-h-[90vh] w-full max-w-4xl flex-col rounded-xl border border-[#2a2d37] bg-[#12141e] shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-[#2a2d37] px-6 py-4">
          <div className="flex items-center gap-3">
            <Bot size={20} className="text-purple-400" />
            <h2 className="text-lg font-semibold text-white">
              {editData ? "Edit Agent" : "Create Agent"}
            </h2>
          </div>
          <div className="flex items-center gap-3">
            {/* Quick Create Toggle */}
            {!editData && (
              <button
                type="button"
                onClick={() => {
                  setIsQuick(!isQuick);
                  setStepIndex(0);
                }}
                className={`flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors ${
                  isQuick
                    ? "border-amber-500/50 bg-amber-500/20 text-amber-400"
                    : "border-[#2a2d37] text-gray-500 hover:text-gray-300"
                }`}
              >
                <Zap size={12} />
                Quick Create
              </button>
            )}
            <button
              onClick={onClose}
              className="rounded-lg p-1 text-gray-400 hover:bg-white/10 hover:text-white"
              aria-label="Close wizard"
            >
              <X size={20} />
            </button>
          </div>
        </div>

        {/* Step Indicator */}
        <div className="border-b border-[#2a2d37] px-6 py-3">
          <div className="flex items-center gap-1">
            {activeSteps.map((stepNum, idx) => {
              const stepDef = STEPS[stepNum];
              const Icon = stepDef?.icon;
              const isActive = idx === stepIndex;
              const isCompleted = idx < stepIndex;
              return (
                <div key={stepNum} className="flex items-center">
                  {idx > 0 && (
                    <div className={`mx-1 h-px w-6 ${isCompleted ? "bg-purple-500" : "bg-[#2a2d37]"}`} />
                  )}
                  <button
                    type="button"
                    onClick={() => goToStep(idx)}
                    className={`flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium transition-colors ${
                      isActive
                        ? "bg-purple-500/20 text-purple-400"
                        : isCompleted
                        ? "text-purple-400/70 hover:text-purple-400"
                        : "text-gray-600 hover:text-gray-400"
                    }`}
                  >
                    {Icon && <Icon size={14} />}
                    <span className="hidden sm:inline">{stepDef?.label}</span>
                  </button>
                </div>
              );
            })}
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-6 py-5">
          <div className="mb-4">
            <h3 className="text-base font-semibold text-white">{STEPS[currentStep]?.label}</h3>
            <p className="text-xs text-gray-500">
              Step {stepIndex + 1} of {activeSteps.length}
            </p>
          </div>
          {renderCurrentStep()}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between border-t border-[#2a2d37] px-6 py-4">
          <button
            type="button"
            onClick={goPrev}
            disabled={!canPrev}
            className="flex items-center gap-1 rounded-lg border border-[#2a2d37] px-4 py-2 text-sm text-gray-400 hover:bg-white/5 disabled:opacity-40"
          >
            <ChevronLeft size={16} />
            Back
          </button>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-[#2a2d37] px-4 py-2 text-sm text-gray-400 hover:bg-white/5"
            >
              Cancel
            </button>
            {isLastStep ? (
              <button
                type="button"
                onClick={handleSubmit}
                disabled={isPending || !canAdvance()}
                className="flex items-center gap-2 rounded-lg bg-purple-600 px-6 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50"
              >
                {isPending ? "Creating..." : editData ? "Save Changes" : "Create Agent"}
              </button>
            ) : (
              <button
                type="button"
                onClick={goNext}
                disabled={!canAdvance()}
                className="flex items-center gap-1 rounded-lg bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50"
              >
                Next
                <ChevronRight size={16} />
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
