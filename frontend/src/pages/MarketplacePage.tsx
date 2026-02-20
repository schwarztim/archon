import { useState, useEffect, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import {
  Store,
  Search,
  Star,
  Download,
  Plus,
  X,
  Loader2,
  Headphones,
  BarChart3,
  FileText,
  Code2,
  Server,
  Bot,
  ShieldCheck,
  Globe,
  Mail,
  Cog,
  Sparkles,
  BrainCircuit,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { apiGet, apiPost } from "@/api/client";

// ─── Types ───────────────────────────────────────────────────────────

interface MarketplaceListing {
  id: string;
  name: string;
  description: string;
  category: string;
  tags: string[];
  version: string;
  license: string;
  creator_id: string;
  author_name?: string;
  install_count: number;
  avg_rating: number;
  price: number;
  definition: Record<string, unknown>;
  created_at: string;
}

// ─── Seed Marketplace Data ──────────────────────────────────────────

interface SeedListing {
  name: string;
  description: string;
  category: string;
  tags: string[];
  version: string;
  publisher: string;
  downloads: number;
  rating: number;
  icon: typeof Bot;
}

const SEED_LISTINGS: SeedListing[] = [
  { name: "Enterprise Support Suite", description: "Complete customer support solution with multi-channel intake, smart routing, SLA tracking, and automated follow-ups.", category: "Customer Support", tags: ["enterprise", "support", "sla"], version: "2.3.1", publisher: "Archon Labs", downloads: 12450, rating: 4.8, icon: Headphones },
  { name: "DataFlow Analyzer", description: "Real-time data pipeline monitoring and analysis with anomaly detection and alerting.", category: "Data Analysis", tags: ["analytics", "pipeline", "monitoring"], version: "1.7.0", publisher: "DataWorks", downloads: 8320, rating: 4.6, icon: BarChart3 },
  { name: "ContentForge Pro", description: "AI-powered content creation toolkit with SEO optimization, brand voice consistency, and multi-format output.", category: "Content Generation", tags: ["content", "seo", "brand"], version: "3.1.0", publisher: "ContentAI", downloads: 15200, rating: 4.9, icon: FileText },
  { name: "CodeGuard", description: "Automated code review agent with security scanning, OWASP compliance checks, and fix suggestions.", category: "Code Assistant", tags: ["security", "code-review", "owasp"], version: "2.0.4", publisher: "SecureDev", downloads: 9870, rating: 4.7, icon: ShieldCheck },
  { name: "DeployPilot", description: "Intelligent CI/CD orchestrator that monitors builds, predicts failures, and auto-remediates common issues.", category: "DevOps", tags: ["ci-cd", "automation", "monitoring"], version: "1.5.2", publisher: "DevOps Co", downloads: 6540, rating: 4.5, icon: Server },
  { name: "ResearchBot", description: "Academic research assistant that searches papers, extracts key findings, and generates summaries.", category: "Research", tags: ["academic", "papers", "nlp"], version: "1.2.0", publisher: "ScholarAI", downloads: 4210, rating: 4.4, icon: BrainCircuit },
  { name: "Email Genius", description: "Smart email automation with personalization, A/B testing, deliverability optimization, and analytics.", category: "Marketing", tags: ["email", "automation", "marketing"], version: "2.1.0", publisher: "MailFlow", downloads: 7630, rating: 4.6, icon: Mail },
  { name: "API Connector Hub", description: "Universal API integration agent supporting REST, GraphQL, and WebSocket with automatic schema discovery.", category: "Integration", tags: ["api", "integration", "rest"], version: "1.8.3", publisher: "ConnectIO", downloads: 11200, rating: 4.7, icon: Globe },
  { name: "Compliance Checker", description: "Automated compliance monitoring for GDPR, HIPAA, SOC2, and custom regulatory frameworks.", category: "Governance", tags: ["compliance", "gdpr", "hipaa"], version: "2.4.0", publisher: "ComplianceAI", downloads: 5890, rating: 4.8, icon: ShieldCheck },
  { name: "Smart Scheduler", description: "AI scheduling agent for meetings, tasks, and resource allocation with calendar integration.", category: "Productivity", tags: ["scheduling", "calendar", "ai"], version: "1.3.1", publisher: "TimeSmart", downloads: 3450, rating: 4.3, icon: Cog },
  { name: "DocuGen", description: "Automated documentation generator from codebases with API spec, README, and changelog support.", category: "Code Assistant", tags: ["docs", "api-spec", "readme"], version: "1.1.0", publisher: "DocuFlow", downloads: 4780, rating: 4.5, icon: Code2 },
  { name: "SentimentScope", description: "Real-time sentiment analysis across social media, reviews, and support tickets with trend dashboards.", category: "Data Analysis", tags: ["sentiment", "social", "nlp"], version: "1.4.2", publisher: "InsightAI", downloads: 6120, rating: 4.4, icon: Sparkles },
];

type SortOption = "popular" | "rating" | "newest" | "name";

const SORT_OPTIONS: { value: SortOption; label: string }[] = [
  { value: "popular", label: "Most Popular" },
  { value: "rating", label: "Highest Rated" },
  { value: "newest", label: "Newest" },
  { value: "name", label: "Name A-Z" },
];

// ─── Helpers ─────────────────────────────────────────────────────────

function Stars({ rating }: { rating: number }) {
  return (
    <span className="inline-flex items-center gap-0.5">
      {Array.from({ length: 5 }, (_, i) => (
        <Star key={i} size={12} className={i < Math.round(rating) ? "fill-yellow-400 text-yellow-400" : "text-gray-600"} />
      ))}
      <span className="ml-1 text-xs text-gray-400">{rating.toFixed(1)}</span>
    </span>
  );
}

function formatDownloads(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

// ─── Install Confirmation Dialog ─────────────────────────────────────

function InstallDialog({
  name,
  onConfirm,
  onCancel,
  installing,
}: {
  name: string;
  onConfirm: () => void;
  onCancel: () => void;
  installing: boolean;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="w-full max-w-sm rounded-xl border border-[#2a2d37] bg-[#12141e] p-6 shadow-2xl">
        <h3 className="mb-2 text-lg font-semibold text-white">Install Agent</h3>
        <p className="mb-5 text-sm text-gray-400">
          Install <span className="font-medium text-white">{name}</span>? This will create a new agent from the package template.
        </p>
        <div className="flex items-center justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onCancel} disabled={installing}>Cancel</Button>
          <Button size="sm" className="bg-purple-600 hover:bg-purple-700" onClick={onConfirm} disabled={installing}>
            {installing ? <Loader2 size={14} className="mr-1.5 animate-spin" /> : <Download size={14} className="mr-1.5" />}
            Install
          </Button>
        </div>
      </div>
    </div>
  );
}

// ─── Main Page ───────────────────────────────────────────────────────

export function MarketplacePage() {
  const navigate = useNavigate();
  const [listings, setListings] = useState<MarketplaceListing[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("all");
  const [sort, setSort] = useState<SortOption>("popular");
  const [installTarget, setInstallTarget] = useState<{ type: "api" | "seed"; id?: string; seed?: SeedListing } | null>(null);
  const [installing, setInstalling] = useState(false);

  // Publish form
  const [showPublish, setShowPublish] = useState(false);
  const [formName, setFormName] = useState("");
  const [formDesc, setFormDesc] = useState("");
  const [formCategory, setFormCategory] = useState("general");
  const [formTags, setFormTags] = useState("");
  const [formVersion, setFormVersion] = useState("1.0.0");
  const [formLicense, setFormLicense] = useState("MIT");
  const [formCreatorId, setFormCreatorId] = useState("");
  const [creating, setCreating] = useState(false);

  async function fetchListings() {
    setLoading(true);
    setError(null);
    try {
      const res = await apiGet<MarketplaceListing[]>("/marketplace/listings");
      setListings(Array.isArray(res.data) ? res.data : []);
    } catch {
      setError("Failed to load marketplace listings.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void fetchListings(); }, []);

  // Combine API listings + seed data
  type DisplayItem = { type: "api"; data: MarketplaceListing } | { type: "seed"; data: SeedListing };

  const combined = useMemo<DisplayItem[]>(() => {
    const items: DisplayItem[] = [];
    listings.forEach((l) => items.push({ type: "api", data: l }));
    SEED_LISTINGS.forEach((s) => {
      if (!listings.some((l) => l.name === s.name)) {
        items.push({ type: "seed", data: s });
      }
    });
    return items;
  }, [listings]);

  // All categories from combined data
  const categories = useMemo(() => {
    const cats = new Set<string>();
    combined.forEach((item) => cats.add(item.data.category));
    return ["all", ...Array.from(cats).sort()];
  }, [combined]);

  // Filter + sort
  const filtered = useMemo(() => {
    let items = combined.filter((item) => {
      if (category !== "all" && item.data.category !== category) return false;
      if (search) {
        const q = search.toLowerCase();
        const name = item.data.name.toLowerCase();
        const desc = item.data.description.toLowerCase();
        const tags = item.data.tags;
        if (!name.includes(q) && !desc.includes(q) && !tags.some((t) => t.includes(q))) return false;
      }
      return true;
    });

    items.sort((a, b) => {
      const aDownloads = a.type === "api" ? a.data.install_count : a.data.downloads;
      const bDownloads = b.type === "api" ? b.data.install_count : b.data.downloads;
      const aRating = a.type === "api" ? a.data.avg_rating : a.data.rating;
      const bRating = b.type === "api" ? b.data.avg_rating : b.data.rating;

      switch (sort) {
        case "popular": return bDownloads - aDownloads;
        case "rating": return bRating - aRating;
        case "name": return a.data.name.localeCompare(b.data.name);
        case "newest":
        default: return 0;
      }
    });

    return items;
  }, [combined, category, search, sort]);

  async function handleInstall() {
    if (!installTarget) return;
    setInstalling(true);
    try {
      if (installTarget.type === "api" && installTarget.id) {
        await apiPost("/marketplace/installs", {
          listing_id: installTarget.id,
          user_id: "current-user",
          installed_version: "1.0.0",
        });
        await fetchListings();
      } else if (installTarget.type === "seed" && installTarget.seed) {
        // Create from seed template
        await apiPost("/templates/", {
          name: installTarget.seed.name,
          description: installTarget.seed.description,
          category: installTarget.seed.category,
          definition: {},
          tags: installTarget.seed.tags,
        });
      }
      setInstallTarget(null);
      navigate("/agents");
    } catch {
      setError("Failed to install agent.");
    } finally {
      setInstalling(false);
    }
  }

  async function handlePublish() {
    if (!formName.trim() || !formCategory.trim() || !formCreatorId.trim()) return;
    setCreating(true);
    try {
      await apiPost("/marketplace/listings", {
        name: formName,
        description: formDesc,
        category: formCategory,
        tags: formTags.split(",").map((t) => t.trim()).filter(Boolean),
        version: formVersion,
        license: formLicense,
        definition: {},
        creator_id: formCreatorId,
      });
      setShowPublish(false);
      setFormName(""); setFormDesc(""); setFormTags(""); setFormCreatorId("");
      await fetchListings();
    } catch {
      setError("Failed to create listing.");
    } finally {
      setCreating(false);
    }
  }

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
          <Store size={24} className="text-purple-400" />
          <h1 className="text-2xl font-bold text-white">Marketplace</h1>
          <span className="rounded-full bg-[#1a1d27] px-2 py-0.5 text-xs text-gray-400">{filtered.length}</span>
        </div>
        <Button size="sm" onClick={() => setShowPublish(!showPublish)}>
          <Plus size={14} className="mr-1.5" /> Publish
        </Button>
      </div>
      <p className="mb-6 text-gray-400">Browse and install reusable agent components, templates, and integrations.</p>

      {/* Publish form */}
      {showPublish && (
        <div className="mb-6 rounded-lg border border-[#2a2d37] bg-[#1a1d27] p-4">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-white">Publish Listing</h3>
            <button onClick={() => setShowPublish(false)} className="text-gray-500 hover:text-white"><X size={14} /></button>
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <Input placeholder="Name *" value={formName} onChange={(e) => setFormName(e.target.value)} className="bg-[#0f1117] text-white border-[#2a2d37]" />
            <Input placeholder="Category *" value={formCategory} onChange={(e) => setFormCategory(e.target.value)} className="bg-[#0f1117] text-white border-[#2a2d37]" />
            <Input placeholder="Creator ID *" value={formCreatorId} onChange={(e) => setFormCreatorId(e.target.value)} className="bg-[#0f1117] text-white border-[#2a2d37]" />
            <Input placeholder="Description" value={formDesc} onChange={(e) => setFormDesc(e.target.value)} className="sm:col-span-2 lg:col-span-3 bg-[#0f1117] text-white border-[#2a2d37]" />
            <Input placeholder="Tags (comma separated)" value={formTags} onChange={(e) => setFormTags(e.target.value)} className="bg-[#0f1117] text-white border-[#2a2d37]" />
            <Input placeholder="Version" value={formVersion} onChange={(e) => setFormVersion(e.target.value)} className="bg-[#0f1117] text-white border-[#2a2d37]" />
            <Input placeholder="License" value={formLicense} onChange={(e) => setFormLicense(e.target.value)} className="bg-[#0f1117] text-white border-[#2a2d37]" />
          </div>
          <div className="mt-3">
            <Button size="sm" onClick={handlePublish} disabled={creating || !formName.trim() || !formCategory.trim() || !formCreatorId.trim()}>
              {creating && <Loader2 size={14} className="mr-1.5 animate-spin" />}
              Publish
            </Button>
          </div>
        </div>
      )}

      {/* Search + Category Filter + Sort */}
      <div className="mb-5 flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[200px] max-w-xs">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
          <Input placeholder="Search agents…" value={search} onChange={(e) => setSearch(e.target.value)} className="pl-9 bg-[#0f1117] text-white border-[#2a2d37]" />
        </div>
        <div className="flex flex-wrap gap-1">
          {categories.map((c) => (
            <button
              key={c}
              onClick={() => setCategory(c)}
              className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${
                c === category ? "bg-purple-500/20 text-purple-400" : "text-gray-400 hover:bg-white/5"
              }`}
            >
              {c === "all" ? "All" : c}
            </button>
          ))}
        </div>
        <select
          value={sort}
          onChange={(e) => setSort(e.target.value as SortOption)}
          className="rounded-lg border border-[#2a2d37] bg-[#1a1d27] px-3 py-1.5 text-xs text-white focus:border-purple-500 focus:outline-none"
        >
          {SORT_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
      </div>

      {/* Package Cards Grid */}
      {filtered.length === 0 ? (
        <div className="flex items-center justify-center rounded-lg border border-[#2a2d37] bg-[#1a1d27] py-16">
          <span className="text-sm text-gray-500">
            {combined.length === 0 ? "No marketplace listings yet." : "No listings match your search."}
          </span>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {filtered.map((item) => {
            const isApi = item.type === "api";
            const data = item.data;
            const key = isApi ? (data as MarketplaceListing).id : (data as SeedListing).name;
            const Icon = isApi ? Bot : (data as SeedListing).icon;
            const publisher = isApi ? ((data as MarketplaceListing).author_name ?? (data as MarketplaceListing).creator_id) : (data as SeedListing).publisher;
            const version = isApi ? (data as MarketplaceListing).version : (data as SeedListing).version;
            const downloads = isApi ? (data as MarketplaceListing).install_count : (data as SeedListing).downloads;
            const rating = isApi ? (data as MarketplaceListing).avg_rating : (data as SeedListing).rating;

            return (
              <div key={key} className="rounded-lg border border-[#2a2d37] bg-[#1a1d27] p-4 transition-colors hover:border-purple-500/30">
                <div className="mb-3 flex items-start gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-purple-500/10 flex-shrink-0">
                    <Icon size={20} className="text-purple-400" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <h3 className="text-sm font-semibold text-white truncate">{data.name}</h3>
                    <p className="text-[11px] text-gray-500">{publisher} · v{version}</p>
                  </div>
                </div>
                <p className="mb-3 line-clamp-2 text-xs text-gray-400">{data.description}</p>
                <div className="mb-3 flex flex-wrap gap-1">
                  {data.tags.slice(0, 3).map((t) => (
                    <span key={t} className="rounded bg-white/10 px-1.5 py-0.5 text-[10px] text-gray-400">{t}</span>
                  ))}
                </div>
                <div className="mb-3 flex items-center justify-between text-xs text-gray-500">
                  <Stars rating={rating ?? 0} />
                  <span className="flex items-center gap-1">
                    <Download size={10} /> {formatDownloads(downloads ?? 0)}
                  </span>
                </div>
                <Button
                  size="sm"
                  className="w-full bg-purple-600 hover:bg-purple-700"
                  onClick={() => {
                    if (isApi) {
                      setInstallTarget({ type: "api", id: (data as MarketplaceListing).id });
                    } else {
                      setInstallTarget({ type: "seed", seed: data as SeedListing });
                    }
                  }}
                >
                  <Download size={14} className="mr-1.5" /> Install
                </Button>
              </div>
            );
          })}
        </div>
      )}

      {/* Install Confirmation Dialog */}
      {installTarget && (
        <InstallDialog
          name={installTarget.type === "api" ? (listings.find((l) => l.id === installTarget.id)?.name ?? "Agent") : (installTarget.seed?.name ?? "Agent")}
          onConfirm={handleInstall}
          onCancel={() => setInstallTarget(null)}
          installing={installing}
        />
      )}
    </div>
  );
}
