import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  Wand2,
  Bot,
  Sparkles,
  ArrowLeft,
  Loader2,
  CheckCircle2,
  AlertCircle,
  BookOpen,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import { AgentWizard } from "@/components/wizard/AgentWizard";
import { NLAgentWizard } from "@/components/wizard/NLAgentWizard";
import { createAgent } from "@/api/agents";
import { listTemplates } from "@/api/templates";
import type { Template } from "@/api/templates";
import type { AppNode, AppEdge } from "@/types";

// ─── Creation mode ────────────────────────────────────────────────────

type CreationMode = "select" | "guided" | "nl" | "template";

// ─── Template card ────────────────────────────────────────────────────

function TemplateCard({
  template,
  onUse,
}: {
  template: Template;
  onUse: (t: Template) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onUse(template)}
      className="flex flex-col gap-2 rounded-xl border border-[#2a2d37] bg-[#1a1d27] p-4 text-left transition-colors hover:border-purple-500/40 hover:bg-purple-500/5"
    >
      <div className="flex items-start gap-2">
        <BookOpen size={16} className="mt-0.5 shrink-0 text-purple-400" />
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-white">{template.name}</p>
          {template.category && (
            <p className="text-xs text-purple-400">{template.category}</p>
          )}
        </div>
      </div>
      <p className="line-clamp-2 text-xs text-gray-500">{template.description}</p>
      {template.tags && template.tags.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {template.tags.slice(0, 3).map((tag) => (
            <span key={tag} className="rounded bg-white/10 px-1.5 py-0.5 text-[10px] text-gray-400">
              {tag}
            </span>
          ))}
        </div>
      )}
    </button>
  );
}

// ─── Mode selection card ──────────────────────────────────────────────

function ModeCard({
  icon: Icon,
  title,
  description,
  badge,
  onClick,
}: {
  icon: typeof Bot;
  title: string;
  description: string;
  badge?: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex flex-col gap-3 rounded-xl border border-[#2a2d37] bg-[#1a1d27] p-5 text-left transition-all hover:border-purple-500/50 hover:bg-purple-500/5 hover:shadow-lg hover:shadow-purple-500/5"
    >
      <div className="flex items-start justify-between">
        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-purple-500/20">
          <Icon size={20} className="text-purple-400" />
        </div>
        {badge && (
          <span className="rounded-full bg-purple-500/20 px-2 py-0.5 text-xs font-medium text-purple-300">
            {badge}
          </span>
        )}
      </div>
      <div>
        <h3 className="mb-1 text-sm font-semibold text-white">{title}</h3>
        <p className="text-xs leading-relaxed text-gray-500">{description}</p>
      </div>
    </button>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────

export function AgentWizardPage() {
  const navigate = useNavigate();
  const [mode, setMode] = useState<CreationMode>("select");
  const [successId, setSuccessId] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Fetch templates for the "From Template" flow
  const { data: templatesData, isLoading: templatesLoading } = useQuery({
    queryKey: ["templates", { limit: 12 }],
    queryFn: () => listTemplates({ limit: 12 }),
    enabled: mode === "template",
  });

  const templates: Template[] = templatesData?.data ?? [];

  // Create agent mutation (used by guided wizard)
  const createMutation = useMutation({
    mutationFn: (payload: {
      name: string;
      description?: string;
      nodes?: AppNode[];
      edges?: AppEdge[];
      tags?: string[];
      definition?: Record<string, unknown>;
      llm_config?: Record<string, unknown>;
      tools?: string[];
      rag_config?: Record<string, unknown> | null;
      security_policy?: Record<string, unknown>;
      connectors?: string[];
    }) =>
      createAgent({
        name: payload.name,
        description: payload.description,
        nodes: payload.nodes ?? [],
        edges: payload.edges ?? [],
      }),
    onSuccess: (res) => {
      const agent = res.data;
      setSuccessId(agent?.id ?? null);
      setErrorMsg(null);
    },
    onError: () => {
      setErrorMsg("Failed to create agent. Please try again.");
    },
  });

  // Handle guided wizard submit
  function handleGuidedSubmit(payload: Record<string, unknown>) {
    setErrorMsg(null);
    createMutation.mutate(payload as Parameters<typeof createMutation.mutate>[0]);
  }

  // Handle template selection — build agent from template definition
  function handleTemplateUse(template: Template) {
    setErrorMsg(null);
    createMutation.mutate({
      name: `${template.name} (from template)`,
      description: template.description ?? undefined,
      definition: template.definition,
      nodes: [],
      edges: [],
    });
  }

  // ── Success screen ─────────────────────────────────────────────────

  if (successId) {
    return (
      <div className="flex min-h-[60vh] flex-col items-center justify-center p-8">
        <div className="w-full max-w-sm text-center">
          <div className="mb-4 flex justify-center">
            <div className="flex h-16 w-16 items-center justify-center rounded-full bg-green-500/20">
              <CheckCircle2 size={32} className="text-green-400" />
            </div>
          </div>
          <h2 className="mb-2 text-xl font-bold text-white">Agent Created!</h2>
          <p className="mb-6 text-sm text-gray-400">
            Your agent has been created successfully and is ready to use.
          </p>
          <div className="flex flex-col gap-2">
            <Button
              className="w-full bg-purple-600 hover:bg-purple-700"
              onClick={() => navigate(`/agents`)}
            >
              <Bot size={16} className="mr-2" />
              View All Agents
            </Button>
            <Button
              variant="outline"
              className="w-full"
              onClick={() => {
                setSuccessId(null);
                setMode("select");
              }}
            >
              Create Another
            </Button>
          </div>
        </div>
      </div>
    );
  }

  // ── NL Wizard mode ─────────────────────────────────────────────────

  if (mode === "nl") {
    return (
      <div className="relative h-full">
        <button
          type="button"
          onClick={() => setMode("select")}
          className="absolute left-4 top-4 z-10 flex items-center gap-1 rounded-lg border border-[#2a2d37] px-3 py-1.5 text-xs text-gray-400 hover:bg-white/5"
        >
          <ArrowLeft size={14} /> Back
        </button>
        <NLAgentWizard
          onClose={() => setMode("select")}
          onCreated={(id) => setSuccessId(id)}
        />
      </div>
    );
  }

  // ── Guided Wizard mode ─────────────────────────────────────────────

  if (mode === "guided") {
    return (
      <div className="relative h-full">
        {errorMsg && (
          <div className="fixed bottom-4 left-1/2 z-50 -translate-x-1/2 flex items-center gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-2 text-sm text-red-400 shadow-lg">
            <AlertCircle size={14} />
            {errorMsg}
          </div>
        )}
        <AgentWizard
          onClose={() => setMode("select")}
          onSubmit={handleGuidedSubmit}
          isPending={createMutation.isPending}
        />
      </div>
    );
  }

  // ── Template mode ──────────────────────────────────────────────────

  if (mode === "template") {
    return (
      <div className="p-6">
        <button
          type="button"
          onClick={() => setMode("select")}
          className="mb-6 flex items-center gap-1 text-sm text-gray-500 hover:text-white"
        >
          <ArrowLeft size={14} /> Back
        </button>

        <div className="mb-6">
          <h1 className="text-2xl font-bold text-white">Choose a Template</h1>
          <p className="mt-1 text-sm text-gray-400">
            Start from a pre-built agent template and customize it to fit your needs.
          </p>
        </div>

        {errorMsg && (
          <div className="mb-4 flex items-center gap-2 rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">
            <AlertCircle size={14} />
            {errorMsg}
          </div>
        )}

        {templatesLoading ? (
          <div className="flex h-40 items-center justify-center">
            <Loader2 size={24} className="animate-spin text-gray-500" />
          </div>
        ) : templates.length === 0 ? (
          <div className="flex h-40 flex-col items-center justify-center gap-2 rounded-xl border border-[#2a2d37] bg-[#1a1d27]">
            <BookOpen size={24} className="text-gray-600" />
            <p className="text-sm text-gray-500">No templates available yet.</p>
            <Button
              variant="outline"
              size="sm"
              onClick={() => navigate("/templates")}
            >
              Browse Templates
            </Button>
          </div>
        ) : (
          <>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {templates.map((t) => (
                <TemplateCard
                  key={t.id}
                  template={t}
                  onUse={handleTemplateUse}
                />
              ))}
            </div>
            {createMutation.isPending && (
              <div className="mt-6 flex items-center justify-center gap-2 text-sm text-gray-400">
                <Loader2 size={16} className="animate-spin" />
                Creating agent from template…
              </div>
            )}
          </>
        )}
      </div>
    );
  }

  // ── Mode selection (default) ───────────────────────────────────────

  return (
    <div className="p-6">
      <button
        type="button"
        onClick={() => navigate("/agents")}
        className="mb-6 flex items-center gap-1 text-sm text-gray-500 hover:text-white"
      >
        <ArrowLeft size={14} /> Back to Agents
      </button>

      <div className="mb-8">
        <div className="mb-2 flex items-center gap-3">
          <Wand2 size={24} className="text-purple-400" />
          <h1 className="text-2xl font-bold text-white">Create an Agent</h1>
        </div>
        <p className="text-sm text-gray-400">
          Choose how you want to build your agent.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <ModeCard
          icon={Sparkles}
          title="AI-Guided (NL Wizard)"
          description="Describe your agent in plain language. Our AI will plan and build it for you — including nodes, connections, and configurations."
          badge="Recommended"
          onClick={() => setMode("nl")}
        />
        <ModeCard
          icon={Bot}
          title="Step-by-Step Wizard"
          description="Walk through identity, model selection, tools, knowledge base, security policies, and connectors in a structured 7-step form."
          onClick={() => setMode("guided")}
        />
        <ModeCard
          icon={BookOpen}
          title="From Template"
          description="Browse the template library and start from a pre-built agent configuration. Customize it to your specific requirements."
          onClick={() => setMode("template")}
        />
      </div>
    </div>
  );
}
