import { useState, useEffect } from "react";
import { Loader2, CheckCircle, XCircle, Trash2, Edit2 } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { listPolicies, deletePolicy, updatePolicy } from "@/api/governance";
import type { CompliancePolicy } from "@/types/models";

function severityBadge(severity: string) {
  const cls: Record<string, string> = {
    critical: "bg-red-500/20 text-red-400",
    high: "bg-orange-500/20 text-orange-400",
    medium: "bg-yellow-500/20 text-yellow-400",
    low: "bg-blue-500/20 text-blue-400",
  };
  return (
    <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${cls[severity] ?? "bg-gray-500/20 text-gray-400"}`}>
      {severity}
    </span>
  );
}

interface Props {
  refreshKey: number;
}

export function PolicyDetail({ refreshKey }: Props) {
  const [policies, setPolicies] = useState<CompliancePolicy[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  async function fetchPolicies() {
    setLoading(true);
    try {
      const res = await listPolicies({ limit: 100 });
      setPolicies(Array.isArray(res.data) ? res.data : []);
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void fetchPolicies(); }, [refreshKey]);

  async function handleDelete(id: string) {
    try {
      await deletePolicy(id);
      await fetchPolicies();
    } catch {
      /* ignore */
    }
  }

  async function handleToggleActive(id: string, currentActive: boolean) {
    try {
      await updatePolicy(id, { is_active: !currentActive });
      await fetchPolicies();
    } catch {
      /* ignore */
    }
  }

  if (loading) {
    return (
      <div className="flex h-24 items-center justify-center rounded-lg border border-[#2a2d37] bg-[#1a1d27]">
        <Loader2 size={20} className="animate-spin text-gray-500" />
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-[#2a2d37] bg-[#1a1d27]">
      <div className="border-b border-[#2a2d37] px-4 py-3">
        <h2 className="text-sm font-semibold text-white">Compliance Policies ({policies.length})</h2>
      </div>

      {policies.length === 0 ? (
        <div className="py-8 text-center text-sm text-gray-500">
          No policies defined. Use the template gallery above to create one.
        </div>
      ) : (
        <div className="divide-y divide-[#2a2d37]">
          {policies.map((p) => (
            <div key={p.id}>
              <div
                className="flex cursor-pointer items-center justify-between px-4 py-3 hover:bg-white/5"
                onClick={() => setExpandedId(expandedId === p.id ? null : p.id)}
              >
                <div className="flex items-center gap-3">
                  {p.is_active ? (
                    <CheckCircle size={14} className="text-green-400" />
                  ) : (
                    <XCircle size={14} className="text-gray-500" />
                  )}
                  <div>
                    <div className="font-medium text-white">{p.name}</div>
                    {p.description && <div className="text-xs text-gray-500">{p.description}</div>}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {severityBadge(p.enforcement ?? "medium")}
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={(e) => { e.stopPropagation(); void handleToggleActive(p.id, p.is_active); }}
                  >
                    <Edit2 size={12} />
                  </Button>
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={(e) => { e.stopPropagation(); void handleDelete(p.id); }}
                    className="text-red-400 hover:bg-red-500/10"
                  >
                    <Trash2 size={12} />
                  </Button>
                </div>
              </div>

              {expandedId === p.id && (
                <div className="border-t border-[#2a2d37] bg-[#0f1117] px-4 py-3">
                  <div className="text-xs text-gray-400">
                    <p className="mb-1"><strong>Type:</strong> {p.type}</p>
                    <p className="mb-1"><strong>Enforcement:</strong> {p.enforcement}</p>
                    <p className="mb-1"><strong>Created:</strong> {new Date(p.created_at).toLocaleString()}</p>
                    {p.rules && (
                      <div className="mt-2">
                        <strong>Rules:</strong>
                        <pre className="mt-1 max-h-40 overflow-auto rounded bg-black/30 p-2 text-[11px]">
                          {JSON.stringify(p.rules, null, 2)}
                        </pre>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
