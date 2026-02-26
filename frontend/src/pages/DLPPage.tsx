import { useState } from "react";
import type { ReactNode } from "react";
import {
  ShieldAlert,
  Search,
  Plus,
  Loader2,
  Shield,
  X,
  Trash2,
  LayoutDashboard,
  List,
  FlaskConical,
} from "lucide-react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/Button";
import { apiPost, apiDelete } from "@/api/client";
import { listPolicies, listDetectorTypes } from "@/api/dlp";
import { DetectorPicker, FALLBACK_DETECTORS } from "@/components/dlp/DetectorPicker";
import { PolicyTestPanel } from "@/components/dlp/PolicyTestPanel";
import { MetricsDashboard } from "@/components/dlp/MetricsDashboard";
import { DetectionsList } from "@/components/dlp/DetectionsList";
import { CustomRegexForm } from "@/components/dlp/CustomRegexForm";
import type { DetectorInfo } from "@/components/dlp/DetectorPicker";

interface DLPPolicy {
  id: string;
  name: string;
  description: string | null;
  is_active: boolean;
  detector_types: string[];
  custom_patterns: Record<string, string>;
  action: string;
  sensitivity: string;
  created_at: string;
  updated_at: string;
}

type TabId = "dashboard" | "policies" | "test" | "detections";

const TABS: Array<{ id: TabId; label: string; icon: ReactNode }> = [
  { id: "dashboard", label: "Dashboard", icon: <LayoutDashboard size={14} /> },
  { id: "policies", label: "Policies", icon: <Shield size={14} /> },
  { id: "test", label: "Test Scanner", icon: <FlaskConical size={14} /> },
  { id: "detections", label: "Detections", icon: <List size={14} /> },
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

export function DLPPage() {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState<TabId>("dashboard");

  const [showCreateForm, setShowCreateForm] = useState(false);
  const [formName, setFormName] = useState("");
  const [formDesc, setFormDesc] = useState("");
  const [formAction, setFormAction] = useState("redact");
  const [formSensitivity, setFormSensitivity] = useState("medium");
  const [formTypes, setFormTypes] = useState<string[]>([]);
  const [formActive, setFormActive] = useState(true);
  const [formCustomPatterns, setFormCustomPatterns] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);

  // ── Queries ──────────────────────────────────────────────────────────
  const { data: policiesData, isLoading } = useQuery({
    queryKey: ["dlp-policies"],
    queryFn: () => listPolicies(),
  });
  const policies: DLPPolicy[] = Array.isArray(policiesData?.data) ? (policiesData.data as unknown as DLPPolicy[]) : [];

  const { data: detectorsData } = useQuery({
    queryKey: ["dlp-detectors"],
    queryFn: () => listDetectorTypes(),
    retry: false,
  });
  const detectorTypes: DetectorInfo[] =
    Array.isArray(detectorsData?.data) && detectorsData.data.length > 0
      ? (detectorsData.data as DetectorInfo[])
      : FALLBACK_DETECTORS;

  // ── Mutations ────────────────────────────────────────────────────────
  const createMutation = useMutation({
    mutationFn: (payload: Record<string, unknown>) =>
      apiPost("/api/v1/dlp/policies/create", payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["dlp-policies"] });
      setShowCreateForm(false);
      setFormName(""); setFormDesc(""); setFormAction("redact"); setFormTypes([]);
      setFormActive(true); setFormCustomPatterns({});
    },
    onError: () => setError("Failed to create policy."),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => apiDelete(`/api/v1/dlp/policies/${id}`),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["dlp-policies"] }),
    onError: () => setError("Failed to delete policy."),
  });

  function handleCreatePolicy() {
    if (!formName.trim() || formTypes.length === 0) return;
    createMutation.mutate({
      name: formName,
      description: formDesc || null,
      is_active: formActive,
      detector_types: formTypes,
      custom_patterns: formCustomPatterns,
      action: formAction,
      sensitivity: formSensitivity,
    } as Record<string, unknown>);
  }

  function handleAddCustomPattern(name: string, pattern: string) {
    setFormCustomPatterns((prev) => ({ ...prev, [name]: pattern }));
  }

  const activeCount = policies.filter((p) => p.is_active).length;

  if (isLoading) {
    return <div className="flex h-64 items-center justify-center"><Loader2 size={24} className="animate-spin text-gray-500" /></div>;
  }

  return (
    <div className="p-6">
      {error && (
        <div className="mb-4 flex items-center justify-between rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">
          <span>{error}</span>
          <button onClick={() => setError(null)}><X size={14} /></button>
        </div>
      )}

      {/* Header */}
      <div className="mb-4 flex items-center gap-3">
        <ShieldAlert size={24} className="text-purple-400" />
        <h1 className="text-2xl font-bold text-white">Data Loss Prevention</h1>
      </div>
      <p className="mb-6 text-gray-400">
        Detect and protect sensitive data in agent interactions with real-time scanning, policy enforcement, and configurable guardrails.
      </p>

      {/* Tab Navigation */}
      <div className="mb-6 flex gap-1 rounded-lg border border-[#2a2d37] bg-[#0f1117] p-1">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`flex items-center gap-1.5 rounded-md px-4 py-2 text-sm font-medium transition-colors ${
              activeTab === tab.id
                ? "bg-purple-500/20 text-purple-400"
                : "text-gray-400 hover:text-white hover:bg-white/5"
            }`}
          >
            {tab.icon}
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      {activeTab === "dashboard" && <MetricsDashboard />}

      {activeTab === "test" && (
        <PolicyTestPanel
          policies={policies.map((p) => ({ id: p.id, name: p.name }))}
        />
      )}

      {activeTab === "detections" && <DetectionsList />}

      {activeTab === "policies" && (
        <div className="space-y-6">
          {/* Policy summary cards */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <div className="rounded-lg border border-[#2a2d37] bg-[#1a1d27] p-4">
              <div className="mb-1 flex items-center gap-2">
                <Shield size={16} className="text-green-400" />
                <span className="text-sm text-gray-400">Active Policies</span>
              </div>
              <p className="text-2xl font-bold text-white">{activeCount}</p>
            </div>
            <div className="rounded-lg border border-[#2a2d37] bg-[#1a1d27] p-4">
              <div className="mb-1 flex items-center gap-2">
                <ShieldAlert size={16} className="text-yellow-400" />
                <span className="text-sm text-gray-400">Total Policies</span>
              </div>
              <p className="text-2xl font-bold text-white">{policies.length}</p>
            </div>
            <div className="rounded-lg border border-[#2a2d37] bg-[#1a1d27] p-4">
              <div className="mb-1 flex items-center gap-2">
                <Search size={16} className="text-blue-400" />
                <span className="text-sm text-gray-400">Detector Types in Use</span>
              </div>
              <p className="text-2xl font-bold text-white">
                {new Set(policies.flatMap((p) => p.detector_types ?? [])).size}
              </p>
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
                    <label className="mb-2 block text-xs text-gray-400">Detector Types *</label>
                    <DetectorPicker
                      selected={formTypes}
                      onChange={setFormTypes}
                      detectors={detectorTypes}
                    />
                  </div>
                  <div className="md:col-span-2">
                    <CustomRegexForm
                      onAdd={handleAddCustomPattern}
                      existingPatterns={formCustomPatterns}
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-xs text-gray-400">Sensitivity</label>
                    <select className="w-full rounded-md border border-[#2a2d37] bg-white/5 px-3 py-1.5 text-sm text-gray-200 focus:border-purple-500 focus:outline-none" value={formSensitivity} onChange={(e) => setFormSensitivity(e.target.value)}>
                      <option value="low">Low</option>
                      <option value="medium">Medium</option>
                      <option value="high">High</option>
                      <option value="critical">Critical</option>
                    </select>
                  </div>
                  <div className="flex items-center gap-3">
                    <label className="flex items-center gap-2 text-sm text-gray-300">
                      <input type="checkbox" checked={formActive} onChange={(e) => setFormActive(e.target.checked)} className="rounded border-[#2a2d37]" />
                      Active
                    </label>
                    <Button size="sm" onClick={handleCreatePolicy} disabled={createMutation.isPending || !formName.trim() || formTypes.length === 0}>
                      {createMutation.isPending ? <Loader2 size={14} className="mr-1.5 animate-spin" /> : null}
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
                      <th className="px-4 py-2 font-medium">Sensitivity</th>
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
                          <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${
                            p.sensitivity === "critical" ? "bg-red-600/20 text-red-300" :
                            p.sensitivity === "high" ? "bg-red-500/20 text-red-400" :
                            p.sensitivity === "medium" ? "bg-yellow-500/20 text-yellow-400" :
                            "bg-green-500/20 text-green-400"
                          }`}>
                            {p.sensitivity}
                          </span>
                        </td>
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
                          <Button variant="ghost" size="sm" onClick={() => deleteMutation.mutate(p.id)} disabled={deleteMutation.isPending && deleteMutation.variables === p.id}>
                            {deleteMutation.isPending && deleteMutation.variables === p.id ? <Loader2 size={12} className="animate-spin" /> : <Trash2 size={12} className="text-red-400" />}
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
      )}
    </div>
  );
}
