import { useState, useEffect } from "react";
import { LayoutTemplate, Plus, X, Tag, Zap } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { apiGet, apiPost } from "@/api/client";

interface Template {
  id: string;
  name: string;
  description: string;
  category: string;
  definition: Record<string, unknown>;
  tags: string[];
  created_at: string;
}

export function TemplatesPage() {
  const [templates, setTemplates] = useState<Template[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [creating, setCreating] = useState(false);
  const [instantiating, setInstantiating] = useState<string | null>(null);
  const [form, setForm] = useState({
    name: "",
    description: "",
    category: "general",
    definition: "{}",
    tags: "",
  });

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

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!form.name || !form.category) return;
    setCreating(true);
    try {
      let definition = {};
      try { definition = JSON.parse(form.definition); } catch { /* use empty */ }
      await apiPost("/templates/", {
        name: form.name,
        description: form.description,
        category: form.category,
        definition,
        tags: form.tags.split(",").map((t) => t.trim()).filter(Boolean),
      });
      setForm({ name: "", description: "", category: "general", definition: "{}", tags: "" });
      setShowForm(false);
      await fetchTemplates();
    } catch {
      setError("Failed to create template.");
    } finally {
      setCreating(false);
    }
  }

  async function handleInstantiate(id: string) {
    setInstantiating(id);
    try {
      await apiPost(`/templates/${id}/instantiate`, {});
      alert("Template instantiated successfully!");
    } catch {
      setError("Failed to instantiate template.");
    } finally {
      setInstantiating(null);
    }
  }

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <p className="text-gray-400">Loading...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6">
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-4 text-red-400">{error}</div>
      </div>
    );
  }

  return (
    <div className="p-6">
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <LayoutTemplate size={24} className="text-purple-400" />
          <h1 className="text-2xl font-bold text-white">Templates</h1>
        </div>
        <Button size="sm" className="bg-purple-600 hover:bg-purple-700" onClick={() => setShowForm(!showForm)}>
          {showForm ? <><X size={14} className="mr-1.5" /> Cancel</> : <><Plus size={14} className="mr-1.5" /> Create Template</>}
        </Button>
      </div>
      <p className="mb-6 text-gray-400">Browse and manage agent templates. Instantiate templates to create new agents.</p>

      {showForm && (
        <form onSubmit={handleCreate} className="mb-6 rounded-lg border border-[#2a2d37] bg-[#1a1d27] p-4">
          <h3 className="mb-3 text-sm font-semibold text-white">New Template</h3>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <label className="mb-1 block text-xs text-gray-400">Name *</label>
              <input className="h-9 w-full rounded-md border border-[#2a2d37] bg-[#0f1117] px-3 text-sm text-white" placeholder="My Template" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            </div>
            <div>
              <label className="mb-1 block text-xs text-gray-400">Category *</label>
              <input className="h-9 w-full rounded-md border border-[#2a2d37] bg-[#0f1117] px-3 text-sm text-white" placeholder="general" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} />
            </div>
            <div className="sm:col-span-2">
              <label className="mb-1 block text-xs text-gray-400">Description</label>
              <input className="h-9 w-full rounded-md border border-[#2a2d37] bg-[#0f1117] px-3 text-sm text-white" placeholder="Describe this template" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
            </div>
            <div>
              <label className="mb-1 block text-xs text-gray-400">Definition (JSON) *</label>
              <textarea className="w-full rounded-md border border-[#2a2d37] bg-[#0f1117] px-3 py-2 text-sm text-white font-mono" rows={3} placeholder='{"system_prompt":"..."}' value={form.definition} onChange={(e) => setForm({ ...form, definition: e.target.value })} />
            </div>
            <div>
              <label className="mb-1 block text-xs text-gray-400">Tags (comma-sep)</label>
              <input className="h-9 w-full rounded-md border border-[#2a2d37] bg-[#0f1117] px-3 text-sm text-white" placeholder="chat, support" value={form.tags} onChange={(e) => setForm({ ...form, tags: e.target.value })} />
            </div>
            <div className="flex items-end sm:col-span-2">
              <Button type="submit" size="sm" className="bg-purple-600 hover:bg-purple-700" disabled={creating}>
                {creating ? "Creating…" : "Create Template"}
              </Button>
            </div>
          </div>
        </form>
      )}

      {templates.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-lg border border-[#2a2d37] bg-[#1a1d27] py-16">
          <LayoutTemplate size={40} className="mb-3 text-gray-600" />
          <p className="text-sm text-gray-500">No templates yet. Create your first template.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {templates.map((t) => (
            <div key={t.id} className="rounded-lg border border-[#2a2d37] bg-[#1a1d27] p-4">
              <div className="mb-2 flex items-start justify-between">
                <h3 className="text-sm font-semibold text-white">{t.name}</h3>
                <span className="rounded bg-purple-500/20 px-2 py-0.5 text-[10px] font-medium text-purple-300">{t.category}</span>
              </div>
              {t.description && <p className="mb-3 text-xs text-gray-400">{t.description}</p>}
              {t.tags && t.tags.length > 0 && (
                <div className="mb-3 flex flex-wrap gap-1">
                  {t.tags.map((tag) => (
                    <span key={tag} className="inline-flex items-center gap-1 rounded bg-white/10 px-1.5 py-0.5 text-[10px] text-gray-400">
                      <Tag size={8} /> {tag}
                    </span>
                  ))}
                </div>
              )}
              <Button size="sm" variant="outline" className="w-full" onClick={() => handleInstantiate(t.id)} disabled={instantiating === t.id}>
                <Zap size={14} className="mr-1.5" />
                {instantiating === t.id ? "Instantiating…" : "Instantiate"}
              </Button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
