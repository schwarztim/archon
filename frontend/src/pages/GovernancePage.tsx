import { useState, useEffect } from "react";
import { Scale, ClipboardList, Loader2 } from "lucide-react";
import { apiGet } from "@/api/client";
import { RegistryDashboard } from "@/components/governance/RegistryDashboard";
import { PolicyGallery } from "@/components/governance/PolicyGallery";
import { PolicyDetail } from "@/components/governance/PolicyDetail";
import { ApprovalQueue } from "@/components/governance/ApprovalQueue";

interface AuditEntry {
  id: string;
  action: string;
  actor_id: string | null;
  resource_type: string;
  resource_id: string | null;
  outcome: string;
  details: Record<string, unknown> | null;
  created_at: string;
}

const TABS = ["Registry", "Policies", "Approvals", "Audit Trail"] as const;
type Tab = (typeof TABS)[number];

export function GovernancePage() {
  const [activeTab, setActiveTab] = useState<Tab>("Registry");
  const [auditTrail, setAuditTrail] = useState<AuditEntry[]>([]);
  const [auditLoading, setAuditLoading] = useState(false);
  const [auditFilter, setAuditFilter] = useState({ action: "", resource_type: "" });
  const [policyRefreshKey, setPolicyRefreshKey] = useState(0);
  const [approvalRefreshKey] = useState(0);

  async function fetchAuditTrail() {
    setAuditLoading(true);
    try {
      const params: Record<string, string> = {};
      if (auditFilter.action) params.action = auditFilter.action;
      if (auditFilter.resource_type) params.resource_type = auditFilter.resource_type;
      const res = await apiGet<AuditEntry[]>("/audit-logs/", { ...params, limit: 50 });
      setAuditTrail(Array.isArray(res.data) ? res.data : []);
    } catch {
      setAuditTrail([]);
    } finally {
      setAuditLoading(false);
    }
  }

  useEffect(() => {
    if (activeTab === "Audit Trail") void fetchAuditTrail();
  }, [activeTab, auditFilter.action, auditFilter.resource_type]);

  return (
    <div className="p-6">
      {/* Header */}
      <div className="mb-4 flex items-center gap-3">
        <Scale size={24} className="text-purple-400" />
        <h1 className="text-2xl font-bold text-white">Governance & Registry</h1>
      </div>
      <p className="mb-6 text-gray-400">Agent registry, compliance policies, approval workflows, and audit trail.</p>

      {/* Tab bar */}
      <div className="mb-6 flex gap-1 rounded-lg border border-[#2a2d37] bg-[#0f1117] p-1">
        {TABS.map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`rounded-md px-4 py-2 text-sm font-medium transition-colors ${
              activeTab === tab
                ? "bg-purple-500/20 text-purple-400"
                : "text-gray-400 hover:text-white"
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {activeTab === "Registry" && <RegistryDashboard />}

      {activeTab === "Policies" && (
        <div className="space-y-4">
          <PolicyGallery onPolicyCreated={() => setPolicyRefreshKey((k) => k + 1)} />
          <PolicyDetail refreshKey={policyRefreshKey} />
        </div>
      )}

      {activeTab === "Approvals" && <ApprovalQueue refreshKey={approvalRefreshKey} />}

      {activeTab === "Audit Trail" && (
        <div className="rounded-lg border border-[#2a2d37] bg-[#1a1d27]">
          <div className="flex items-center justify-between border-b border-[#2a2d37] px-4 py-3">
            <h2 className="flex items-center gap-2 text-sm font-semibold text-white">
              <ClipboardList size={14} /> Audit Trail
            </h2>
            <div className="flex gap-2">
              <select
                value={auditFilter.action}
                onChange={(e) => setAuditFilter((f) => ({ ...f, action: e.target.value }))}
                className="h-8 rounded-md border border-[#2a2d37] bg-[#0f1117] px-2 text-xs text-white"
              >
                <option value="">All Actions</option>
                <option value="compliance_scan.executed">Compliance Scan</option>
                <option value="approval.created">Approval Created</option>
                <option value="approval.approved">Approval Approved</option>
                <option value="approval.rejected">Approval Rejected</option>
              </select>
              <select
                value={auditFilter.resource_type}
                onChange={(e) => setAuditFilter((f) => ({ ...f, resource_type: e.target.value }))}
                className="h-8 rounded-md border border-[#2a2d37] bg-[#0f1117] px-2 text-xs text-white"
              >
                <option value="">All Resources</option>
                <option value="agent">Agent</option>
                <option value="approval_request">Approval</option>
                <option value="compliance_policy">Policy</option>
              </select>
            </div>
          </div>

          {auditLoading ? (
            <div className="flex h-24 items-center justify-center">
              <Loader2 size={20} className="animate-spin text-gray-500" />
            </div>
          ) : auditTrail.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12">
              <ClipboardList size={32} className="mb-2 text-gray-600" />
              <p className="text-sm text-gray-500">No audit entries found.</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-[#2a2d37] text-left text-xs text-gray-500">
                    <th className="px-4 py-2 font-medium">Timestamp</th>
                    <th className="px-4 py-2 font-medium">Action</th>
                    <th className="px-4 py-2 font-medium">Resource</th>
                    <th className="px-4 py-2 font-medium">Outcome</th>
                    <th className="px-4 py-2 font-medium">Details</th>
                  </tr>
                </thead>
                <tbody>
                  {auditTrail.map((e) => (
                    <tr key={e.id} className="border-b border-[#2a2d37] hover:bg-white/5">
                      <td className="px-4 py-2 text-gray-400">
                        {new Date(e.created_at).toLocaleString()}
                      </td>
                      <td className="px-4 py-2">
                        <code className="rounded bg-white/10 px-1.5 py-0.5 text-xs">{e.action}</code>
                      </td>
                      <td className="px-4 py-2 text-gray-400">{e.resource_type}</td>
                      <td className="px-4 py-2">
                        <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                          e.outcome === "success" ? "bg-green-500/20 text-green-400" : "bg-red-500/20 text-red-400"
                        }`}>
                          {e.outcome}
                        </span>
                      </td>
                      <td className="max-w-xs truncate px-4 py-2 text-xs text-gray-500">
                        {e.details ? JSON.stringify(e.details) : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
