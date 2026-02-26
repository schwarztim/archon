import { CheckCircle2, XCircle, AlertCircle } from "lucide-react";

export type ServiceStatus = "healthy" | "degraded" | "unhealthy" | "unknown";

export interface ServiceHealth {
  name: string;
  displayName: string;
  status: ServiceStatus;
}

function StatusDot({ status }: { status: ServiceStatus }) {
  const colors: Record<ServiceStatus, string> = {
    healthy: "bg-green-500",
    degraded: "bg-yellow-500",
    unhealthy: "bg-red-500",
    unknown: "bg-gray-500",
  };
  return <span className={`inline-block h-2.5 w-2.5 rounded-full ${colors[status]}`} />;
}

function StatusIcon({ status }: { status: ServiceStatus }) {
  switch (status) {
    case "healthy":
      return <CheckCircle2 size={14} className="text-green-500" />;
    case "degraded":
      return <AlertCircle size={14} className="text-yellow-500" />;
    case "unhealthy":
      return <XCircle size={14} className="text-red-500" />;
    default:
      return <AlertCircle size={14} className="text-gray-500" />;
  }
}

interface HealthIndicatorsProps {
  services: ServiceHealth[];
}

export function HealthIndicators({ services }: HealthIndicatorsProps) {
  return (
    <div className="rounded-lg border border-surface-border bg-surface-raised p-4">
      <h2 className="mb-3 text-sm font-semibold text-white">System Health</h2>
      <div className="flex flex-wrap gap-6">
        {services.map((service) => (
          <div key={service.name} className="flex items-center gap-2">
            <StatusDot status={service.status} />
            <span className="text-sm text-gray-300">{service.displayName}</span>
            <StatusIcon status={service.status} />
          </div>
        ))}
      </div>
    </div>
  );
}
