import { useState, useEffect, useMemo } from "react";
import {
  LayoutTemplate,
  Plus,
  X,
  Tag,
  Zap,
  Search,
  ChevronRight,
  ChevronLeft,
  Check,
  Loader2,
  Headphones,
  BarChart3,
  FileText,
  Code2,
  Microscope,
  Server,
  Bot,
  MessageSquare,
  Workflow,
  ShieldCheck,
  Database,
  Globe,
  Mail,
  Megaphone,
  Users,
  Lightbulb,
  Cog,
  BrainCircuit,
  Sparkles,
  BookOpen,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Textarea } from "@/components/ui/Textarea";
import { Label } from "@/components/ui/Label";
import { apiGet, apiPost } from "@/api/client";

// ─── Types ───────────────────────────────────────────────────────────

interface Template {
  id: string;
  name: string;
  description: string;
  category: string;
  definition: Record<string, unknown>;
  tags: string[];
  created_at: string;
}

type TemplateCategory =
  | "Customer Support"
  | "Data Analysis"
  | "Content Generation"
  | "Code Assistant"
  | "Research"
  | "DevOps"
  | "Custom";

// ─── Seed Templates ──────────────────────────────────────────────────

interface SeedTemplate {
  name: string;
  description: string;
  category: TemplateCategory;
  icon: typeof Bot;
  tags: string[];
}

const SEED_TEMPLATES: SeedTemplate[] = [
  { name: "Customer Support Bot", description: "AI-powered support agent that handles common inquiries, tracks tickets, and escalates complex issues to human agents.", category: "Customer Support", icon: Headphones, tags: ["support", "chat", "tickets"] },
  { name: "Refund Processor", description: "Automates refund request processing with policy checks, order validation, and approval workflows.", category: "Customer Support", icon: MessageSquare, tags: ["refunds", "automation"] },
  { name: "FAQ Auto-Responder", description: "Answers frequently asked questions using a curated knowledge base with context-aware responses.", category: "Customer Support", icon: BookOpen, tags: ["faq", "knowledge-base"] },
  { name: "Sales Data Analyst", description: "Analyzes sales data, generates reports, identifies trends, and provides actionable business insights.", category: "Data Analysis", icon: BarChart3, tags: ["analytics", "reports", "sales"] },
  { name: "Log Analyzer", description: "Parses and analyzes application logs to detect anomalies, errors, and performance bottlenecks.", category: "Data Analysis", icon: Database, tags: ["logs", "monitoring"] },
  { name: "Survey Insights", description: "Processes survey responses, performs sentiment analysis, and generates executive summaries.", category: "Data Analysis", icon: Users, tags: ["surveys", "sentiment"] },
  { name: "Blog Writer", description: "Generates SEO-optimized blog posts with research, outlines, and multi-draft revision workflows.", category: "Content Generation", icon: FileText, tags: ["blog", "seo", "writing"] },
  { name: "Social Media Manager", description: "Creates and schedules social media content across platforms with tone and brand consistency.", category: "Content Generation", icon: Megaphone, tags: ["social", "marketing"] },
  { name: "Email Campaign Drafter", description: "Generates personalized email campaigns with A/B testing variants and performance tracking.", category: "Content Generation", icon: Mail, tags: ["email", "campaigns"] },
  { name: "Newsletter Curator", description: "Curates and summarizes industry news into formatted newsletter content.", category: "Content Generation", icon: Globe, tags: ["newsletter", "curation"] },
  { name: "Code Reviewer", description: "Reviews pull requests, identifies bugs, security vulnerabilities, and suggests improvements.", category: "Code Assistant", icon: Code2, tags: ["code-review", "security"] },
  { name: "Test Generator", description: "Automatically generates unit and integration tests for codebases with high coverage targets.", category: "Code Assistant", icon: ShieldCheck, tags: ["testing", "automation"] },
  { name: "Documentation Writer", description: "Generates API documentation, README files, and inline code comments from source code.", category: "Code Assistant", icon: BookOpen, tags: ["docs", "api"] },
  { name: "Refactor Assistant", description: "Suggests and applies code refactoring patterns to improve code quality and maintainability.", category: "Code Assistant", icon: Workflow, tags: ["refactoring", "quality"] },
  { name: "Research Assistant", description: "Searches academic papers, summarizes findings, and generates literature review drafts.", category: "Research", icon: Microscope, tags: ["academic", "papers"] },
  { name: "Competitive Intelligence", description: "Monitors competitors, analyzes market positioning, and generates comparison reports.", category: "Research", icon: Lightbulb, tags: ["market", "intelligence"] },
  { name: "Patent Analyzer", description: "Analyzes patent filings, identifies prior art, and summarizes technical claims.", category: "Research", icon: BrainCircuit, tags: ["patents", "legal"] },
  { name: "CI/CD Monitor", description: "Monitors CI/CD pipelines, detects failures, and suggests fixes based on error patterns.", category: "DevOps", icon: Server, tags: ["ci-cd", "monitoring"] },
  { name: "Incident Responder", description: "Automates incident response with runbook execution, status page updates, and escalation.", category: "DevOps", icon: Cog, tags: ["incidents", "runbooks"] },
  { name: "Infrastructure Advisor", description: "Analyzes infrastructure costs, recommends optimizations, and generates provisioning plans.", category: "DevOps", icon: Server, tags: ["infra", "cost"] },
  { name: "Custom Workflow", description: "Blank template for building custom agent workflows from scratch.", category: "Custom", icon: Sparkles, tags: ["custom", "blank"] },
];

const ALL_CATEGORIES: TemplateCategory[] = [
  "Customer Support",
  "Data Analysis",
  "Content Generation",
  "Code Assistant",
  "Research",
  "DevOps",
  "Custom",
];

const CATEGORY_COLORS: Record<string, string> = {
  "Customer Support": "bg-blue-500/20 text-blue-400",
  "Data Analysis": "bg-emerald-500/20 text-emerald-400",
  "Content Generation": "bg-orange-500/20 text-orange-400",
  "Code Assistant": "bg-cyan-500/20 text-cyan-400",
  "Research": "bg-violet-500/20 text-violet-400",
  "DevOps": "bg-red-500/20 text-red-400",
  "Custom": "bg-gray-500/20 text-gray-400",
};

// ─── Create Form Steps ──────────────────────────────────────────────

function CreateTemplateModal({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: () => void;
}) {
  const [step, setStep] = useState(0);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState<TemplateCategory>("Custom");
  const [tags, setTags] = useState("");
  const [model, setModel] = useState("gpt-4o");
  const [temperature, setTemperature] = useState(0.7);
  const [tools, setTools] = useState<string[]>([]);

  const MODELS = ["gpt-4o", "gpt-4o-mini", "claude-3-5-sonnet", "claude-3-opus", "gemini-pro", "mistral-large"];
  const TOOL_OPTIONS = ["web_search", "code_interpreter", "file_reader", "api_caller", "database_query", "email_sender"];

  async function handlePublish() {
    setCreating(true);
    try {
      await apiPost("/templates/", {
        name,
        description,
        category,
        definition: { model, temperature, tools },
        tags: tags.split(",").map((t) => t.trim()).filter(Boolean),
      });
      onCreated();
      onClose();
    } catch {
      // Keep modal open on failure
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="relative w-full max-w-lg rounded-xl border border-surface-border bg-surface-overlay shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-surface-border px-6 py-4">
          <h2 className="text-lg font-semibold text-white">Create Template</h2>
          <button onClick={onClose} className="rounded p-1 text-gray-400 hover:bg-white/10 hover:text-white" aria-label="Close">
            <X size={18} />
          </button>
        </div>

        {/* Step indicators */}
        <div className="flex items-center gap-2 border-b border-surface-border px-6 py-3">
          {["Details", "Configure", "Preview"].map((label, idx) => (
            <button
              key={label}
              type="button"
              onClick={() => { if (idx <= step) setStep(idx); }}
              disabled={idx > step}
              className={`flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium ${
                idx === step ? "bg-purple-500/20 text-purple-400" : idx < step ? "text-gray-300" : "text-gray-600"
              }`}
            >
              <span className={`flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-bold ${
                idx === step ? "bg-purple-500 text-white" : idx < step ? "bg-green-500/30 text-green-400" : "bg-surface-border text-gray-500"
              }`}>
                {idx < step ? <Check size={10} /> : idx + 1}
              </span>
              {label}
            </button>
          ))}
        </div>

        {/* Content */}
        <div className="px-6 py-5 space-y-4">
          {step === 0 && (
            <>
              <div>
                <Label className="mb-1 block text-white">Name *</Label>
                <Input placeholder="My Agent Template" value={name} onChange={(e) => setName(e.target.value)} className="bg-surface-base text-white border-surface-border" />
              </div>
              <div>
                <Label className="mb-1 block text-white">Description</Label>
                <Textarea rows={3} placeholder="What does this template do?" value={description} onChange={(e) => setDescription(e.target.value)} className="bg-surface-base text-white border-surface-border" />
              </div>
              <div>
                <Label className="mb-1 block text-white">Category *</Label>
                <select value={category} onChange={(e) => setCategory(e.target.value as TemplateCategory)} className="h-9 w-full rounded-md border border-surface-border bg-surface-base px-3 text-sm text-white">
                  {ALL_CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
              </div>
              <div>
                <Label className="mb-1 block text-white">Tags</Label>
                <Input placeholder="chat, support, automation" value={tags} onChange={(e) => setTags(e.target.value)} className="bg-surface-base text-white border-surface-border" />
              </div>
            </>
          )}
          {step === 1 && (
            <>
              <div>
                <Label className="mb-1 block text-white">Model</Label>
                <select value={model} onChange={(e) => setModel(e.target.value)} className="h-9 w-full rounded-md border border-surface-border bg-surface-base px-3 text-sm text-white">
                  {MODELS.map((m) => <option key={m} value={m}>{m}</option>)}
                </select>
              </div>
              <div>
                <Label className="mb-1 block text-white">Temperature: {temperature.toFixed(1)}</Label>
                <input type="range" min={0} max={2} step={0.1} value={temperature} onChange={(e) => setTemperature(parseFloat(e.target.value))} className="w-full accent-purple-500" />
              </div>
              <div>
                <Label className="mb-2 block text-white">Tools</Label>
                <div className="flex flex-wrap gap-2">
                  {TOOL_OPTIONS.map((t) => (
                    <button
                      key={t}
                      type="button"
                      onClick={() => setTools(tools.includes(t) ? tools.filter((x) => x !== t) : [...tools, t])}
                      className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${
                        tools.includes(t) ? "bg-purple-500/20 text-purple-400" : "border border-surface-border text-gray-400 hover:bg-white/5"
                      }`}
                    >
                      {t.replace(/_/g, " ")}
                    </button>
                  ))}
                </div>
              </div>
            </>
          )}
          {step === 2 && (
            <div className="rounded-lg border border-surface-border bg-surface-base p-4 space-y-2 text-sm">
              <div><span className="text-gray-500">Name:</span> <span className="text-white">{name || "—"}</span></div>
              <div><span className="text-gray-500">Category:</span> <span className={`ml-1 rounded-full px-2 py-0.5 text-xs ${CATEGORY_COLORS[category]}`}>{category}</span></div>
              <div><span className="text-gray-500">Model:</span> <span className="text-white">{model}</span></div>
              <div><span className="text-gray-500">Temperature:</span> <span className="text-white">{temperature.toFixed(1)}</span></div>
              {tools.length > 0 && <div><span className="text-gray-500">Tools:</span> <span className="text-white">{tools.join(", ")}</span></div>}
              {description && <div><span className="text-gray-500">Description:</span> <span className="text-gray-300">{description}</span></div>}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between border-t border-surface-border px-6 py-4">
          {step > 0 ? (
            <Button variant="ghost" size="sm" onClick={() => setStep(step - 1)}>
              <ChevronLeft size={14} className="mr-1" /> Back
            </Button>
          ) : <div />}
          {step < 2 ? (
            <Button size="sm" className="bg-purple-600 hover:bg-purple-700" onClick={() => setStep(step + 1)} disabled={step === 0 && !name.trim()}>
              Next <ChevronRight size={14} className="ml-1" />
            </Button>
          ) : (
            <Button size="sm" className="bg-purple-600 hover:bg-purple-700" onClick={handlePublish} disabled={creating || !name.trim()}>
              {creating ? <Loader2 size={14} className="mr-1.5 animate-spin" /> : <Plus size={14} className="mr-1.5" />}
              Publish Template
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

// ─── Detail Modal ────────────────────────────────────────────────────

function TemplateDetailModal({
  template,
  onClose,
  onUse,
  using,
}: {
  template: SeedTemplate | Template;
  onClose: () => void;
  onUse: () => void;
  using: boolean;
}) {
  const isSeed = !("id" in template);
  const Icon = isSeed ? (template as SeedTemplate).icon : LayoutTemplate;
  const cat = template.category;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="relative w-full max-w-md rounded-xl border border-surface-border bg-surface-overlay shadow-2xl">
        <div className="flex items-center justify-between border-b border-surface-border px-6 py-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-purple-500/10">
              <Icon size={20} className="text-purple-400" />
            </div>
            <div>
              <h3 className="text-lg font-semibold text-white">{template.name}</h3>
              <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${CATEGORY_COLORS[cat] ?? "bg-gray-500/20 text-gray-400"}`}>{cat}</span>
            </div>
          </div>
          <button onClick={onClose} className="rounded p-1 text-gray-400 hover:bg-white/10 hover:text-white" aria-label="Close">
            <X size={18} />
          </button>
        </div>
        <div className="px-6 py-5">
          <p className="mb-4 text-sm text-gray-300">{template.description}</p>
          {template.tags.length > 0 && (
            <div className="mb-4 flex flex-wrap gap-1.5">
              {template.tags.map((tag) => (
                <span key={tag} className="inline-flex items-center gap-1 rounded-full bg-white/10 px-2 py-0.5 text-xs text-gray-400">
                  <Tag size={10} /> {tag}
                </span>
              ))}
            </div>
          )}
          <Button className="w-full bg-purple-600 hover:bg-purple-700" onClick={onUse} disabled={using}>
            {using ? <Loader2 size={14} className="mr-1.5 animate-spin" /> : <Zap size={14} className="mr-1.5" />}
            Use Template
          </Button>
        </div>
      </div>
    </div>
  );
}

// ─── Main Page ───────────────────────────────────────────────────────

export function TemplatesPage() {
  const [templates, setTemplates] = useState<Template[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [instantiating, setInstantiating] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [catFilter, setCatFilter] = useState("all");
  const [detailItem, setDetailItem] = useState<SeedTemplate | Template | null>(null);

  async function fetchTemplates() {
    setLoading(true);
    setError(null);
    try {
      const res = await apiGet<Template[]>("/templates/");
      setTemplates(Array.isArray(res.data) ? res.data : []);
    } catch {
      setError("Failed to load templates.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void fetchTemplates(); }, []);

  async function handleInstantiate(id: string) {
    setInstantiating(id);
    try {
      await apiPost(`/templates/${id}/instantiate`, {});
      setDetailItem(null);
    } catch {
      setError("Failed to instantiate template.");
    } finally {
      setInstantiating(null);
    }
  }

  async function handleUseSeed(seed: SeedTemplate) {
    setInstantiating(seed.name);
    try {
      await apiPost("/templates/", {
        name: seed.name,
        description: seed.description,
        category: seed.category,
        definition: {},
        tags: seed.tags,
      });
      await fetchTemplates();
      setDetailItem(null);
    } catch {
      setError("Failed to create from seed.");
    } finally {
      setInstantiating(null);
    }
  }

  // Combined list: user templates + seeds
  const combined = useMemo(() => {
    const items: Array<{ type: "user"; data: Template } | { type: "seed"; data: SeedTemplate }> = [];
    templates.forEach((t) => items.push({ type: "user", data: t }));
    SEED_TEMPLATES.forEach((s) => {
      if (!templates.some((t) => t.name === s.name)) {
        items.push({ type: "seed", data: s });
      }
    });
    return items;
  }, [templates]);

  const filtered = combined.filter((item) => {
    const name = item.data.name.toLowerCase();
    const desc = item.data.description.toLowerCase();
    const q = search.toLowerCase();
    if (q && !name.includes(q) && !desc.includes(q)) return false;
    if (catFilter !== "all" && item.data.category !== catFilter) return false;
    return true;
  });

  if (loading) {
    return <div className="flex h-64 items-center justify-center"><p className="text-gray-400">Loading...</p></div>;
  }

  return (
    <div className="p-6">
      {error && (
        <div className="mb-4 rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">
          {error}
          <button onClick={() => setError(null)} className="ml-2 text-red-300 hover:text-white"><X size={12} /></button>
        </div>
      )}

      {/* Header */}
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <LayoutTemplate size={24} className="text-purple-400" />
          <h1 className="text-2xl font-bold text-white">Templates</h1>
          <span className="rounded-full bg-surface-raised px-2 py-0.5 text-xs text-gray-400">{filtered.length}</span>
        </div>
        <Button size="sm" className="bg-purple-600 hover:bg-purple-700" onClick={() => setShowCreate(true)}>
          <Plus size={14} className="mr-1.5" /> Create Template
        </Button>
      </div>
      <p className="mb-6 text-gray-400">Browse pre-built and custom agent templates. Click to view details or use a template.</p>

      {/* Search & Category Filter */}
      <div className="mb-5 flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[200px] max-w-xs">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
          <Input placeholder="Search templates…" value={search} onChange={(e) => setSearch(e.target.value)} className="pl-9 bg-surface-base text-white border-surface-border" />
        </div>
        <div className="flex flex-wrap gap-1">
          <button onClick={() => setCatFilter("all")} className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${catFilter === "all" ? "bg-purple-500/20 text-purple-400" : "text-gray-400 hover:bg-white/5"}`}>
            All
          </button>
          {ALL_CATEGORIES.map((c) => (
            <button key={c} onClick={() => setCatFilter(c)} className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${catFilter === c ? "bg-purple-500/20 text-purple-400" : "text-gray-400 hover:bg-white/5"}`}>
              {c}
            </button>
          ))}
        </div>
      </div>

      {/* Gallery Grid */}
      {filtered.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-lg border border-surface-border bg-surface-raised py-16">
          <LayoutTemplate size={40} className="mb-3 text-gray-600" />
          <p className="text-sm text-gray-500">No templates match your search.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {filtered.map((item) => {
            const isSeed = item.type === "seed";
            const data = item.data;
            const Icon = isSeed ? (data as SeedTemplate).icon : LayoutTemplate;
            const key = isSeed ? (data as SeedTemplate).name : (data as Template).id;
            const catColor = CATEGORY_COLORS[data.category] ?? "bg-gray-500/20 text-gray-400";

            return (
              <div
                key={key}
                onClick={() => setDetailItem(data)}
                className="group cursor-pointer rounded-lg border border-surface-border bg-surface-raised p-4 transition-colors hover:border-purple-500/30"
              >
                <div className="mb-3 flex items-start justify-between">
                  <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-purple-500/10 group-hover:bg-purple-500/20 transition-colors">
                    <Icon size={20} className="text-purple-400" />
                  </div>
                  <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${catColor}`}>{data.category}</span>
                </div>
                <h3 className="mb-1 text-sm font-semibold text-white">{data.name}</h3>
                <p className="mb-3 line-clamp-2 text-xs text-gray-400">{data.description}</p>
                {data.tags.length > 0 && (
                  <div className="mb-3 flex flex-wrap gap-1">
                    {data.tags.slice(0, 3).map((tag) => (
                      <span key={tag} className="inline-flex items-center gap-0.5 rounded bg-white/10 px-1.5 py-0.5 text-[10px] text-gray-400">
                        <Tag size={8} /> {tag}
                      </span>
                    ))}
                    {data.tags.length > 3 && <span className="text-[10px] text-gray-600">+{data.tags.length - 3}</span>}
                  </div>
                )}
                <Button
                  size="sm"
                  variant="outline"
                  className="w-full"
                  onClick={(e) => {
                    e.stopPropagation();
                    if (isSeed) {
                      handleUseSeed(data as SeedTemplate);
                    } else {
                      handleInstantiate((data as Template).id);
                    }
                  }}
                  disabled={instantiating === key}
                >
                  <Zap size={14} className="mr-1.5" />
                  {instantiating === key ? "Creating…" : "Use Template"}
                </Button>
              </div>
            );
          })}
        </div>
      )}

      {/* Detail Modal */}
      {detailItem && (
        <TemplateDetailModal
          template={detailItem}
          onClose={() => setDetailItem(null)}
          onUse={() => {
            if ("id" in detailItem) {
              handleInstantiate((detailItem as Template).id);
            } else {
              handleUseSeed(detailItem as SeedTemplate);
            }
          }}
          using={instantiating !== null}
        />
      )}

      {/* Create Modal */}
      {showCreate && (
        <CreateTemplateModal
          onClose={() => setShowCreate(false)}
          onCreated={() => { void fetchTemplates(); }}
        />
      )}
    </div>
  );
}
