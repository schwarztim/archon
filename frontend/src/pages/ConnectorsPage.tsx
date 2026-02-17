import { useState, useEffect } from "react";
import { Plug, Plus, X, Database, Globe, Cloud, Wifi, WifiOff, AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { apiGet, apiPost } from "@/api/client";

interface Connector {
  id: string;
  name: string;
  type: string;
  config: Record<string, unknown>;
  status: string;
  created_at: string;
}

const typeIcons: Record<string, typeof Database> = { postgresql: Database, pinecone: Cloud, rest_api: Globe, s3: Cloud, redis: Database };

function statusDot(status: string) {
  const colors: Record<string, string> = { connected: "bg-green-400", active: "bg-green-400", disconnected: "bg-gray-400", error: "bg-red-400", pending: "bg-yellow-400" };
  return <span className={`inline-block h-2.5 w-2.5 rounded-full ${colors[status] ?? "bg-gray-400"}`} />;
}

function statusIcon(status: string) {
  if (status === "connected" || status === "active") return <Wifi size={14} className="text-green-400" />;
  if (status === "error") return <AlertTriangle size={14} className="text-red-400" />;
  return <WifiOff size={14} className="text-gray-400" />;
}

export function ConnectorsPage() {
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({
    name: "",
    type: "postgresql",
    config: "{}",
    status: "pending",
  });

  async function fetchConnectors() {
    setLoading(true);
    setError(null);
    try {
      const res = await apiGet<Connector[]>("/connectors/");
      setConnectors(Array.isArray(res.data) ? res.data : []);
    } catch {
      setError("Failed to load connectors.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void fetchConnectors(); }, []);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!form.name || !form.type) return;
    setCreating(true);
    try {
      let config = {};
      try { config = JSON.parse(form.config); } catch { /* use empty */ }
      await apiPost("/connectors/", {
        name: form.name,
        type: form.type,
        config,
        status: form.status,
      });
      setForm({ name: "", type: "postgresql", config: "{}", status: "pending" });
      setShowForm(false);
      await fetchConnectors();
    } catch {
      setError("Failed to create connector.");
    } finally {
      setCreating(false);
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
          <Plug size={24} className="text-purple-400" />
          <h1 className="text-2xl font-bold text-white">Connectors</h1>
        </div>
        <Button size="sm" className="bg-purple-600 hover:bg-purple-700" onClick={() => setShowForm(!showForm)}>
          {showForm ? <><X size={14} className="mr-1.5" /> Cancel</> : <><Plus size={14} className="mr-1.5" /> Add Connector</>}
        </Button>
      </div>
      <p className="mb-6 text-gray-400">Manage data source connections, API integrations, and vector store configurations.</p>

      {showForm && (
        <form onSubmit={handleCreate} className="mb-6 rounded-lg border border-[#2a2d37] bg-[#1a1d27] p-4">
          <h3 className="mb-3 text-sm font-semibold text-white">New Connector</h3>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <div>
              <label className="mb-1 block text-xs text-gray-400">Name *</label>
              <input className="h-9 w-full rounded-md border border-[#2a2d37] bg-[#0f1117] px-3 text-sm text-white" placeholder="Production DB" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            </div>
            <div>
              <label className="mb-1 block text-xs text-gray-400">Type *</label>
              <select value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })} className="h-9 w-full rounded-md border border-[#2a2d37] bg-[#0f1117] px-3 text-sm text-white">
                <option value="postgresql">PostgreSQL</option>
                <option value="pinecone">Pinecone</option>
                <option value="rest_api">REST API</option>
                <option value="s3">S3</option>
                <option value="redis">Redis</option>
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs text-gray-400">Config (JSON) *</label>
              <input className="h-9 w-full rounded-md border border-[#2a2d37] bg-[#0f1117] px-3 text-sm text-white font-mono" placeholder='{"host":"..."}' value={form.config} onChange={(e) => setForm({ ...form, config: e.target.value })} />
            </div>
            <div className="flex items-end">
              <Button type="submit" size="sm" className="w-full bg-purple-600 hover:bg-purple-700" disabled={creating}>
                {creating ? "Creating…" : "Save"}
              </Button>
            </div>
          </div>
        </form>
      )}

      {connectors.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-lg border border-[#2a2d37] bg-[#1a1d27] py-16">
          <Plug size={40} className="mb-3 text-gray-600" />
          <p className="text-sm text-gray-500">No connectors yet. Add your first connector.</p>
        </div>
      ) : (
        <div className="rounded-lg border border-[#2a2d37] bg-[#1a1d27]">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[#2a2d37] text-left text-xs text-gray-500">
                  <th className="px-4 py-2 font-medium">Name</th>
                  <th className="px-4 py-2 font-medium">Type</th>
                  <th className="px-4 py-2 font-medium">Status</th>
                  <th className="px-4 py-2 font-medium text-right">Created</th>
                </tr>
              </thead>
              <tbody>
                {connectors.map((c) => {
                  const Icon = typeIcons[c.type] ?? Globe;
                  return (
                    <tr key={c.id} className="border-b border-[#2a2d37] hover:bg-white/5">
                      <td className="px-4 py-2">
                        <div className="flex items-center gap-2">
                          <Icon size={16} className="text-purple-400" />
                          <span className="font-medium text-white">{c.name}</span>
                        </div>
                      </td>
                      <td className="px-4 py-2 text-gray-400">{c.type}</td>
                      <td className="px-4 py-2">
                        <div className="flex items-center gap-2">
                          {statusDot(c.status)}
                          {statusIcon(c.status)}
                          <span className="capitalize text-gray-400">{c.status}</span>
                        </div>
                      </td>
                      <td className="px-4 py-2 text-right text-gray-400">{new Date(c.created_at).toLocaleDateString()}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
