import { Input } from "@/components/ui/Input";
import { Calendar, Search } from "lucide-react";

const ACTION_TYPES = [
  "agent.created",
  "agent.updated",
  "agent.deleted",
  "user.invited",
  "user.updated",
  "user.removed",
  "secret.created",
  "secret.rotated",
  "policy.created",
  "policy.updated",
  "deployment.created",
  "deployment.promoted",
  "connector.created",
  "workflow.created",
  "login.success",
  "login.failure",
  "approval.submitted",
  "approval.approved",
  "approval.rejected",
];

const RESOURCE_TYPES = [
  "agents",
  "users",
  "secrets",
  "policies",
  "deployments",
  "connectors",
  "workflows",
  "approvals",
  "budgets",
  "templates",
];

export interface AuditFilterValues {
  search: string;
  action: string;
  resourceType: string;
  dateFrom: string;
  dateTo: string;
}

interface Props {
  filters: AuditFilterValues;
  onChange: (filters: AuditFilterValues) => void;
}

export function AuditFilters({ filters, onChange }: Props) {
  const update = (patch: Partial<AuditFilterValues>) =>
    onChange({ ...filters, ...patch });

  return (
    <div className="mb-4 flex flex-wrap items-center gap-3">
      {/* Full-text search */}
      <div className="relative">
        <Search
          size={14}
          className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-500"
        />
        <Input
          placeholder="Search events…"
          value={filters.search}
          onChange={(e) => update({ search: e.target.value })}
          className="max-w-[200px] pl-8"
        />
      </div>

      {/* Action type */}
      <select
        value={filters.action}
        onChange={(e) => update({ action: e.target.value })}
        className="h-9 rounded-md border border-[#2a2d37] bg-[#1a1d27] px-3 text-sm text-gray-300 focus:border-purple-500 focus:outline-none"
      >
        <option value="">All Actions</option>
        {ACTION_TYPES.map((a) => (
          <option key={a} value={a}>
            {a}
          </option>
        ))}
      </select>

      {/* Resource type */}
      <select
        value={filters.resourceType}
        onChange={(e) => update({ resourceType: e.target.value })}
        className="h-9 rounded-md border border-[#2a2d37] bg-[#1a1d27] px-3 text-sm text-gray-300 focus:border-purple-500 focus:outline-none"
      >
        <option value="">All Resources</option>
        {RESOURCE_TYPES.map((r) => (
          <option key={r} value={r}>
            {r}
          </option>
        ))}
      </select>

      {/* Date range */}
      <div className="flex items-center gap-1.5 text-xs text-gray-400">
        <Calendar size={14} />
        <Input
          type="date"
          value={filters.dateFrom}
          onChange={(e) => update({ dateFrom: e.target.value })}
          className="max-w-[150px]"
          placeholder="From"
        />
        <span>–</span>
        <Input
          type="date"
          value={filters.dateTo}
          onChange={(e) => update({ dateTo: e.target.value })}
          className="max-w-[150px]"
          placeholder="To"
        />
      </div>
    </div>
  );
}
