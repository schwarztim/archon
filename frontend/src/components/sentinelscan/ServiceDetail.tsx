import { X, Server, Shield, Users, Calendar, Globe } from "lucide-react";
import type { ServiceFinding } from "@/api/sentinelscan";

interface ServiceDetailProps {
  service: ServiceFinding;
  onClose: () => void;
  onRemediate?: (findingId: string, action: string) => void;
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

export function ServiceDetail({ service, onClose, onRemediate }: ServiceDetailProps) {
  return (
    <div className="fixed inset-y-0 right-0 z-50 w-96 border-l border-surface-border bg-surface-raised shadow-xl overflow-y-auto">
      <div className="flex items-center justify-between border-b border-surface-border px-4 py-3">
        <h2 className="text-sm font-semibold text-white">Service Details</h2>
        <button onClick={onClose} className="text-gray-400 hover:text-white transition-colors" type="button">
          <X size={18} />
        </button>
      </div>

      <div className="p-4 space-y-4">
        {/* Header */}
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-purple-500/20">
            <Server size={20} className="text-purple-400" />
          </div>
          <div>
            <h3 className="font-semibold text-white">{service.service_name}</h3>
            <p className="text-xs text-gray-500">{service.provider}</p>
          </div>
        </div>

        {/* Status & Risk */}
        <div className="grid grid-cols-2 gap-3">
          <div className="rounded-lg border border-surface-border bg-surface-base p-3">
            <div className="flex items-center gap-1.5 mb-1">
              <Shield size={12} className="text-gray-500" />
              <span className="text-xs text-gray-500">Risk Level</span>
            </div>
            {riskBadge(service.risk_level)}
          </div>
          <div className="rounded-lg border border-surface-border bg-surface-base p-3">
            <span className="text-xs text-gray-500 block mb-1">Status</span>
            {statusBadge(service.status)}
          </div>
        </div>

        {/* Details */}
        <div className="space-y-2">
          <div className="flex items-center gap-2 text-sm">
            <Users size={14} className="text-gray-500" />
            <span className="text-gray-400">Users:</span>
            <span className="text-white">{service.user_count}</span>
          </div>
          <div className="flex items-center gap-2 text-sm">
            <Globe size={14} className="text-gray-500" />
            <span className="text-gray-400">Domain:</span>
            <span className="text-white">{service.domain}</span>
          </div>
          <div className="flex items-center gap-2 text-sm">
            <Shield size={14} className="text-gray-500" />
            <span className="text-gray-400">Type:</span>
            <span className="text-white">{service.service_type}</span>
          </div>
          <div className="flex items-center gap-2 text-sm">
            <Calendar size={14} className="text-gray-500" />
            <span className="text-gray-400">First Seen:</span>
            <span className="text-white">{new Date(service.first_seen).toLocaleDateString()}</span>
          </div>
          <div className="flex items-center gap-2 text-sm">
            <Calendar size={14} className="text-gray-500" />
            <span className="text-gray-400">Last Seen:</span>
            <span className="text-white">{new Date(service.last_seen).toLocaleDateString()}</span>
          </div>
          <div className="text-sm">
            <span className="text-gray-400">Data Exposure:</span>
            <span className="ml-2 text-white">{service.data_exposure}</span>
          </div>
          <div className="text-sm">
            <span className="text-gray-400">Detection Source:</span>
            <span className="ml-2 text-white">{service.detection_source}</span>
          </div>
        </div>

        {/* Remediation Actions */}
        {onRemediate && (
          <div className="border-t border-surface-border pt-4">
            <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">Remediation</h4>
            <div className="grid grid-cols-2 gap-2">
              {(["Block", "Approve", "Monitor", "Ignore"] as const).map((action) => {
                const styles: Record<string, string> = {
                  Block: "bg-red-500/20 text-red-400 hover:bg-red-500/30",
                  Approve: "bg-green-500/20 text-green-400 hover:bg-green-500/30",
                  Monitor: "bg-yellow-500/20 text-yellow-400 hover:bg-yellow-500/30",
                  Ignore: "bg-gray-500/20 text-gray-400 hover:bg-gray-500/30",
                };
                return (
                  <button
                    key={action}
                    className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${styles[action]}`}
                    onClick={() => onRemediate(service.id, action)}
                    type="button"
                  >
                    {action}
                  </button>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
