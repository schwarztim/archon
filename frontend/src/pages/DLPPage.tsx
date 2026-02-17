import { useState, useEffect } from "react";
import {
  ShieldAlert,
  Search,
  EyeOff,
  Plus,
  Loader2,
  CheckCircle2,
  AlertTriangle,
  Shield,
  X,
  Trash2,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import { apiGet, apiPost, apiDelete } from "@/api/client";

interface DLPPolicy {
  id: string;
  name: string;
  description: string | null;
  is_active: boolean;
  detector_types: string[];
  custom_patterns: Record<string, unknown>;
  action: string;
  sensitivity: string;
  created_at: string;
  updated_at: string;
}

interface ScanResult {
  findings: Array<{
    type: string;
    value: string;
    confidence: number;
    location: string;
  }>;
  policy_id: string | null;
  risk_level: string;
}

const DETECTOR_TYPES = [
  "credit_card",
  "ssn",
  "email",
  "phone",
  "ip_address",
  "api_key",
  "password",
  "pii_name",
  "address",
];

const ACTIONS = ["redact", "mask", "block", "log", "alert"];

function actionBadge(action: string) {
  const colors: Record<string, string> = {
    redact: "bg-purple-500/20 text-purple-400",
    mask: "bg-blue-500/20 text-blue-400",
    block: "bg-red-500/20 text-red-400",
    log: "bg-gray-500/20 text-gray-400",
    alert: "bg-yellow-500/20 text-yellow-400",
  };
  return (
    <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${colors[action] ?? "bg-gray-500/20 text-gray-400"}`}>
      {action}
    </span>
  );
}

function severityColor(confidence: number): string {
  if (confidence >= 0.9) return "bg-red-500/20 text-red-400";
  if (confidence >= 0.7) return "bg-orange-500/20 text-orange-400";
  return "bg-yellow-500/20 text-yellow-400";
}

export function DLPPage() {
  const [policies, setPolicies] = useState<DLPPolicy[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [scanInput, setScanInput] = useState("");
  const [scanPolicyId, setScanPolicyId] = useState("");
  const [scanResult, setScanResult] = useState<ScanResult | null>(null);
  const [scanning, setScanning] = useState(false);

  const [showCreateForm, setShowCreateForm] = useState(false);
  const [formName, setFormName] = useState("");
  const [formDesc, setFormDesc] = useState("");
  const [formAction, setFormAction] = useState("redact");
  const [formSensitivity, setFormSensitivity] = useState("medium");
  const [formTypes, setFormTypes] = useState<string[]>([]);
  const [formActive, setFormActive] = useState(true);
  const [creating, setCreating] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);

  async function fetchPolicies() {
    setLoading(true);
    setError(null);
    try {
      const res = await apiGet<DLPPolicy[]>("/api/v1/dlp/policies");
      setPolicies(Array.isArray(res.data) ? res.data : []);
    } catch {
      setError("Failed to load DLP policies.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void fetchPolicies(); }, []);

  async function handleScan() {
    if (!scanInput.trim()) return;
    setScanning(true);
    setScanResult(null);
    try {
      const body: Record<string, unknown> = { content: scanInput };
      if (scanPolicyId) body.policy_id = scanPolicyId;
      const res = await apiPost<ScanResult>("/api/v1/dlp/scan", body);
      setScanResult(res.data);
    } catch {
      setError("Scan failed.");
    } finally {
      setScanning(false);
    }
  }

  async function handleCreatePolicy() {
    if (!formName.trim() || formTypes.length === 0) return;
    setCreating(true);
    try {
      await apiPost("/api/v1/dlp/policies", {
        name: formName,
        description: formDesc || null,
        is_active: formActive,
        detector_types: formTypes,
        custom_patterns: {},
        action: formAction,
        sensitivity: formSensitivity,
      });
      setShowCreateForm(false);
      setFormName(""); setFormDesc(""); setFormAction("redact"); setFormTypes([]); setFormActive(true);
      await fetchPolicies();
    } catch {
      setError("Failed to create policy.");
    } finally {
      setCreating(false);
    }
  }

  async function handleDelete(id: string) {
    setDeleting(id);
    try {
      await apiDelete(`/api/v1/dlp/policies/${id}`);
      await fetchPolicies();
    } catch {
      setError("Failed to delete policy.");
    } finally {
      setDeleting(null);
    }
  }

  function toggleEntityType(t: string) {
    setFormTypes((prev) => prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t]);
  }

  const activeCount = policies.filter((p) => p.is_active).length;
  const totalDetectors = new Set(policies.flatMap((p) => p.detector_types ?? [])).size;

  if (loading) {
    return <div className="flex h-64 items-center justify-center"><p className="text-gray-400">Loading...</p></div>;
  }

  return (
    <div className="p-6">
      {error && (
        <div className="mb-4 rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">{error}</div>
      )}

      <div className="mb-4 flex items-center gap-3">
        <ShieldAlert size={24} className="text-purple-400" />
        <h1 className="text-2xl font-bold text-white">Data Loss Prevention</h1>
      </div>
      <p className="mb-6 text-gray-400">
        Detect and protect sensitive data in agent interactions with real-time scanning and policy enforcement.
      </p>

      {/* Stats */}
      <div className="mb-8 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {[
          { label: "Active Policies", value: String(activeCount), icon: <Shield size={20} /> },
          { label: "Total Policies", value: String(policies.length), icon: <ShieldAlert size={20} /> },
          { label: "Detector Types", value: String(totalDetectors), icon: <Search size={20} /> },
          { label: "Scan Available", value: "Ready", icon: <EyeOff size={20} /> },
        ].map((s) => (
          <div key={s.label} className="rounded-lg border border-[#2a2d37] bg-[#1a1d27] p-4">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-sm text-gray-400">{s.label}</span>
              <span className="text-purple-400">{s.icon}</span>
            </div>
            <p className="text-2xl font-bold text-white">{s.value}</p>
          </div>
        ))}
      </div>

      {/* Live Scanner */}
      <div className="mb-8 rounded-lg border border-[#2a2d37] bg-[#1a1d27]">
        <div className="border-b border-[#2a2d37] px-4 py-3">
          <h2 className="text-sm font-semibold text-white">Live Scanner</h2>
        </div>
        <div className="p-4">
          <textarea
            className="mb-3 w-full rounded-md border border-[#2a2d37] bg-[#0f1117] p-3 text-sm text-gray-200 placeholder-gray-500 focus:border-purple-500 focus:outline-none"
            rows={4}
            placeholder="Paste text to scan for sensitive data (e.g., SSNs, credit cards, API keys)..."
            value={scanInput}
            onChange={(e) => setScanInput(e.target.value)}
          />
          <div className="flex items-center gap-2">
            {policies.length > 0 && (
              <select
                className="h-8 rounded-md border border-[#2a2d37] bg-[#0f1117] px-2 text-xs text-white"
                value={scanPolicyId}
                onChange={(e) => setScanPolicyId(e.target.value)}
              >
                <option value="">Any policy</option>
                {policies.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
            )}
            <Button size="sm" onClick={handleScan} disabled={scanning || !scanInput.trim()}>
              {scanning ? <Loader2 size={14} className="mr-1.5 animate-spin" /> : <Search size={14} className="mr-1.5" />}
              Scan
            </Button>
          </div>

          {scanResult && (
            <div className="mt-4 rounded-md border border-[#2a2d37] bg-[#0f1117] p-4">
              <div className="mb-3 flex items-center gap-2">
                {scanResult.findings.length > 0 ? (
                  <AlertTriangle size={16} className="text-orange-400" />
                ) : (
                  <CheckCircle2 size={16} className="text-green-400" />
                )}
                <span className="text-sm font-medium text-white">
                  {scanResult.findings.length > 0
                    ? `${scanResult.findings.length} sensitive entit${scanResult.findings.length === 1 ? "y" : "ies"} detected`
                    : "No sensitive data detected"}
                </span>
              </div>
              {scanResult.findings.length > 0 && (
                <div className="space-y-2">
                  {scanResult.findings.map((entity, i) => (
                    <div key={i} className="flex items-center gap-3 rounded border border-[#2a2d37] bg-white/5 px-3 py-2 text-sm">
                      <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${severityColor(entity.confidence)}`}>
                        {entity.type}
                      </span>
                      <code className="text-gray-400">{entity.value}</code>
                      <span className="ml-auto text-xs text-gray-500">
                        {Math.round(entity.confidence * 100)}% confidence
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Policy Management */}
      <div className="rounded-lg border border-[#2a2d37] bg-[#1a1d27]">
        <div className="flex items-center justify-between border-b border-[#2a2d37] px-4 py-3">
          <h2 className="text-sm font-semibold text-white">DLP Policies</h2>
          <Button size="sm" variant="secondary" onClick={() => setShowCreateForm(!showCreateForm)}>
            {showCreateForm ? <X size={14} className="mr-1.5" /> : <Plus size={14} className="mr-1.5" />}
            {showCreateForm ? "Cancel" : "Create Policy"}
          </Button>
        </div>

        {showCreateForm && (
          <div className="border-b border-[#2a2d37] bg-[#0f1117] p-4">
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <div>
                <label className="mb-1 block text-xs text-gray-400">Name *</label>
                <input className="w-full rounded-md border border-[#2a2d37] bg-white/5 px-3 py-1.5 text-sm text-gray-200 focus:border-purple-500 focus:outline-none" value={formName} onChange={(e) => setFormName(e.target.value)} placeholder="Policy name" />
              </div>
              <div>
                <label className="mb-1 block text-xs text-gray-400">Action</label>
                <select className="w-full rounded-md border border-[#2a2d37] bg-white/5 px-3 py-1.5 text-sm text-gray-200 focus:border-purple-500 focus:outline-none" value={formAction} onChange={(e) => setFormAction(e.target.value)}>
                  {ACTIONS.map((a) => <option key={a} value={a}>{a.charAt(0).toUpperCase() + a.slice(1)}</option>)}
                </select>
              </div>
              <div className="md:col-span-2">
                <label className="mb-1 block text-xs text-gray-400">Description</label>
                <input className="w-full rounded-md border border-[#2a2d37] bg-white/5 px-3 py-1.5 text-sm text-gray-200 focus:border-purple-500 focus:outline-none" value={formDesc} onChange={(e) => setFormDesc(e.target.value)} placeholder="Optional description" />
              </div>
              <div className="md:col-span-2">
                <label className="mb-1 block text-xs text-gray-400">Detector Types</label>
                <div className="flex flex-wrap gap-2">
                  {DETECTOR_TYPES.map((t) => (
                    <button key={t} type="button" onClick={() => toggleEntityType(t)} className={`rounded-full border px-3 py-1 text-xs transition-colors ${formTypes.includes(t) ? "border-purple-500 bg-purple-500/20 text-purple-300" : "border-[#2a2d37] bg-white/5 text-gray-400 hover:border-white/20"}`}>
                      {t}
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <label className="mb-1 block text-xs text-gray-400">Sensitivity</label>
                <select className="w-full rounded-md border border-[#2a2d37] bg-white/5 px-3 py-1.5 text-sm text-gray-200 focus:border-purple-500 focus:outline-none" value={formSensitivity} onChange={(e) => setFormSensitivity(e.target.value)}>
                  <option value="low">Low</option>
                  <option value="medium">Medium</option>
                  <option value="high">High</option>
                </select>
              </div>
              <div className="flex items-center gap-3">
                <label className="flex items-center gap-2 text-sm text-gray-300">
                  <input type="checkbox" checked={formActive} onChange={(e) => setFormActive(e.target.checked)} className="rounded border-[#2a2d37]" />
                  Active
                </label>
                <Button size="sm" onClick={handleCreatePolicy} disabled={creating || !formName.trim() || formTypes.length === 0}>
                  {creating ? <Loader2 size={14} className="mr-1.5 animate-spin" /> : null}
                  Save Policy
                </Button>
              </div>
            </div>
          </div>
        )}

        {policies.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12">
            <ShieldAlert size={32} className="mb-2 text-gray-600" />
            <p className="text-sm text-gray-500">No DLP policies configured yet.</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[#2a2d37] text-left text-xs text-gray-500">
                  <th className="px-4 py-2 font-medium">Name</th>
                  <th className="px-4 py-2 font-medium">Status</th>
                  <th className="px-4 py-2 font-medium">Action</th>
                  <th className="px-4 py-2 font-medium">Detectors</th>
                  <th className="px-4 py-2 font-medium">Created</th>
                  <th className="px-4 py-2 font-medium text-right">Delete</th>
                </tr>
              </thead>
              <tbody>
                {policies.map((p) => (
                  <tr key={p.id} className="border-b border-[#2a2d37] hover:bg-white/5">
                    <td className="px-4 py-2">
                      <div className="font-medium text-white">{p.name}</div>
                      {p.description && <div className="text-xs text-gray-500">{p.description}</div>}
                    </td>
                    <td className="px-4 py-2">
                      <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${p.is_active ? "bg-green-500/20 text-green-400" : "bg-gray-500/20 text-gray-400"}`}>
                        {p.is_active ? "Active" : "Inactive"}
                      </span>
                    </td>
                    <td className="px-4 py-2">{actionBadge(p.action)}</td>
                    <td className="px-4 py-2">
                      <div className="flex flex-wrap gap-1">
                        {(p.detector_types ?? []).slice(0, 3).map((t) => (
                          <span key={t} className="inline-block rounded bg-white/10 px-1.5 py-0.5 text-xs text-gray-400">{t}</span>
                        ))}
                        {(p.detector_types ?? []).length > 3 && (
                          <span className="text-xs text-gray-500">+{p.detector_types.length - 3}</span>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-2 text-gray-400">
                      {new Date(p.created_at).toLocaleDateString()}
                    </td>
                    <td className="px-4 py-2 text-right">
                      <Button variant="ghost" size="sm" onClick={() => handleDelete(p.id)} disabled={deleting === p.id}>
                        {deleting === p.id ? <Loader2 size={12} className="animate-spin" /> : <Trash2 size={12} className="text-red-400" />}
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
