import { useState } from "react";
import {
  GitBranch,
  Plus,
  Search,
  Play,
  Trash2,
  Users2,
  Calendar,
  Loader2,
  X,
  ChevronDown,
} from "lucide-react";
import { apiGet, apiPost, apiDelete } from "@/api/client";
import type { ApiResponse } from "@/types";
import { useApiQuery, useApiMutation } from "@/hooks/useApi";
import type {
  Workflow,
  WorkflowCreatePayload,
  WorkflowRun,
} from "@/api/workflows";
import {
  listWorkflows,
  createWorkflow,
  executeWorkflow,
  deleteWorkflow,
} from "@/api/workflows";

// ─── Helpers ─────────────────────────────────────────────────────────

function statusBadge(active: boolean) {
  return (
    <span
      className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${
        active
          ? "bg-green-500/20 text-green-400"
          : "bg-gray-500/20 text-gray-400"
      }`}
    >
      {active ? "Active" : "Inactive"}
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
  return `${days}d ago`;
}

// ─── Agent type for step builder dropdown ────────────────────────────

interface AgentOption {
  id: string;
  name: string;
}

// ─── Component ───────────────────────────────────────────────────────

export function WorkflowsPage() {
  const [search, setSearch] = useState("");
  const [groupFilter, setGroupFilter] = useState<string>("all");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [showCreate, setShowCreate] = useState(false);
  const [page, setPage] = useState(0);
  const limit = 20;

  // ── Data fetching ──────────────────────────────────────────────────
  const params: Record<string, string | number | boolean> = {
    limit,
    offset: page * limit,
  };
  if (search) params.search = search;
  if (groupFilter !== "all") params.group_id = groupFilter;
  if (statusFilter !== "all") params.is_active = statusFilter === "active";

  const { data, isLoading, error } = useApiQuery<Workflow[]>(
    ["workflows-page", params],
    () => listWorkflows(params),
  );

  const workflows = data?.data ?? [];
  const total = data?.meta?.pagination?.total ?? workflows.length;

  // ── Distinct groups for filter ─────────────────────────────────────
  const allGroups = Array.from(
    new Set(workflows.map((w) => w.group_name).filter(Boolean)),
  );

  // ── Stats ──────────────────────────────────────────────────────────
  const activeCount = workflows.filter((w) => w.is_active).length;
  const totalSteps = workflows.reduce((sum, w) => sum + w.steps.length, 0);

  // ── Mutations ──────────────────────────────────────────────────────
  const createMutation = useApiMutation<Workflow, WorkflowCreatePayload>(
    (payload) => createWorkflow(payload),
    [["workflows-page"]],
  );

  const deleteMutation = useApiMutation<void, string>(
    (id) =>
      deleteWorkflow(id).then(
        () => undefined as unknown as ApiResponse<void>,
      ),
    [["workflows-page"]],
  );

  const executeMutation = useApiMutation<WorkflowRun, string>(
    (id) => executeWorkflow(id),
    [["workflows-page"]],
  );

  // ── Loading / Error ────────────────────────────────────────────────
  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <p className="text-gray-400">Loading workflows...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6">
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-4 text-red-400">
          Failed to load workflows.
        </div>
      </div>
    );
  }

  return (
    <div className="p-6">
      {/* Header */}
      <div className="mb-2 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <GitBranch size={24} className="text-purple-400" />
          <h1 className="text-2xl font-bold text-white">Workflows</h1>
          <span className="rounded-full bg-[#1a1d27] px-2 py-0.5 text-xs text-gray-400">
            {total}
          </span>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="flex items-center gap-2 rounded-lg bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700"
        >
          <Plus size={16} />
          Create Workflow
        </button>
      </div>
      <p className="mb-6 text-gray-400">
        Define and manage multi-step agent workflows for your team
      </p>

      {/* Stats Bar */}
      <div className="mb-4 grid grid-cols-3 gap-4">
        {[
          { label: "Total Workflows", value: total },
          { label: "Active", value: activeCount },
          { label: "Total Steps", value: totalSteps },
        ].map((s) => (
          <div
            key={s.label}
            className="rounded-lg border border-[#2a2d37] bg-[#1a1d27] px-4 py-3"
          >
            <p className="text-xs text-gray-500">{s.label}</p>
            <p className="text-lg font-bold text-white">{s.value}</p>
          </div>
        ))}
      </div>

      {/* Filters */}
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[200px]">
          <Search
            size={16}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500"
          />
          <input
            type="text"
            placeholder="Search workflows..."
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(0);
            }}
            className="w-full rounded-lg border border-[#2a2d37] bg-[#1a1d27] py-2 pl-9 pr-3 text-sm text-white placeholder-gray-500 focus:border-purple-500 focus:outline-none"
          />
        </div>
        {allGroups.length > 0 && (
          <select
            value={groupFilter}
            onChange={(e) => {
              setGroupFilter(e.target.value);
              setPage(0);
            }}
            className="rounded-lg border border-[#2a2d37] bg-[#1a1d27] px-3 py-2 text-sm text-white focus:border-purple-500 focus:outline-none"
          >
            <option value="all">All Groups</option>
            {allGroups.map((g) => (
              <option key={g} value={g}>
                {g}
              </option>
            ))}
          </select>
        )}
        <select
          value={statusFilter}
          onChange={(e) => {
            setStatusFilter(e.target.value);
            setPage(0);
          }}
          className="rounded-lg border border-[#2a2d37] bg-[#1a1d27] px-3 py-2 text-sm text-white focus:border-purple-500 focus:outline-none"
        >
          <option value="all">All Statuses</option>
          <option value="active">Active</option>
          <option value="inactive">Inactive</option>
        </select>
      </div>

      {/* Table */}
      {workflows.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-lg border border-[#2a2d37] bg-[#1a1d27] py-16">
          <GitBranch size={48} className="mb-3 text-gray-600" />
          <p className="mb-1 text-sm text-gray-400">No workflows found</p>
          <p className="mb-4 text-xs text-gray-600">
            Create your first workflow to get started.
          </p>
          <button
            onClick={() => setShowCreate(true)}
            className="flex items-center gap-2 rounded-lg bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700"
          >
            <Plus size={16} />
            Create Workflow
          </button>
        </div>
      ) : (
        <div className="rounded-lg border border-[#2a2d37] bg-[#1a1d27]">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[#2a2d37] text-left text-xs text-gray-500">
                  <th className="px-4 py-2 font-medium">Name</th>
                  <th className="px-4 py-2 font-medium">Group</th>
                  <th className="px-4 py-2 font-medium">Steps</th>
                  <th className="px-4 py-2 font-medium">Schedule</th>
                  <th className="px-4 py-2 font-medium">Status</th>
                  <th className="px-4 py-2 font-medium">Updated</th>
                  <th className="px-4 py-2 font-medium text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {workflows.map((wf) => (
                  <tr
                    key={wf.id}
                    className="border-b border-[#2a2d37] hover:bg-white/5"
                  >
                    <td className="px-4 py-2">
                      <div className="flex items-center gap-2">
                        <GitBranch size={16} className="text-purple-400" />
                        <div>
                          <span className="font-medium text-white">
                            {wf.name}
                          </span>
                          <p className="line-clamp-1 text-xs text-gray-500">
                            {wf.description || "No description"}
                          </p>
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-2">
                      <div className="flex items-center gap-1 text-gray-400">
                        <Users2 size={12} />
                        {wf.group_name || "—"}
                      </div>
                    </td>
                    <td className="px-4 py-2 text-gray-400">
                      {wf.steps.length}
                    </td>
                    <td className="px-4 py-2">
                      <div className="flex items-center gap-1 text-gray-400">
                        <Calendar size={12} />
                        {wf.schedule || "Manual"}
                      </div>
                    </td>
                    <td className="px-4 py-2">{statusBadge(wf.is_active)}</td>
                    <td className="px-4 py-2 text-gray-400">
                      {timeAgo(wf.updated_at)}
                    </td>
                    <td className="px-4 py-2 text-right">
                      <div className="flex items-center justify-end gap-1">
                        <button
                          onClick={() => executeMutation.mutate(wf.id)}
                          className="rounded p-1 text-gray-400 hover:bg-green-500/20 hover:text-green-400"
                          aria-label={`Run ${wf.name}`}
                          title="Run workflow"
                        >
                          {executeMutation.isPending ? (
                            <Loader2 size={14} className="animate-spin" />
                          ) : (
                            <Play size={14} />
                          )}
                        </button>
                        <button
                          onClick={() => {
                            if (confirm(`Delete workflow "${wf.name}"?`)) {
                              deleteMutation.mutate(wf.id);
                            }
                          }}
                          className="rounded p-1 text-gray-400 hover:bg-red-500/20 hover:text-red-400"
                          aria-label={`Delete ${wf.name}`}
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

      {/* Create Workflow Modal */}
      {showCreate && (
        <CreateWorkflowModal
          onClose={() => setShowCreate(false)}
          onSubmit={(payload) => {
            createMutation.mutate(payload, {
              onSuccess: () => setShowCreate(false),
            });
          }}
          isPending={createMutation.isPending}
        />
      )}
    </div>
  );
}

// ─── Create Workflow Modal ───────────────────────────────────────────

interface StepDraft {
  key: string;
  name: string;
  agent_id: string;
  config: string;
  depends_on: string[];
}

function CreateWorkflowModal({
  onClose,
  onSubmit,
  isPending,
}: {
  onClose: () => void;
  onSubmit: (payload: WorkflowCreatePayload) => void;
  isPending: boolean;
}) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [groupId, setGroupId] = useState("");
  const [groupName, setGroupName] = useState("");
  const [schedule, setSchedule] = useState("");
  const [steps, setSteps] = useState<StepDraft[]>([]);

  // Load agents for dropdown
  const { data: agentsData } = useApiQuery<AgentOption[]>(
    ["agents-for-workflow"],
    () => apiGet<AgentOption[]>("/agents/"),
  );
  const agents = agentsData?.data ?? [];

  function addStep() {
    setSteps((prev) => [
      ...prev,
      {
        key: crypto.randomUUID(),
        name: "",
        agent_id: "",
        config: "{}",
        depends_on: [],
      },
    ]);
  }

  function removeStep(key: string) {
    setSteps((prev) => prev.filter((s) => s.key !== key));
  }

  function updateStep(key: string, field: keyof StepDraft, value: unknown) {
    setSteps((prev) =>
      prev.map((s) => (s.key === key ? { ...s, [field]: value } : s)),
    );
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!name) return;

    const parsedSteps = steps.map((s) => {
      let config: Record<string, unknown> = {};
      try {
        config = JSON.parse(s.config || "{}");
      } catch {
        /* use empty */
      }
      return {
        name: s.name,
        agent_id: s.agent_id,
        config,
        depends_on: s.depends_on,
      };
    });

    onSubmit({
      name,
      description,
      group_id: groupId,
      group_name: groupName,
      steps: parsedSteps,
      schedule: schedule || null,
      is_active: true,
      created_by: "",
    });
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-lg border border-[#2a2d37] bg-[#12141e] p-6">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-white">Create Workflow</h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-white"
            aria-label="Close"
          >
            <X size={20} />
          </button>
        </div>
        <form onSubmit={handleSubmit}>
          {/* Basic fields */}
          <label className="mb-1 block text-xs text-gray-400">Name</label>
          <input
            type="text"
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="mb-3 w-full rounded-lg border border-[#2a2d37] bg-[#1a1d27] px-3 py-2 text-sm text-white focus:border-purple-500 focus:outline-none"
            placeholder="My Workflow"
          />

          <label className="mb-1 block text-xs text-gray-400">
            Description
          </label>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={2}
            className="mb-3 w-full rounded-lg border border-[#2a2d37] bg-[#1a1d27] px-3 py-2 text-sm text-white focus:border-purple-500 focus:outline-none"
            placeholder="What does this workflow do?"
          />

          <div className="mb-3 grid grid-cols-2 gap-3">
            <div>
              <label className="mb-1 block text-xs text-gray-400">
                Group ID
              </label>
              <input
                type="text"
                value={groupId}
                onChange={(e) => setGroupId(e.target.value)}
                className="w-full rounded-lg border border-[#2a2d37] bg-[#1a1d27] px-3 py-2 text-sm text-white focus:border-purple-500 focus:outline-none"
                placeholder="team-alpha"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs text-gray-400">
                Group Name
              </label>
              <input
                type="text"
                value={groupName}
                onChange={(e) => setGroupName(e.target.value)}
                className="w-full rounded-lg border border-[#2a2d37] bg-[#1a1d27] px-3 py-2 text-sm text-white focus:border-purple-500 focus:outline-none"
                placeholder="Team Alpha"
              />
            </div>
          </div>

          <label className="mb-1 block text-xs text-gray-400">
            Schedule (cron, optional)
          </label>
          <input
            type="text"
            value={schedule}
            onChange={(e) => setSchedule(e.target.value)}
            className="mb-4 w-full rounded-lg border border-[#2a2d37] bg-[#1a1d27] px-3 py-2 text-sm text-white focus:border-purple-500 focus:outline-none"
            placeholder="0 */6 * * * (leave blank for manual)"
          />

          {/* Steps builder */}
          <div className="mb-4">
            <div className="mb-2 flex items-center justify-between">
              <label className="text-xs font-medium text-gray-400">
                Steps
              </label>
              <button
                type="button"
                onClick={addStep}
                className="flex items-center gap-1 rounded border border-[#2a2d37] px-2 py-1 text-xs text-gray-400 hover:bg-white/5"
              >
                <Plus size={12} />
                Add Step
              </button>
            </div>

            {steps.length === 0 && (
              <p className="rounded border border-dashed border-[#2a2d37] py-4 text-center text-xs text-gray-600">
                No steps yet — click "Add Step" to begin.
              </p>
            )}

            <div className="space-y-3">
              {steps.map((step, idx) => (
                <div
                  key={step.key}
                  className="rounded-lg border border-[#2a2d37] bg-[#1a1d27] p-3"
                >
                  <div className="mb-2 flex items-center justify-between">
                    <span className="text-xs font-medium text-purple-400">
                      Step {idx + 1}
                    </span>
                    <button
                      type="button"
                      onClick={() => removeStep(step.key)}
                      className="text-gray-500 hover:text-red-400"
                      aria-label="Remove step"
                    >
                      <Trash2 size={12} />
                    </button>
                  </div>

                  <div className="mb-2 grid grid-cols-2 gap-2">
                    <div>
                      <label className="mb-0.5 block text-[10px] text-gray-500">
                        Step Name
                      </label>
                      <input
                        type="text"
                        value={step.name}
                        onChange={(e) =>
                          updateStep(step.key, "name", e.target.value)
                        }
                        className="w-full rounded border border-[#2a2d37] bg-[#12141e] px-2 py-1.5 text-xs text-white focus:border-purple-500 focus:outline-none"
                        placeholder="Step name"
                      />
                    </div>
                    <div>
                      <label className="mb-0.5 block text-[10px] text-gray-500">
                        Agent
                      </label>
                      <select
                        value={step.agent_id}
                        onChange={(e) =>
                          updateStep(step.key, "agent_id", e.target.value)
                        }
                        className="w-full rounded border border-[#2a2d37] bg-[#12141e] px-2 py-1.5 text-xs text-white focus:border-purple-500 focus:outline-none"
                      >
                        <option value="">Select agent...</option>
                        {agents.map((a) => (
                          <option key={a.id} value={a.id}>
                            {a.name}
                          </option>
                        ))}
                      </select>
                    </div>
                  </div>

                  <div className="mb-2">
                    <label className="mb-0.5 block text-[10px] text-gray-500">
                      Config (JSON)
                    </label>
                    <textarea
                      value={step.config}
                      onChange={(e) =>
                        updateStep(step.key, "config", e.target.value)
                      }
                      rows={2}
                      className="w-full rounded border border-[#2a2d37] bg-[#12141e] px-2 py-1.5 font-mono text-xs text-white focus:border-purple-500 focus:outline-none"
                      placeholder="{}"
                    />
                  </div>

                  {idx > 0 && (
                    <div>
                      <label className="mb-0.5 block text-[10px] text-gray-500">
                        Depends On
                      </label>
                      <div className="flex flex-wrap gap-1">
                        {steps.slice(0, idx).map((dep) => {
                          const selected = step.depends_on.includes(dep.key);
                          return (
                            <button
                              key={dep.key}
                              type="button"
                              onClick={() => {
                                const newDeps = selected
                                  ? step.depends_on.filter(
                                      (d) => d !== dep.key,
                                    )
                                  : [...step.depends_on, dep.key];
                                updateStep(step.key, "depends_on", newDeps);
                              }}
                              className={`rounded px-2 py-0.5 text-[10px] ${
                                selected
                                  ? "bg-purple-500/20 text-purple-300"
                                  : "bg-[#12141e] text-gray-500 hover:bg-white/5"
                              }`}
                            >
                              {dep.name || `Step ${steps.indexOf(dep) + 1}`}
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>

          {/* Actions */}
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-[#2a2d37] px-4 py-2 text-sm text-gray-400 hover:bg-white/5"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isPending}
              className="flex items-center gap-2 rounded-lg bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50"
            >
              <GitBranch size={14} />
              {isPending ? "Creating..." : "Create Workflow"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
