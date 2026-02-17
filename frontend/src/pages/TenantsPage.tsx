import { useState, useEffect } from "react";
import { Users, Plus, Loader2, ShieldCheck, ExternalLink } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { apiGet, apiPost } from "@/api/client";
import { TenantDetail } from "@/components/tenants/TenantDetail";

interface Tenant {
  id: string;
  name: string;
  slug: string;
  owner_email: string;
  tier: string;
  status: string;
  created_at: string;
}

interface QuotaInfo {
  resource: string;
  limit: number;
  used: number;
  unit: string;
}

interface UsageSummary {
  total_requests: number;
  total_tokens: number;
  period: string;
}

function statusBadge(status: string) {
  const cls: Record<string, string> = { active: "bg-green-500/20 text-green-400", suspended: "bg-red-500/20 text-red-400", provisioning: "bg-blue-500/20 text-blue-400", deleted: "bg-gray-500/20 text-gray-400" };
  return <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${cls[status] ?? "bg-gray-500/20 text-gray-400"}`}>{status}</span>;
}

function tierBadge(tier: string) {
  const cls: Record<string, string> = { enterprise: "bg-purple-500/20 text-purple-400", team: "bg-blue-500/20 text-blue-400", individual: "bg-green-500/20 text-green-400", free: "bg-gray-500/20 text-gray-400" };
  return <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${cls[tier] ?? "bg-gray-500/20 text-gray-400"}`}>{tier}</span>;
}

function quotaBar(used: number, limit: number) {
  const pct = limit > 0 ? Math.min((used / limit) * 100, 100) : 0;
  const color = pct > 90 ? "bg-red-400" : pct > 70 ? "bg-yellow-400" : "bg-green-400";
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-24 overflow-hidden rounded-full bg-white/10">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-gray-400">{used.toLocaleString()}/{limit.toLocaleString()}</span>
    </div>
  );
}

export function TenantsPage() {
  const navigate = useNavigate();
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [ownerEmail, setOwnerEmail] = useState("");
  const [tier, setTier] = useState("team");
  const [creating, setCreating] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [quotas, setQuotas] = useState<Record<string, QuotaInfo[]>>({});
  const [usage, setUsage] = useState<Record<string, UsageSummary>>({});
  const [selectedTenant, setSelectedTenant] = useState<Tenant | null>(null);

  async function fetchTenants() {
    setLoading(true);
    setError(null);
    try {
      const res = await apiGet<Tenant[]>("/tenants");
      setTenants(Array.isArray(res.data) ? res.data : []);
    } catch {
      setError("Failed to load tenants.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void fetchTenants(); }, []);

  async function handleCreate() {
    if (!name.trim() || !slug.trim() || !ownerEmail.trim()) return;
    setCreating(true);
    try {
      await apiPost("/tenants/signup", { name, slug, owner_email: ownerEmail, tier });
      setShowForm(false);
      setName(""); setSlug(""); setOwnerEmail("");
      await fetchTenants();
    } catch {
      setError("Failed to create tenant.");
    } finally {
      setCreating(false);
    }
  }

  async function handleExpand(id: string) {
    if (expandedId === id) {
      setExpandedId(null);
      return;
    }
    setExpandedId(id);
    try {
      const [quotaRes, usageRes] = await Promise.allSettled([
        apiGet<QuotaInfo[]>(`/tenants/${id}/quota`),
        apiGet<UsageSummary>(`/tenants/${id}/usage/summary`),
      ]);
      if (quotaRes.status === "fulfilled") {
        const d = quotaRes.value.data;
        setQuotas((prev) => ({ ...prev, [id]: Array.isArray(d) ? d : [] }));
      }
      if (usageRes.status === "fulfilled") {
        setUsage((prev) => ({ ...prev, [id]: usageRes.value.data as UsageSummary }));
      }
    } catch {
      // silently fail for detail fetch
    }
  }

  if (loading) {
    return <div className="flex h-64 items-center justify-center"><p className="text-gray-400">Loading...</p></div>;
  }

  if (selectedTenant) {
    return (
      <div className="p-6">
        <TenantDetail
          tenant={selectedTenant}
          onBack={() => setSelectedTenant(null)}
        />
      </div>
    );
  }

  return (
    <div className="p-6">
      {error && (
        <div className="mb-4 rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">{error}</div>
      )}

      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Users size={24} className="text-purple-400" />
          <h1 className="text-2xl font-bold text-white">Tenants</h1>
        </div>
        <Button size="sm" onClick={() => setShowForm(!showForm)}>
          <Plus size={14} className="mr-1.5" />Create Tenant
        </Button>
      </div>
      <p className="mb-6 text-gray-400">Manage multi-tenant workspaces, quotas, and resource isolation.</p>

      {showForm && (
        <div className="mb-6 rounded-lg border border-[#2a2d37] bg-[#1a1d27] p-4">
          <h3 className="mb-3 text-sm font-semibold text-white">New Tenant</h3>
          <div className="flex flex-wrap gap-3">
            <Input placeholder="Tenant name *" value={name} onChange={(e) => setName(e.target.value)} className="max-w-xs" />
            <Input placeholder="slug *" value={slug} onChange={(e) => setSlug(e.target.value)} className="max-w-[160px]" />
            <Input placeholder="Owner email *" value={ownerEmail} onChange={(e) => setOwnerEmail(e.target.value)} className="max-w-xs" />
            <select value={tier} onChange={(e) => setTier(e.target.value)} className="h-9 rounded-md border border-[#2a2d37] bg-[#0f1117] px-3 text-sm text-white">
              <option value="free">Free</option>
              <option value="individual">Individual</option>
              <option value="team">Team</option>
              <option value="enterprise">Enterprise</option>
            </select>
            <Button size="sm" onClick={handleCreate} disabled={creating || !name.trim() || !slug.trim() || !ownerEmail.trim()}>
              {creating && <Loader2 size={14} className="mr-1.5 animate-spin" />}
              Create
            </Button>
          </div>
        </div>
      )}

      <div className="rounded-lg border border-[#2a2d37] bg-[#1a1d27]">
        {tenants.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12">
            <Users size={32} className="mb-2 text-gray-600" />
            <p className="text-sm text-gray-500">No tenants configured yet.</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead><tr className="border-b border-[#2a2d37] text-left text-xs text-gray-500">
                <th className="px-4 py-2 font-medium">Name</th>
                <th className="px-4 py-2 font-medium">Slug</th>
                <th className="px-4 py-2 font-medium">Tier</th>
                <th className="px-4 py-2 font-medium">Status</th>
                <th className="px-4 py-2 font-medium text-right">Created</th>
              </tr></thead>
              <tbody>{tenants.map((t) => (
                <>
                  <tr key={t.id} className="border-b border-[#2a2d37] hover:bg-white/5 cursor-pointer" onClick={() => setSelectedTenant(t)}>
                    <td className="px-4 py-2 font-medium text-white">{t.name}</td>
                    <td className="px-4 py-2 font-mono text-xs text-gray-400">{t.slug}</td>
                    <td className="px-4 py-2">{tierBadge(t.tier ?? "free")}</td>
                    <td className="px-4 py-2">{statusBadge(t.status ?? "active")}</td>
                    <td className="px-4 py-2 text-right text-gray-400">{new Date(t.created_at).toLocaleDateString()}</td>
                  </tr>
                  {expandedId === t.id && (
                    <tr key={`${t.id}-detail`} className="border-b border-[#2a2d37] bg-[#0f1117]">
                      <td colSpan={5} className="px-6 py-3">
                        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
                          {/* Tenant Details */}
                          <div>
                            <h4 className="mb-2 text-xs font-semibold text-gray-400 uppercase">Tenant Details</h4>
                            <div className="space-y-1.5 text-xs">
                              <div className="text-gray-300">Name: <span className="font-semibold text-white">{t.name}</span></div>
                              <div className="text-gray-300">Slug: <span className="font-mono text-white">{t.slug}</span></div>
                              <div className="text-gray-300">Owner: <span className="text-white">{t.owner_email}</span></div>
                              <div className="text-gray-300">Created: <span className="text-white">{new Date(t.created_at).toLocaleDateString()}</span></div>
                              <div className="mt-3 flex items-center gap-2">
                                <ShieldCheck size={14} className="text-purple-400" />
                                <span className="text-gray-400">IdP:</span>
                                <span className="text-gray-500">Not configured</span>
                              </div>
                              <Button
                                size="sm"
                                variant="outline"
                                className="mt-2"
                                onClick={(e) => { e.stopPropagation(); navigate("/sso"); }}
                              >
                                <ExternalLink size={12} className="mr-1.5" />
                                Configure SSO
                              </Button>
                            </div>
                          </div>
                          <div>
                            <h4 className="mb-2 text-xs font-semibold text-gray-400 uppercase">Quotas</h4>
                            {(quotas[t.id] ?? []).length === 0 ? (
                              <p className="text-xs text-gray-500">No quota data available.</p>
                            ) : (
                              <div className="space-y-2">
                                {quotas[t.id]!.map((q, i) => (
                                  <div key={i}>
                                    <div className="mb-1 text-xs font-medium capitalize text-gray-300">{q.resource}</div>
                                    {quotaBar(q.used, q.limit)}
                                    <div className="mt-0.5 text-[10px] text-gray-500">{q.unit}</div>
                                  </div>
                                ))}
                              </div>
                            )}
                          </div>
                          <div>
                            <h4 className="mb-2 text-xs font-semibold text-gray-400 uppercase">Usage Summary</h4>
                            {usage[t.id] ? (
                              <div className="space-y-1 text-xs">
                                <div className="text-gray-300">Requests: <span className="font-semibold text-white">{(usage[t.id]!.total_requests ?? 0).toLocaleString()}</span></div>
                                <div className="text-gray-300">Tokens: <span className="font-semibold text-white">{(usage[t.id]!.total_tokens ?? 0).toLocaleString()}</span></div>
                                <div className="text-gray-500">Period: {usage[t.id]!.period ?? "—"}</div>
                              </div>
                            ) : (
                              <p className="text-xs text-gray-500">No usage data available.</p>
                            )}
                          </div>
                        </div>
                      </td>
                    </tr>
                  )}
                </>
              ))}</tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
