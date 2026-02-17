import { useState, useEffect } from "react";
import { Scale, Plus, ShieldCheck, CheckCircle, XCircle, Loader2, ClipboardList } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { apiGet, apiPost } from "@/api/client";

interface RegisteredAgent {
  id: string;
  agent_id: string;
  owner: string;
  department: string;
  approval_status: string;
  models_used: string[];
  data_accessed: string[];
  risk_level: string;
  created_at: string;
}

interface GovernancePolicy {
  id: string;
  name: string;
  description: string | null;
  rules: string;
  severity: string;
  is_active: boolean;
  created_at: string;
}

interface AuditEntry {
  id: string;
  action: string;
  actor: string;
  resource_type: string;
  details: Record<string, unknown>;
  created_at: string;
}

function riskBadge(level: string) {
  const cls: Record<string, string> = { high: "bg-red-500/20 text-red-400", medium: "bg-yellow-500/20 text-yellow-400", low: "bg-green-500/20 text-green-400" };
  return <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${cls[level] ?? "bg-gray-500/20 text-gray-400"}`}>{level}</span>;
}

function approvalBadge(status: string) {
  const cls: Record<string, string> = { approved: "bg-green-500/20 text-green-400", pending: "bg-yellow-500/20 text-yellow-400", rejected: "bg-red-500/20 text-red-400" };
  return <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${cls[status] ?? "bg-gray-500/20 text-gray-400"}`}>{status}</span>;
}

function severityBadge(severity: string) {
  const cls: Record<string, string> = { critical: "bg-red-500/20 text-red-400", high: "bg-orange-500/20 text-orange-400", medium: "bg-yellow-500/20 text-yellow-400", low: "bg-blue-500/20 text-blue-400" };
  return <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${cls[severity] ?? "bg-gray-500/20 text-gray-400"}`}>{severity}</span>;
}

export function GovernancePage() {
  const [agents, setAgents] = useState<RegisteredAgent[]>([]);
  const [policies, setPolicies] = useState<GovernancePolicy[]>([]);
  const [auditTrail, setAuditTrail] = useState<AuditEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Agent registration form
  const [showAgentForm, setShowAgentForm] = useState(false);
  const [agentId, setAgentId] = useState("");
  const [agentOwner, setAgentOwner] = useState("");
  const [agentDept, setAgentDept] = useState("");
  const [agentRisk, setAgentRisk] = useState("low");
  const [creatingAgent, setCreatingAgent] = useState(false);

  // Policy form
  const [showPolicyForm, setShowPolicyForm] = useState(false);
  const [policyName, setPolicyName] = useState("");
  const [policyDesc, setPolicyDesc] = useState("");
  const [policyRules, setPolicyRules] = useState("");
  const [policySeverity, setPolicySeverity] = useState("medium");
  const [creatingPolicy, setCreatingPolicy] = useState(false);

  async function fetchAll() {
    setLoading(true);
    setError(null);
    try {
      const [agentsRes, policiesRes, auditRes] = await Promise.allSettled([
        apiGet<RegisteredAgent[]>("/governance/agents"),
        apiGet<GovernancePolicy[]>("/governance/policies"),
        apiGet<AuditEntry[]>("/governance/audit"),
      ]);
      if (agentsRes.status === "fulfilled") setAgents(Array.isArray(agentsRes.value.data) ? agentsRes.value.data : []);
      if (policiesRes.status === "fulfilled") setPolicies(Array.isArray(policiesRes.value.data) ? policiesRes.value.data : []);
      if (auditRes.status === "fulfilled") setAuditTrail(Array.isArray(auditRes.value.data) ? auditRes.value.data : []);
    } catch {
      setError("Failed to load governance data.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void fetchAll(); }, []);

  async function handleRegisterAgent() {
    if (!agentId.trim() || !agentOwner.trim()) return;
    setCreatingAgent(true);
    try {
      await apiPost("/governance/agents", {
        agent_id: agentId,
        owner: agentOwner,
        department: agentDept || "unassigned",
        approval_status: "pending",
        models_used: [],
        data_accessed: [],
        risk_level: agentRisk,
      });
      setShowAgentForm(false);
      setAgentId(""); setAgentOwner(""); setAgentDept("");
      await fetchAll();
    } catch {
      setError("Failed to register agent.");
    } finally {
      setCreatingAgent(false);
    }
  }

  async function handleCreatePolicy() {
    if (!policyName.trim() || !policyRules.trim()) return;
    setCreatingPolicy(true);
    try {
      await apiPost("/governance/policies", {
        name: policyName,
        description: policyDesc || null,
        rules: policyRules,
        severity: policySeverity,
        is_active: true,
      });
      setShowPolicyForm(false);
      setPolicyName(""); setPolicyDesc(""); setPolicyRules("");
      await fetchAll();
    } catch {
      setError("Failed to create policy.");
    } finally {
      setCreatingPolicy(false);
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

      <div className="mb-4 flex items-center gap-3">
        <Scale size={24} className="text-purple-400" />
        <h1 className="text-2xl font-bold text-white">Governance</h1>
      </div>
      <p className="mb-6 text-gray-400">Agent registry, compliance policies, and audit trail.</p>

      {/* Agent Registry */}
      <div className="mb-6 rounded-lg border border-[#2a2d37] bg-[#1a1d27]">
        <div className="flex items-center justify-between border-b border-[#2a2d37] px-4 py-3">
          <h2 className="text-sm font-semibold text-white">Agent Registry ({agents.length})</h2>
          <Button size="sm" variant="secondary" onClick={() => setShowAgentForm(!showAgentForm)}>
            <Plus size={14} className="mr-1.5" />Register Agent
          </Button>
        </div>

        {showAgentForm && (
          <div className="border-b border-[#2a2d37] bg-[#0f1117] p-4">
            <div className="flex flex-wrap gap-3">
              <Input placeholder="Agent ID *" value={agentId} onChange={(e) => setAgentId(e.target.value)} className="max-w-xs" />
              <Input placeholder="Owner *" value={agentOwner} onChange={(e) => setAgentOwner(e.target.value)} className="max-w-xs" />
              <Input placeholder="Department" value={agentDept} onChange={(e) => setAgentDept(e.target.value)} className="max-w-[160px]" />
              <select value={agentRisk} onChange={(e) => setAgentRisk(e.target.value)} className="h-9 rounded-md border border-[#2a2d37] bg-[#0f1117] px-3 text-sm text-white">
                <option value="low">Low Risk</option>
                <option value="medium">Medium Risk</option>
                <option value="high">High Risk</option>
              </select>
              <Button size="sm" onClick={handleRegisterAgent} disabled={creatingAgent || !agentId.trim() || !agentOwner.trim()}>
                {creatingAgent && <Loader2 size={14} className="mr-1.5 animate-spin" />}
                Register
              </Button>
            </div>
          </div>
        )}

        {agents.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12">
            <ShieldCheck size={32} className="mb-2 text-gray-600" />
            <p className="text-sm text-gray-500">No agents registered yet.</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead><tr className="border-b border-[#2a2d37] text-left text-xs text-gray-500">
                <th className="px-4 py-2 font-medium">Agent ID</th>
                <th className="px-4 py-2 font-medium">Owner</th>
                <th className="px-4 py-2 font-medium">Department</th>
                <th className="px-4 py-2 font-medium">Approval</th>
                <th className="px-4 py-2 font-medium">Risk</th>
                <th className="px-4 py-2 font-medium text-right">Registered</th>
              </tr></thead>
              <tbody>{agents.map((a) => (
                <tr key={a.id} className="border-b border-[#2a2d37] hover:bg-white/5">
                  <td className="px-4 py-2 font-medium text-white">{a.agent_id}</td>
                  <td className="px-4 py-2 text-gray-400">{a.owner}</td>
                  <td className="px-4 py-2 text-gray-400">{a.department}</td>
                  <td className="px-4 py-2">{approvalBadge(a.approval_status)}</td>
                  <td className="px-4 py-2">{riskBadge(a.risk_level)}</td>
                  <td className="px-4 py-2 text-right text-gray-400">{new Date(a.created_at).toLocaleDateString()}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </div>

      {/* Compliance Policies */}
      <div className="mb-6 rounded-lg border border-[#2a2d37] bg-[#1a1d27]">
        <div className="flex items-center justify-between border-b border-[#2a2d37] px-4 py-3">
          <h2 className="text-sm font-semibold text-white">Compliance Policies ({policies.length})</h2>
          <Button size="sm" variant="secondary" onClick={() => setShowPolicyForm(!showPolicyForm)}>
            <Plus size={14} className="mr-1.5" />Create Policy
          </Button>
        </div>

        {showPolicyForm && (
          <div className="border-b border-[#2a2d37] bg-[#0f1117] p-4">
            <div className="flex flex-wrap gap-3">
              <Input placeholder="Policy name *" value={policyName} onChange={(e) => setPolicyName(e.target.value)} className="max-w-xs" />
              <Input placeholder="Description" value={policyDesc} onChange={(e) => setPolicyDesc(e.target.value)} className="max-w-xs" />
              <Input placeholder="Rules *" value={policyRules} onChange={(e) => setPolicyRules(e.target.value)} className="max-w-xs" />
              <select value={policySeverity} onChange={(e) => setPolicySeverity(e.target.value)} className="h-9 rounded-md border border-[#2a2d37] bg-[#0f1117] px-3 text-sm text-white">
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
                <option value="critical">Critical</option>
              </select>
              <Button size="sm" onClick={handleCreatePolicy} disabled={creatingPolicy || !policyName.trim() || !policyRules.trim()}>
                {creatingPolicy && <Loader2 size={14} className="mr-1.5 animate-spin" />}
                Save
              </Button>
            </div>
          </div>
        )}

        {policies.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12">
            <p className="text-sm text-gray-500">No compliance policies defined yet.</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead><tr className="border-b border-[#2a2d37] text-left text-xs text-gray-500">
                <th className="px-4 py-2 font-medium">Name</th>
                <th className="px-4 py-2 font-medium">Severity</th>
                <th className="px-4 py-2 font-medium">Active</th>
                <th className="px-4 py-2 font-medium text-right">Created</th>
              </tr></thead>
              <tbody>{policies.map((p) => (
                <tr key={p.id} className="border-b border-[#2a2d37] hover:bg-white/5">
                  <td className="px-4 py-2">
                    <div className="font-medium text-white">{p.name}</div>
                    {p.description && <div className="text-xs text-gray-500">{p.description}</div>}
                  </td>
                  <td className="px-4 py-2">{severityBadge(p.severity)}</td>
                  <td className="px-4 py-2">{p.is_active ? <CheckCircle size={14} className="text-green-400" /> : <XCircle size={14} className="text-gray-500" />}</td>
                  <td className="px-4 py-2 text-right text-gray-400">{new Date(p.created_at).toLocaleDateString()}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </div>

      {/* Audit Trail */}
      <div className="rounded-lg border border-[#2a2d37] bg-[#1a1d27]">
        <div className="border-b border-[#2a2d37] px-4 py-3">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-white">
            <ClipboardList size={14} />Audit Trail (recent)
          </h2>
        </div>
        {auditTrail.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12">
            <p className="text-sm text-gray-500">No audit entries yet.</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead><tr className="border-b border-[#2a2d37] text-left text-xs text-gray-500">
                <th className="px-4 py-2 font-medium">Timestamp</th>
                <th className="px-4 py-2 font-medium">Action</th>
                <th className="px-4 py-2 font-medium">Actor</th>
                <th className="px-4 py-2 font-medium">Resource</th>
              </tr></thead>
              <tbody>{auditTrail.slice(0, 10).map((e) => (
                <tr key={e.id} className="border-b border-[#2a2d37] hover:bg-white/5">
                  <td className="px-4 py-2 text-gray-400">{new Date(e.created_at).toLocaleString()}</td>
                  <td className="px-4 py-2"><code className="rounded bg-white/10 px-1.5 py-0.5 text-xs">{e.action}</code></td>
                  <td className="px-4 py-2 font-medium text-white">{e.actor}</td>
                  <td className="px-4 py-2 text-gray-400">{e.resource_type}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
