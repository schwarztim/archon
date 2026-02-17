import { useState, useEffect } from "react";
import { Store, Search, Star, Download, Plus, X, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { apiGet, apiPost } from "@/api/client";

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

function stars(rating: number) {
  return (
    <span className="inline-flex items-center gap-0.5">
      {Array.from({ length: 5 }, (_, i) => (
        <Star key={i} size={12} className={i < Math.round(rating) ? "fill-yellow-400 text-yellow-400" : "text-gray-600"} />
      ))}
      <span className="ml-1 text-xs text-gray-400">{rating.toFixed(1)}</span>
    </span>
  );
}

export function MarketplacePage() {
  const [listings, setListings] = useState<MarketplaceListing[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [installing, setInstalling] = useState(false);

  // Create form
  const [showCreateForm, setShowCreateForm] = useState(false);
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

  const categories = ["all", ...new Set(listings.map((l) => l.category).filter(Boolean))];

  const filtered = listings.filter((l) => {
    if (category !== "all" && l.category !== category) return false;
    if (search && !l.name.toLowerCase().includes(search.toLowerCase()) && !(l.tags ?? []).some((t) => t.includes(search.toLowerCase()))) return false;
    return true;
  });

  const selected = listings.find((l) => l.id === selectedId);

  async function handleInstall(listingId: string) {
    setInstalling(true);
    try {
      await apiPost("/marketplace/installs", {
        listing_id: listingId,
        user_id: "current-user",
        installed_version: selected?.version ?? "1.0.0",
      });
      await fetchListings();
    } catch {
      setError("Failed to install agent.");
    } finally {
      setInstalling(false);
    }
  }

  async function handleCreate() {
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
      setShowCreateForm(false);
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
        <div className="mb-4 rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">{error}</div>
      )}

      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Store size={24} className="text-purple-400" />
          <h1 className="text-2xl font-bold text-white">Marketplace</h1>
        </div>
        <Button size="sm" onClick={() => setShowCreateForm(!showCreateForm)}>
          <Plus size={14} className="mr-1.5" />Publish
        </Button>
      </div>
      <p className="mb-6 text-gray-400">Browse and install reusable agent components, templates, and integrations.</p>

      {/* Create form */}
      {showCreateForm && (
        <div className="mb-6 rounded-lg border border-[#2a2d37] bg-[#1a1d27] p-4">
          <h3 className="mb-3 text-sm font-semibold text-white">Publish Listing</h3>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <Input placeholder="Name *" value={formName} onChange={(e) => setFormName(e.target.value)} />
            <Input placeholder="Category *" value={formCategory} onChange={(e) => setFormCategory(e.target.value)} />
            <Input placeholder="Creator ID *" value={formCreatorId} onChange={(e) => setFormCreatorId(e.target.value)} />
            <Input placeholder="Description" value={formDesc} onChange={(e) => setFormDesc(e.target.value)} className="sm:col-span-2 lg:col-span-3" />
            <Input placeholder="Tags (comma separated)" value={formTags} onChange={(e) => setFormTags(e.target.value)} />
            <Input placeholder="Version" value={formVersion} onChange={(e) => setFormVersion(e.target.value)} />
            <Input placeholder="License" value={formLicense} onChange={(e) => setFormLicense(e.target.value)} />
          </div>
          <div className="mt-3">
            <Button size="sm" onClick={handleCreate} disabled={creating || !formName.trim() || !formCategory.trim() || !formCreatorId.trim()}>
              {creating && <Loader2 size={14} className="mr-1.5 animate-spin" />}
              Publish
            </Button>
          </div>
        </div>
      )}

      {/* Search + category filter */}
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="relative max-w-xs flex-1">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
          <Input placeholder="Search agents…" value={search} onChange={(e) => setSearch(e.target.value)} className="pl-9" />
        </div>
        <div className="flex gap-1">
          {categories.map((c) => (
            <button key={c} onClick={() => setCategory(c)} className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${c === category ? "bg-purple-500/20 text-purple-400" : "text-gray-400 hover:bg-white/5"}`}>
              {c}
            </button>
          ))}
        </div>
      </div>

      {/* Detail modal */}
      {selected && (
        <div className="mb-6 rounded-lg border border-[#2a2d37] bg-[#1a1d27] p-5">
          <div className="mb-3 flex items-start justify-between">
            <div>
              <h3 className="text-lg font-semibold text-white">{selected.name}</h3>
              <p className="text-sm text-gray-400">by {selected.author_name ?? selected.creator_id} · v{selected.version}</p>
            </div>
            <button onClick={() => setSelectedId(null)} className="text-gray-500 hover:text-white"><X size={16} /></button>
          </div>
          <p className="mb-3 text-sm text-gray-300">{selected.description}</p>
          <div className="mb-3 flex items-center gap-4 text-sm">
            {stars(selected.avg_rating ?? 0)}
            <span className="flex items-center gap-1 text-gray-400"><Download size={12} />{(selected.install_count ?? 0).toLocaleString()} installs</span>
            <span className="text-gray-400">{(selected.price ?? 0) === 0 ? "Free" : `$${selected.price}`}</span>
          </div>
          <div className="mb-3 flex flex-wrap gap-1.5">{(selected.tags ?? []).map((t) => <span key={t} className="rounded bg-white/10 px-2 py-0.5 text-xs text-gray-300">{t}</span>)}</div>
          <Button size="sm" onClick={() => handleInstall(selected.id)} disabled={installing}>
            {installing ? <Loader2 size={14} className="mr-1.5 animate-spin" /> : <Download size={14} className="mr-1.5" />}
            Install Agent
          </Button>
        </div>
      )}

      {/* Listing cards grid */}
      {filtered.length === 0 ? (
        <div className="flex items-center justify-center rounded-lg border border-[#2a2d37] bg-[#1a1d27] py-16">
          <span className="text-sm text-gray-500">
            {listings.length === 0 ? "No marketplace listings yet." : "No listings match your search."}
          </span>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {filtered.map((l) => (
            <div key={l.id} onClick={() => setSelectedId(l.id)} className="cursor-pointer rounded-lg border border-[#2a2d37] bg-[#1a1d27] p-4 transition-colors hover:border-purple-500/40">
              <div className="mb-2 flex items-center justify-between">
                <h3 className="text-sm font-semibold text-white">{l.name}</h3>
                {(l.price ?? 0) > 0 && <span className="rounded bg-purple-500/20 px-1.5 py-0.5 text-xs font-medium text-purple-400">${l.price}</span>}
              </div>
              <p className="mb-3 line-clamp-2 text-xs text-gray-400">{l.description}</p>
              <div className="mb-2 flex flex-wrap gap-1">{(l.tags ?? []).map((t) => <span key={t} className="rounded bg-white/10 px-1.5 py-0.5 text-[10px] text-gray-400">{t}</span>)}</div>
              <div className="flex items-center justify-between text-xs text-gray-500">
                <span>{l.author_name ?? l.creator_id}</span>
                <div className="flex items-center gap-3">
                  {stars(l.avg_rating ?? 0)}
                  <span className="flex items-center gap-1"><Download size={10} />{(l.install_count ?? 0).toLocaleString()}</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
