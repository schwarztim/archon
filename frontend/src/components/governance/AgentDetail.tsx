import { useState, useEffect } from "react";
import { ArrowLeft, Loader2, ShieldCheck, Clock, CheckCircle, XCircle, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { getRegistryDetail, scanAgent, type AgentDetail as AgentDetailType } from "@/api/governance";

interface Props {
  agentId: string;
  onBack: () => void;
}

function statusIcon(status: string) {
  if (status === "compliant") return <CheckCircle size={14} className="text-green-400" />;
  if (status === "non_compliant") return <XCircle size={14} className="text-red-400" />;
  return <Clock size={14} className="text-yellow-400" />;
}

export function AgentDetail({ agentId, onBack }: Props) {
  const [detail, setDetail] = useState<AgentDetailType | null>(null);
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);

  async function fetchDetail() {
    setLoading(true);
    try {
      const res = await getRegistryDetail(agentId);
      setDetail(res.data);
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void fetchDetail(); }, [agentId]);

  async function handleScan() {
    setScanning(true);
    try {
      await scanAgent(agentId);
      await fetchDetail();
    } catch {
      /* ignore */
    } finally {
      setScanning(false);
    }
  }

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 size={24} className="animate-spin text-gray-500" />
      </div>
    );
  }

  if (!detail) {
    return (
      <div className="rounded-lg border border-surface-border bg-surface-raised p-6">
        <Button size="sm" variant="secondary" onClick={onBack}>
          <ArrowLeft size={14} className="mr-1" /> Back
        </Button>
        <p className="mt-4 text-sm text-gray-400">Agent not found in registry.</p>
      </div>
    );
  }

  const { registry, compliance_history, compliance_score, risk_score, total_scans, passed_scans } = detail;

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="rounded-lg border border-surface-border bg-surface-raised p-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Button size="sm" variant="secondary" onClick={onBack}>
              <ArrowLeft size={14} />
            </Button>
            <div>
              <h2 className="text-lg font-bold text-white">{registry.agent_id}</h2>
              <p className="text-xs text-gray-400">Owner: {registry.owner} · Dept: {registry.department}</p>
            </div>
          </div>
          <Button size="sm" onClick={handleScan} disabled={scanning}>
            {scanning ? <Loader2 size={14} className="mr-1 animate-spin" /> : <RefreshCw size={14} className="mr-1" />}
            Run Scan
          </Button>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        {[
          { label: "Compliance Score", value: `${compliance_score}%`, color: compliance_score >= 80 ? "text-green-400" : compliance_score >= 50 ? "text-yellow-400" : "text-red-400" },
          { label: "Risk Score", value: `${risk_score}/100`, color: risk_score >= 70 ? "text-red-400" : risk_score >= 40 ? "text-yellow-400" : "text-green-400" },
          { label: "Total Scans", value: String(total_scans), color: "text-blue-400" },
          { label: "Passed", value: `${passed_scans}/${total_scans}`, color: "text-green-400" },
        ].map((s) => (
          <div key={s.label} className="rounded-lg border border-surface-border bg-surface-raised p-3">
            <p className="text-xs text-gray-500">{s.label}</p>
            <p className={`mt-1 text-xl font-bold ${s.color}`}>{s.value}</p>
          </div>
        ))}
      </div>

      {/* Compliance History Timeline */}
      <div className="rounded-lg border border-surface-border bg-surface-raised">
        <div className="border-b border-surface-border px-4 py-3">
          <h3 className="flex items-center gap-2 text-sm font-semibold text-white">
            <ShieldCheck size={14} /> Compliance History
          </h3>
        </div>
        {compliance_history.length === 0 ? (
          <div className="py-8 text-center text-sm text-gray-500">No compliance scans recorded.</div>
        ) : (
          <div className="max-h-80 overflow-y-auto">
            <div className="divide-y divide-[#2a2d37]">
              {compliance_history.map((record) => (
                <div key={record.id} className="flex items-center gap-3 px-4 py-3">
                  {statusIcon(record.status ?? "pending")}
                  <div className="flex-1">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-white">
                        {record.status === "compliant" ? "Passed" : record.status === "non_compliant" ? "Failed" : "Pending"}
                      </span>
                      <span className="text-xs text-gray-500">
                        Policy: {record.policy_id}
                      </span>
                    </div>
                    {record.details && (
                      <p className="mt-0.5 text-xs text-gray-500">
                        {typeof record.details === "object"
                          ? (record.details as Record<string, unknown>).policy as string ?? ""
                          : ""}
                      </p>
                    )}
                  </div>
                  <span className="text-xs text-gray-500">
                    {new Date(record.checked_at).toLocaleString()}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
