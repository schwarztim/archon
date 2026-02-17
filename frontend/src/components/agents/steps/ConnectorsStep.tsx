import { useState } from "react";
import { Plug, ExternalLink, Check, AlertCircle, Search } from "lucide-react";
import { useApiQuery } from "@/hooks/useApi";
import { apiGet } from "@/api/client";
import type { Connector } from "@/types/models";

// ─── Types ───────────────────────────────────────────────────────────

export interface ConnectorsData {
  selectedConnectors: string[];
}

interface ConnectorsStepProps {
  data: ConnectorsData;
  onChange: (data: ConnectorsData) => void;
}

// ─── Constants ───────────────────────────────────────────────────────

const CONNECTOR_ICONS: Record<string, string> = {
  slack: "💬",
  postgresql: "🐘",
  salesforce: "☁️",
  github: "🐙",
  s3: "📦",
  jira: "📋",
  rest: "🔗",
  snowflake: "❄️",
  hubspot: "🟠",
  stripe: "💳",
  google_drive: "📁",
  teams: "👥",
};

const CATEGORY_MAP: Record<string, string> = {
  slack: "Communication",
  teams: "Communication",
  postgresql: "Database",
  snowflake: "Database",
  salesforce: "CRM",
  hubspot: "CRM",
  github: "Development",
  jira: "Project Management",
  s3: "Storage",
  google_drive: "Storage",
  rest: "API",
  stripe: "Payments",
};

const FALLBACK_CONNECTORS = [
  { id: "slack-1", name: "Slack", type: "slack", status: "connected" as const, config: {} },
  { id: "pg-1", name: "PostgreSQL", type: "postgresql", status: "connected" as const, config: {} },
  { id: "github-1", name: "GitHub", type: "github", status: "connected" as const, config: {} },
  { id: "sf-1", name: "Salesforce", type: "salesforce", status: "disconnected" as const, config: {} },
  { id: "s3-1", name: "Amazon S3", type: "s3", status: "disconnected" as const, config: {} },
  { id: "jira-1", name: "Jira", type: "jira", status: "disconnected" as const, config: {} },
  { id: "snowflake-1", name: "Snowflake", type: "snowflake", status: "disconnected" as const, config: {} },
  { id: "hubspot-1", name: "HubSpot", type: "hubspot", status: "disconnected" as const, config: {} },
];

const STATUS_COLORS = {
  connected: "text-green-400",
  disconnected: "text-gray-500",
  error: "text-red-400",
  pending: "text-yellow-400",
};

// ─── Component ───────────────────────────────────────────────────────

export function ConnectorsStep({ data, onChange }: ConnectorsStepProps) {
  const [categoryFilter, setCategoryFilter] = useState("All");
  const [search, setSearch] = useState("");

  const { data: connectorsResp } = useApiQuery<Connector[]>(
    ["connectors-wizard"],
    () => apiGet<Connector[]>("/connectors/", { limit: 100 }),
  );

  const connectors = (connectorsResp?.data?.length ?? 0) > 0
    ? connectorsResp!.data
    : FALLBACK_CONNECTORS;

  const categories = ["All", ...new Set(
    connectors.map((c) => CATEGORY_MAP[c.type] ?? "Other"),
  )];

  const filtered = connectors.filter((c) => {
    const matchesSearch = c.name.toLowerCase().includes(search.toLowerCase());
    const cat = CATEGORY_MAP[c.type] ?? "Other";
    const matchesCategory = categoryFilter === "All" || cat === categoryFilter;
    return matchesSearch && matchesCategory;
  });

  const toggleConnector = (id: string) => {
    onChange({
      selectedConnectors: data.selectedConnectors.includes(id)
        ? data.selectedConnectors.filter((c) => c !== id)
        : [...data.selectedConnectors, id],
    });
  };

  const inputClass =
    "w-full rounded-lg border border-[#2a2d37] bg-[#1a1d27] px-3 py-2 text-sm text-white placeholder-gray-500 focus:border-purple-500 focus:outline-none";

  return (
    <div className="space-y-4">
      {/* Search & Category Filter */}
      <div className="flex gap-3">
        <div className="relative flex-1">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
          <input
            type="text"
            placeholder="Search connectors..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className={`pl-9 ${inputClass}`}
          />
        </div>
        <select
          value={categoryFilter}
          onChange={(e) => setCategoryFilter(e.target.value)}
          className={`w-40 ${inputClass}`}
        >
          {categories.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
      </div>

      {/* Connector Cards */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {filtered.map((connector) => {
          const isSelected = data.selectedConnectors.includes(connector.id);
          const icon = CONNECTOR_ICONS[connector.type] ?? "🔗";
          const isConnected = connector.status === "connected";

          return (
            <div
              key={connector.id}
              className={`rounded-lg border p-4 transition-colors ${
                isSelected
                  ? "border-purple-500 bg-purple-500/10"
                  : "border-[#2a2d37] bg-[#1a1d27] hover:border-gray-600"
              }`}
            >
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-3">
                  <span className="text-2xl">{icon}</span>
                  <div>
                    <span className="text-sm font-medium text-white">{connector.name}</span>
                    <div className="flex items-center gap-1 text-xs">
                      {isConnected ? (
                        <>
                          <Check size={12} className={STATUS_COLORS.connected} />
                          <span className={STATUS_COLORS.connected}>Connected</span>
                        </>
                      ) : connector.status === "error" ? (
                        <>
                          <AlertCircle size={12} className={STATUS_COLORS.error} />
                          <span className={STATUS_COLORS.error}>Error</span>
                        </>
                      ) : (
                        <>
                          <Plug size={12} className={STATUS_COLORS.disconnected} />
                          <span className={STATUS_COLORS.disconnected}>Not connected</span>
                        </>
                      )}
                    </div>
                  </div>
                </div>
              </div>

              <div className="mt-3 flex items-center justify-between">
                <span className="rounded bg-[#12141e] px-1.5 py-0.5 text-[10px] text-gray-500">
                  {CATEGORY_MAP[connector.type] ?? "Other"}
                </span>
                <div className="flex gap-2">
                  {!isConnected && (
                    <button
                      type="button"
                      className="flex items-center gap-1 rounded px-2 py-1 text-xs text-purple-400 hover:bg-purple-500/10"
                    >
                      <ExternalLink size={12} /> Connect
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => toggleConnector(connector.id)}
                    className={`rounded px-2 py-1 text-xs font-medium ${
                      isSelected
                        ? "bg-purple-500/20 text-purple-400"
                        : "text-gray-400 hover:bg-white/5"
                    }`}
                  >
                    {isSelected ? "Selected ✓" : "Select"}
                  </button>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Selected count */}
      <p className="text-xs text-gray-500">
        {data.selectedConnectors.length} connector{data.selectedConnectors.length !== 1 ? "s" : ""} selected
      </p>
    </div>
  );
}
