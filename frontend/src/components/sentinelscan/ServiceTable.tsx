import { Server } from "lucide-react";
import type { ServiceFinding } from "@/api/sentinelscan";

interface ServiceTableProps {
  services: ServiceFinding[];
  onServiceClick?: (service: ServiceFinding) => void;
  selectedIds?: Set<string>;
  onToggleSelect?: (id: string) => void;
  onSelectAll?: () => void;
}

function riskBadge(level: string) {
  const colors: Record<string, string> = {
    critical: "bg-red-500/20 text-red-400",
    high: "bg-orange-500/20 text-orange-400",
    medium: "bg-yellow-500/20 text-yellow-400",
    low: "bg-green-500/20 text-green-400",
  };
  return (
    <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${colors[level] ?? "bg-gray-500/20 text-gray-400"}`}>
      {level}
    </span>
  );
}

function statusBadge(status: string) {
  const colors: Record<string, string> = {
    Approved: "bg-green-500/20 text-green-400",
    Unapproved: "bg-red-500/20 text-red-400",
    Blocked: "bg-red-500/20 text-red-400",
    Monitoring: "bg-yellow-500/20 text-yellow-400",
    Ignored: "bg-gray-500/20 text-gray-400",
  };
  return (
    <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${colors[status] ?? "bg-gray-500/20 text-gray-400"}`}>
      {status}
    </span>
  );
}

function typeBadge(type: string) {
  const colors: Record<string, string> = {
    LLM: "bg-purple-500/20 text-purple-400",
    Embedding: "bg-blue-500/20 text-blue-400",
    Image: "bg-pink-500/20 text-pink-400",
    Voice: "bg-teal-500/20 text-teal-400",
    Code: "bg-indigo-500/20 text-indigo-400",
  };
  return (
    <span className={`inline-block rounded bg-white/10 px-1.5 py-0.5 text-xs ${colors[type] ?? "text-gray-400"}`}>
      {type}
    </span>
  );
}

export function ServiceTable({ services, onServiceClick, selectedIds, onToggleSelect, onSelectAll }: ServiceTableProps) {
  if (services.length === 0) {
    return (
      <div className="rounded-lg border border-[#2a2d37] bg-[#1a1d27]">
        <div className="border-b border-[#2a2d37] px-4 py-3">
          <h2 className="text-sm font-semibold text-white">Service Inventory (0)</h2>
        </div>
        <div className="flex flex-col items-center justify-center py-12">
          <Server size={32} className="mb-2 text-gray-600" />
          <p className="text-sm text-gray-500">No services discovered yet. Run a scan to get started.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-[#2a2d37] bg-[#1a1d27]">
      <div className="border-b border-[#2a2d37] px-4 py-3">
        <h2 className="text-sm font-semibold text-white">Service Inventory ({services.length})</h2>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[#2a2d37] text-left text-xs text-gray-500">
              {onToggleSelect && (
                <th className="px-3 py-2 font-medium w-8">
                  <input
                    type="checkbox"
                    className="rounded border-gray-600"
                    onChange={onSelectAll}
                    checked={selectedIds?.size === services.length && services.length > 0}
                  />
                </th>
              )}
              <th className="px-4 py-2 font-medium">Service Name</th>
              <th className="px-4 py-2 font-medium">Type</th>
              <th className="px-4 py-2 font-medium">Risk Level</th>
              <th className="px-4 py-2 font-medium">Users</th>
              <th className="px-4 py-2 font-medium">Data Exposure</th>
              <th className="px-4 py-2 font-medium">First Seen</th>
              <th className="px-4 py-2 font-medium">Last Seen</th>
              <th className="px-4 py-2 font-medium">Status</th>
            </tr>
          </thead>
          <tbody>
            {services.map((svc) => (
              <tr
                key={svc.id}
                className="border-b border-[#2a2d37] hover:bg-white/5 cursor-pointer"
                onClick={() => onServiceClick?.(svc)}
              >
                {onToggleSelect && (
                  <td className="px-3 py-2" onClick={(e) => e.stopPropagation()}>
                    <input
                      type="checkbox"
                      className="rounded border-gray-600"
                      checked={selectedIds?.has(svc.id) ?? false}
                      onChange={() => onToggleSelect(svc.id)}
                    />
                  </td>
                )}
                <td className="px-4 py-2">
                  <div className="flex items-center gap-2">
                    <Server size={14} className="text-gray-500" />
                    <span className="font-medium text-white">{svc.service_name}</span>
                  </div>
                </td>
                <td className="px-4 py-2">{typeBadge(svc.service_type)}</td>
                <td className="px-4 py-2">{riskBadge(svc.risk_level)}</td>
                <td className="px-4 py-2 text-gray-400">{svc.user_count}</td>
                <td className="px-4 py-2 text-gray-400 text-xs">{svc.data_exposure}</td>
                <td className="px-4 py-2 text-gray-400 text-xs">
                  {new Date(svc.first_seen).toLocaleDateString()}
                </td>
                <td className="px-4 py-2 text-gray-400 text-xs">
                  {new Date(svc.last_seen).toLocaleDateString()}
                </td>
                <td className="px-4 py-2">{statusBadge(svc.status)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
