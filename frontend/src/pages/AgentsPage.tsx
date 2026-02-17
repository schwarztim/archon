import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Bot,
  Plus,
  Search,
  LayoutGrid,
  List,
  Edit,
  Copy,
  Trash2,
  Play,
  Pause,
  MoreHorizontal,
  Tag,
  Clock,
  Zap,
} from "lucide-react";
import { useAuth } from "@/providers/auth-provider";
import { apiGet, apiPost, apiPut, apiDelete } from "@/api/client";
import type { ApiResponse } from "@/types";
import { useApiQuery, useApiMutation } from "@/hooks/useApi";
import { AgentWizard } from "@/components/wizard/AgentWizard";

// ─── Types ───────────────────────────────────────────────────────────

interface Agent {
  id: string;
  name: string;
  description: string;
  status: "active" | "draft" | "paused" | "archived";
  tags: string[];
  created_at: string;
  updated_at: string;
  execution_count: number;
  last_executed: string | null;
  owner: string;
}

interface CreateAgentPayload {
  name: string;
  description: string;
  tags: string[];
  definition?: Record<string, unknown>;
  llm_config?: Record<string, unknown>;
  tools?: string[];
  rag_config?: Record<string, unknown> | null;
  security_policy?: Record<string, unknown>;
  mcp_config?: Record<string, unknown> | null;
  connectors?: string[];
}

// ─── Helpers ─────────────────────────────────────────────────────────

const STATUS_COLORS: Record<string, string> = {
  active: "bg-green-500/20 text-green-400",
  draft: "bg-gray-500/20 text-gray-400",
  paused: "bg-yellow-500/20 text-yellow-400",
  archived: "bg-red-500/20 text-red-400",
};

function statusBadge(status: string) {
  return (
    <span
      className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium capitalize ${STATUS_COLORS[status] ?? "bg-gray-500/20 text-gray-400"}`}
    >
      {status}
    </span>
  );
}

function timeAgo(dateStr: string | null): string {
  if (!dateStr) return "Never";
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "Just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return `${Math.floor(days / 30)}mo ago`;
}

// ─── Component ───────────────────────────────────────────────────────

export function AgentsPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [tagFilter, setTagFilter] = useState<string>("all");
  const [viewMode, setViewMode] = useState<"grid" | "list">("grid");
  const [showCreate, setShowCreate] = useState(false);
  const [quickCreate, setQuickCreate] = useState(false);
  const [activeMenu, setActiveMenu] = useState<string | null>(null);
  const [page, setPage] = useState(0);
  const limit = 20;

  // ── Data fetching ──────────────────────────────────────────────────
  const params: Record<string, string | number> = { limit, offset: page * limit };
  if (search) params.search = search;
  if (statusFilter !== "all") params.status = statusFilter;
  if (tagFilter !== "all") params.tag = tagFilter;

  const { data, isLoading, error } = useApiQuery<Agent[]>(
    ["agents-page", params],
    () => apiGet<Agent[]>("/agents/", params),
  );

  const agents = data?.data ?? [];
  const total = data?.meta?.pagination?.total ?? agents.length;

  // ── Distinct tags ──────────────────────────────────────────────────
  const allTags = Array.from(new Set(agents.flatMap((a) => a.tags)));

  // ── Mutations ──────────────────────────────────────────────────────
  const createMutation = useApiMutation<Agent, CreateAgentPayload>(
    (payload) => apiPost<Agent>("/agents/", payload),
    [["agents-page"]],
  );

  const cloneMutation = useApiMutation<Agent, string>(
    (id) => apiPost<Agent>(`/agents/${id}/clone`, {}),
    [["agents-page"]],
  );

  const deleteMutation = useApiMutation<void, string>(
    (id) => apiDelete(`/agents/${id}`).then(() => undefined as unknown as ApiResponse<void>),
    [["agents-page"]],
  );

  const statusMutation = useApiMutation<Agent, { id: string; status: string }>(
    ({ id, status }) => apiPut<Agent>(`/agents/${id}`, { status }),
    [["agents-page"]],
  );

  // ── Loading / Error ────────────────────────────────────────────────
  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <p className="text-gray-400">Loading agents...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6">
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-4 text-red-400">
          Failed to load agents.
        </div>
      </div>
    );
  }

  return (
    <div className="p-6">
      {/* Header */}
      <div className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Bot size={24} className="text-purple-400" />
          <h1 className="text-2xl font-bold text-white">Agents</h1>
          <span className="rounded-full bg-[#1a1d27] px-2 py-0.5 text-xs text-gray-400">
            {total}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {/* View Toggle */}
          <div className="flex rounded-lg border border-[#2a2d37]">
            <button
              onClick={() => setViewMode("grid")}
              className={`rounded-l-lg p-2 ${
                viewMode === "grid" ? "bg-purple-600 text-white" : "text-gray-400 hover:bg-white/5"
              }`}
              aria-label="Grid view"
            >
              <LayoutGrid size={16} />
            </button>
            <button
              onClick={() => setViewMode("list")}
              className={`rounded-r-lg p-2 ${
                viewMode === "list" ? "bg-purple-600 text-white" : "text-gray-400 hover:bg-white/5"
              }`}
              aria-label="List view"
            >
              <List size={16} />
            </button>
          </div>
          <div className="relative group">
            <button
              onClick={() => { setQuickCreate(false); setShowCreate(true); }}
              className="flex items-center gap-2 rounded-lg bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700"
            >
              <Plus size={16} />
              Create Agent
            </button>
            <button
              onClick={() => { setQuickCreate(true); setShowCreate(true); }}
              className="mt-1 flex w-full items-center gap-2 rounded-lg border border-[#2a2d37] px-4 py-1.5 text-xs text-gray-400 hover:bg-white/5 absolute top-full right-0 bg-[#12141e] opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap"
            >
              <Zap size={12} />
              Quick Create
            </button>
          </div>
        </div>
      </div>

      {/* Search & Filters */}
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[200px]">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
          <input
            type="text"
            placeholder="Search agents..."
            value={search}
            onChange={(e) => { setSearch(e.target.value); setPage(0); }}
            className="w-full rounded-lg border border-[#2a2d37] bg-[#1a1d27] py-2 pl-9 pr-3 text-sm text-white placeholder-gray-500 focus:border-purple-500 focus:outline-none"
          />
        </div>
        <select
          value={statusFilter}
          onChange={(e) => { setStatusFilter(e.target.value); setPage(0); }}
          className="rounded-lg border border-[#2a2d37] bg-[#1a1d27] px-3 py-2 text-sm text-white focus:border-purple-500 focus:outline-none"
        >
          <option value="all">All Statuses</option>
          <option value="active">Active</option>
          <option value="draft">Draft</option>
          <option value="paused">Paused</option>
          <option value="archived">Archived</option>
        </select>
        {allTags.length > 0 && (
          <select
            value={tagFilter}
            onChange={(e) => { setTagFilter(e.target.value); setPage(0); }}
            className="rounded-lg border border-[#2a2d37] bg-[#1a1d27] px-3 py-2 text-sm text-white focus:border-purple-500 focus:outline-none"
          >
            <option value="all">All Tags</option>
            {allTags.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        )}
      </div>

      {/* Empty State */}
      {agents.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-lg border border-[#2a2d37] bg-[#1a1d27] py-16">
          <Bot size={48} className="mb-3 text-gray-600" />
          <p className="mb-1 text-sm text-gray-400">No agents found</p>
          <p className="mb-4 text-xs text-gray-600">Create your first agent to get started.</p>
          <button
            onClick={() => { setQuickCreate(false); setShowCreate(true); }}
            className="flex items-center gap-2 rounded-lg bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700"
          >
            <Plus size={16} />
            Create Agent
          </button>
        </div>
      ) : viewMode === "grid" ? (
        /* Grid View */
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {agents.map((agent) => (
            <div
              key={agent.id}
              className="group relative rounded-lg border border-[#2a2d37] bg-[#1a1d27] p-4 hover:border-purple-500/30"
            >
              {/* Card Header */}
              <div className="mb-3 flex items-start justify-between">
                <div className="flex items-center gap-2">
                  <Bot size={18} className="text-purple-400" />
                  <h3 className="font-medium text-white">{agent.name}</h3>
                </div>
                <div className="relative">
                  <button
                    onClick={() => setActiveMenu(activeMenu === agent.id ? null : agent.id)}
                    className="rounded p-1 text-gray-400 opacity-0 hover:bg-white/10 hover:text-white group-hover:opacity-100"
                    aria-label={`Actions for ${agent.name}`}
                  >
                    <MoreHorizontal size={16} />
                  </button>
                  {activeMenu === agent.id && (
                    <div className="absolute right-0 top-8 z-10 w-36 rounded-lg border border-[#2a2d37] bg-[#12141e] py-1 shadow-xl">
                      <button
                        onClick={() => { setActiveMenu(null); navigate(`/builder?agentId=${agent.id}`); }}
                        className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-gray-300 hover:bg-white/5"
                      >
                        <Edit size={14} /> Edit
                      </button>
                      <button
                        onClick={() => {
                          cloneMutation.mutate(agent.id);
                          setActiveMenu(null);
                        }}
                        className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-gray-300 hover:bg-white/5"
                      >
                        <Copy size={14} /> Clone
                      </button>
                      <button
                        onClick={() => {
                          statusMutation.mutate({
                            id: agent.id,
                            status: agent.status === "active" ? "paused" : "active",
                          });
                          setActiveMenu(null);
                        }}
                        className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-gray-300 hover:bg-white/5"
                      >
                        {agent.status === "active" ? (
                          <><Pause size={14} /> Pause</>
                        ) : (
                          <><Play size={14} /> Activate</>
                        )}
                      </button>
                      <hr className="my-1 border-[#2a2d37]" />
                      <button
                        onClick={() => {
                          if (confirm(`Delete agent "${agent.name}"?`)) {
                            deleteMutation.mutate(agent.id);
                          }
                          setActiveMenu(null);
                        }}
                        className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-red-400 hover:bg-red-500/10"
                      >
                        <Trash2 size={14} /> Delete
                      </button>
                    </div>
                  )}
                </div>
              </div>

              {/* Description */}
              <p className="mb-3 line-clamp-2 text-xs text-gray-500">
                {agent.description || "No description"}
              </p>

              {/* Status & Tags */}
              <div className="mb-3 flex flex-wrap items-center gap-2">
                {statusBadge(agent.status)}
                {agent.tags.slice(0, 3).map((t) => (
                  <span
                    key={t}
                    className="flex items-center gap-1 rounded bg-[#12141e] px-1.5 py-0.5 text-xs text-gray-500"
                  >
                    <Tag size={10} />
                    {t}
                  </span>
                ))}
                {agent.tags.length > 3 && (
                  <span className="text-xs text-gray-600">+{agent.tags.length - 3}</span>
                )}
              </div>

              {/* Footer Stats */}
              <div className="flex items-center justify-between border-t border-[#2a2d37] pt-3 text-xs text-gray-500">
                <div className="flex items-center gap-1">
                  <Play size={12} />
                  {agent.execution_count} runs
                </div>
                <div className="flex items-center gap-1">
                  <Clock size={12} />
                  {timeAgo(agent.last_executed)}
                </div>
              </div>
            </div>
          ))}
        </div>
      ) : (
        /* List View */
        <div className="rounded-lg border border-[#2a2d37] bg-[#1a1d27]">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[#2a2d37] text-left text-xs text-gray-500">
                  <th className="px-4 py-2 font-medium">Name</th>
                  <th className="px-4 py-2 font-medium">Status</th>
                  <th className="px-4 py-2 font-medium">Tags</th>
                  <th className="px-4 py-2 font-medium">Runs</th>
                  <th className="px-4 py-2 font-medium">Last Run</th>
                  <th className="px-4 py-2 font-medium">Updated</th>
                  <th className="px-4 py-2 font-medium text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {agents.map((agent) => (
                  <tr key={agent.id} className="border-b border-[#2a2d37] hover:bg-white/5">
                    <td className="px-4 py-2">
                      <div className="flex items-center gap-2">
                        <Bot size={16} className="text-purple-400" />
                        <div>
                          <span className="font-medium text-white">{agent.name}</span>
                          <p className="line-clamp-1 text-xs text-gray-500">{agent.description}</p>
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-2">{statusBadge(agent.status)}</td>
                    <td className="px-4 py-2">
                      <div className="flex flex-wrap gap-1">
                        {agent.tags.slice(0, 2).map((t) => (
                          <span
                            key={t}
                            className="rounded bg-[#12141e] px-1.5 py-0.5 text-xs text-gray-500"
                          >
                            {t}
                          </span>
                        ))}
                        {agent.tags.length > 2 && (
                          <span className="text-xs text-gray-600">+{agent.tags.length - 2}</span>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-2 text-gray-400">{agent.execution_count}</td>
                    <td className="px-4 py-2 text-gray-400">{timeAgo(agent.last_executed)}</td>
                    <td className="px-4 py-2 text-gray-400">
                      {new Date(agent.updated_at).toLocaleDateString()}
                    </td>
                    <td className="px-4 py-2 text-right">
                      <div className="flex items-center justify-end gap-1">
                        <button
                          onClick={() => navigate(`/builder?agentId=${agent.id}`)}
                          className="rounded p-1 text-gray-400 hover:bg-white/10 hover:text-white"
                          aria-label={`Edit ${agent.name}`}
                        >
                          <Edit size={14} />
                        </button>
                        <button
                          onClick={() => cloneMutation.mutate(agent.id)}
                          className="rounded p-1 text-gray-400 hover:bg-blue-500/20 hover:text-blue-400"
                          aria-label={`Clone ${agent.name}`}
                        >
                          <Copy size={14} />
                        </button>
                        <button
                          onClick={() => {
                            if (confirm(`Delete agent "${agent.name}"?`)) {
                              deleteMutation.mutate(agent.id);
                            }
                          }}
                          className="rounded p-1 text-gray-400 hover:bg-red-500/20 hover:text-red-400"
                          aria-label={`Delete ${agent.name}`}
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Pagination */}
      {total > limit && (
        <div className="mt-4 flex items-center justify-between">
          <span className="text-xs text-gray-500">
            {page * limit + 1}–{Math.min((page + 1) * limit, total)} of {total}
          </span>
          <div className="flex gap-2">
            <button
              disabled={page === 0}
              onClick={() => setPage((p) => p - 1)}
              className="rounded border border-[#2a2d37] px-3 py-1 text-xs text-gray-400 hover:bg-white/5 disabled:opacity-40"
            >
              Previous
            </button>
            <button
              disabled={(page + 1) * limit >= total}
              onClick={() => setPage((p) => p + 1)}
              className="rounded border border-[#2a2d37] px-3 py-1 text-xs text-gray-400 hover:bg-white/5 disabled:opacity-40"
            >
              Next
            </button>
          </div>
        </div>
      )}

      {/* Agent Creation Wizard */}
      {showCreate && (
        <AgentWizard
          onClose={() => setShowCreate(false)}
          onSubmit={(payload) => {
            createMutation.mutate(payload as CreateAgentPayload, {
              onSuccess: () => setShowCreate(false),
            });
          }}
          isPending={createMutation.isPending}
          quickCreate={quickCreate}
        />
      )}
    </div>
  );
}
