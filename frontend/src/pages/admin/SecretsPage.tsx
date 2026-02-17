import { useState } from "react";
import {
  KeyRound,
  Plus,
  RefreshCw,
  Trash2,
  ShieldOff,
  Eye,
  EyeOff,
  X,
  Search,
  AlertTriangle,
} from "lucide-react";
import { useAuth } from "@/providers/auth-provider";
import { apiGet, apiPost, apiDelete } from "@/api/client";
import type { ApiResponse } from "@/types";
import { useApiQuery, useApiMutation } from "@/hooks/useApi";

// ─── Types ───────────────────────────────────────────────────────────

interface Secret {
  id: string;
  name: string;
  path: string;
  type: "api_key" | "oauth_token" | "certificate" | "password" | "generic";
  last_rotated: string | null;
  created_at: string;
  expires_at: string | null;
}

interface CreateSecretPayload {
  name: string;
  path: string;
  type: Secret["type"];
  value: string;
}

// ─── Helpers ─────────────────────────────────────────────────────────

const TYPE_BADGES: Record<string, { icon: string; color: string }> = {
  api_key: { icon: "🔑", color: "bg-blue-500/20 text-blue-400" },
  oauth_token: { icon: "🎫", color: "bg-purple-500/20 text-purple-400" },
  certificate: { icon: "📜", color: "bg-green-500/20 text-green-400" },
  password: { icon: "🔒", color: "bg-red-500/20 text-red-400" },
  generic: { icon: "⚙️", color: "bg-gray-500/20 text-gray-400" },
};

function typeBadge(type: string) {
  const badge = TYPE_BADGES[type] ?? TYPE_BADGES.generic;
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${badge.color}`}
    >
      <span>{badge.icon}</span>
      {type.replace("_", " ")}
    </span>
  );
}

function rotationStatus(secret: Secret) {
  if (!secret.expires_at) {
    return (
      <span className="text-xs text-gray-500">No policy</span>
    );
  }
  const now = Date.now();
  const expiresAt = new Date(secret.expires_at).getTime();
  const daysUntil = (expiresAt - now) / 86_400_000;
  if (daysUntil <= 0) {
    return <span className="text-xs font-medium text-red-400">● Expired</span>;
  }
  if (daysUntil <= 30) {
    return <span className="text-xs font-medium text-yellow-400">● Approaching</span>;
  }
  return <span className="text-xs font-medium text-green-400">● OK</span>;
}

function timeAgo(dateStr: string | null): string {
  if (!dateStr) return "Never";
  const diff = Date.now() - new Date(dateStr).getTime();
  const days = Math.floor(diff / 86_400_000);
  if (days === 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 30) return `${days}d ago`;
  return `${Math.floor(days / 30)}mo ago`;
}

// ─── Component ───────────────────────────────────────────────────────

export function SecretsPage() {
  const { hasRole } = useAuth();
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState<string>("all");
  const [showCreate, setShowCreate] = useState(false);
  const [confirmAction, setConfirmAction] = useState<{
    type: "rotate" | "delete";
    secret: Secret;
  } | null>(null);
  const [page, setPage] = useState(0);
  const limit = 20;

  // ── RBAC gate ──────────────────────────────────────────────────────
  if (!hasRole("admin")) {
    return (
      <div className="flex h-64 flex-col items-center justify-center gap-2">
        <ShieldOff size={32} className="text-red-400" />
        <p className="text-red-400">Admin access required</p>
      </div>
    );
  }

  // ── Data fetching ──────────────────────────────────────────────────
  const params: Record<string, string | number> = { limit, offset: page * limit };
  if (search) params.search = search;
  if (typeFilter !== "all") params.type = typeFilter;

  const { data, isLoading, error } = useApiQuery<Secret[]>(
    ["admin-secrets", params],
    () => apiGet<Secret[]>("/secrets", params),
  );

  const secrets = data?.data ?? [];
  const total = data?.meta?.pagination?.total ?? secrets.length;

  // ── Mutations ──────────────────────────────────────────────────────
  const createMutation = useApiMutation<Secret, CreateSecretPayload>(
    (payload) => apiPost<Secret>("/secrets", payload),
    [["admin-secrets"]],
  );

  const rotateMutation = useApiMutation<Secret, string>(
    (id) => apiPost<Secret>(`/secrets/${id}/rotate`, {}),
    [["admin-secrets"]],
  );

  const deleteMutation = useApiMutation<void, string>(
    (id) => apiDelete(`/secrets/${id}`).then(() => undefined as unknown as ApiResponse<void>),
    [["admin-secrets"]],
  );

  // ── Confirm handler ────────────────────────────────────────────────
  const handleConfirm = () => {
    if (!confirmAction) return;
    if (confirmAction.type === "rotate") {
      rotateMutation.mutate(confirmAction.secret.id, {
        onSuccess: () => setConfirmAction(null),
      });
    } else {
      deleteMutation.mutate(confirmAction.secret.id, {
        onSuccess: () => setConfirmAction(null),
      });
    }
  };

  // ── Loading / Error ────────────────────────────────────────────────
  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <p className="text-gray-400">Loading secrets...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6">
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-4 text-red-400">
          Failed to load secrets.
        </div>
      </div>
    );
  }

  // ── Vault status ────────────────────────────────────────────────────
  const { data: readyData } = useApiQuery<{ vault?: { status: string } }>(
    ["vault-status"],
    () => apiGet<{ vault?: { status: string } }>("/ready"),
  );
  const vaultConnected = readyData?.data?.vault?.status === "healthy";
  const vaultChecked = !!readyData;

  return (
    <div className="p-6">
      {/* Vault Status Banner */}
      {vaultChecked && (
        vaultConnected ? (
          <div className="mb-4 rounded-lg border border-green-500/30 bg-green-500/10 px-4 py-2 text-sm text-green-400">
            🟢 Vault Connected
          </div>
        ) : (
          <div className="mb-4 rounded-lg border border-yellow-500/30 bg-yellow-500/10 px-4 py-2 text-sm text-yellow-400">
            ⚠️ Running in Stub Mode — Secrets stored in memory only
          </div>
        )
      )}

      {/* Header */}
      <div className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <KeyRound size={24} className="text-purple-400" />
          <h1 className="text-2xl font-bold text-white">Secrets Management</h1>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="flex items-center gap-2 rounded-lg bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700"
        >
          <Plus size={16} />
          Create Secret
        </button>
      </div>

      {/* Search & Filters */}
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[200px]">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
          <input
            type="text"
            placeholder="Search secrets..."
            value={search}
            onChange={(e) => { setSearch(e.target.value); setPage(0); }}
            className="w-full rounded-lg border border-[#2a2d37] bg-[#1a1d27] py-2 pl-9 pr-3 text-sm text-white placeholder-gray-500 focus:border-purple-500 focus:outline-none"
          />
        </div>
        <select
          value={typeFilter}
          onChange={(e) => { setTypeFilter(e.target.value); setPage(0); }}
          className="rounded-lg border border-[#2a2d37] bg-[#1a1d27] px-3 py-2 text-sm text-white focus:border-purple-500 focus:outline-none"
        >
          <option value="all">All Types</option>
          <option value="api_key">API Key</option>
          <option value="oauth_token">OAuth Token</option>
          <option value="certificate">Certificate</option>
          <option value="password">Password</option>
          <option value="generic">Generic</option>
        </select>
      </div>

      {/* Table */}
      <div className="rounded-lg border border-[#2a2d37] bg-[#1a1d27]">
        <div className="overflow-x-auto">
          {secrets.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12">
              <KeyRound size={32} className="mb-2 text-gray-600" />
              <p className="text-sm text-gray-500">No secrets found.</p>
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[#2a2d37] text-left text-xs text-gray-500">
                  <th className="px-4 py-2 font-medium">Name</th>
                  <th className="px-4 py-2 font-medium">Path</th>
                  <th className="px-4 py-2 font-medium">Type</th>
                  <th className="px-4 py-2 font-medium">Rotation Status</th>
                  <th className="px-4 py-2 font-medium">Last Rotated</th>
                  <th className="px-4 py-2 font-medium">Expires</th>
                  <th className="px-4 py-2 font-medium text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {secrets.map((s) => (
                  <tr key={s.id} className="border-b border-[#2a2d37] hover:bg-white/5">
                    <td className="px-4 py-2 font-medium text-white">{s.name}</td>
                    <td className="px-4 py-2 font-mono text-xs text-gray-400">{s.path}</td>
                    <td className="px-4 py-2">{typeBadge(s.type)}</td>
                    <td className="px-4 py-2">{rotationStatus(s)}</td>
                    <td className="px-4 py-2 text-gray-400">{timeAgo(s.last_rotated)}</td>
                    <td className="px-4 py-2 text-gray-400">
                      {s.expires_at ? (
                        <span
                          className={
                            new Date(s.expires_at).getTime() - Date.now() < 7 * 86_400_000
                              ? "text-red-400"
                              : ""
                          }
                        >
                          {new Date(s.expires_at).toLocaleDateString()}
                        </span>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td className="px-4 py-2 text-right">
                      <div className="flex items-center justify-end gap-1">
                        <button
                          onClick={() => setConfirmAction({ type: "rotate", secret: s })}
                          className="rounded p-1 text-gray-400 hover:bg-blue-500/20 hover:text-blue-400"
                          aria-label={`Rotate ${s.name}`}
                        >
                          <RefreshCw size={14} />
                        </button>
                        <button
                          onClick={() => setConfirmAction({ type: "delete", secret: s })}
                          className="rounded p-1 text-gray-400 hover:bg-red-500/20 hover:text-red-400"
                          aria-label={`Delete ${s.name}`}
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Pagination */}
        {total > limit && (
          <div className="flex items-center justify-between border-t border-[#2a2d37] px-4 py-3">
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
      </div>

      {/* Create Secret Modal */}
      {showCreate && (
        <CreateSecretModal
          onClose={() => setShowCreate(false)}
          onSubmit={(payload) => {
            createMutation.mutate(payload, { onSuccess: () => setShowCreate(false) });
          }}
          isPending={createMutation.isPending}
        />
      )}

      {/* Confirm Action Modal */}
      {confirmAction && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
          <div className="w-full max-w-sm rounded-lg border border-[#2a2d37] bg-[#12141e] p-6">
            <div className="mb-4 flex items-center gap-3">
              <AlertTriangle
                size={24}
                className={confirmAction.type === "delete" ? "text-red-400" : "text-yellow-400"}
              />
              <h2 className="text-lg font-semibold text-white">
                {confirmAction.type === "delete" ? "Delete Secret" : "Rotate Secret"}
              </h2>
            </div>
            <p className="mb-6 text-sm text-gray-400">
              {confirmAction.type === "delete"
                ? `Are you sure you want to delete "${confirmAction.secret.name}"? This action cannot be undone.`
                : `Rotate secret ${confirmAction.secret.name}? This will generate a new value.`}
            </p>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setConfirmAction(null)}
                className="rounded-lg border border-[#2a2d37] px-4 py-2 text-sm text-gray-400 hover:bg-white/5"
              >
                Cancel
              </button>
              <button
                onClick={handleConfirm}
                disabled={rotateMutation.isPending || deleteMutation.isPending}
                className={`rounded-lg px-4 py-2 text-sm font-medium text-white disabled:opacity-50 ${
                  confirmAction.type === "delete"
                    ? "bg-red-600 hover:bg-red-700"
                    : "bg-yellow-600 hover:bg-yellow-700"
                }`}
              >
                {confirmAction.type === "delete" ? "Delete" : "Rotate"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Create Secret Modal ─────────────────────────────────────────────

function CreateSecretModal({
  onClose,
  onSubmit,
  isPending,
}: {
  onClose: () => void;
  onSubmit: (payload: CreateSecretPayload) => void;
  isPending: boolean;
}) {
  const [name, setName] = useState("");
  const [path, setPath] = useState("");
  const [type, setType] = useState<Secret["type"]>("api_key");
  const [value, setValue] = useState("");
  const [showValue, setShowValue] = useState(false);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="w-full max-w-md rounded-lg border border-[#2a2d37] bg-[#12141e] p-6">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-white">Create Secret</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-white" aria-label="Close">
            <X size={20} />
          </button>
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (name && path && value) {
              onSubmit({ name, path, type, value });
            }
          }}
        >
          <label className="mb-1 block text-xs text-gray-400">Name</label>
          <input
            type="text"
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="mb-3 w-full rounded-lg border border-[#2a2d37] bg-[#1a1d27] px-3 py-2 text-sm text-white focus:border-purple-500 focus:outline-none"
            placeholder="my-api-key"
          />
          <label className="mb-1 block text-xs text-gray-400">Path</label>
          <input
            type="text"
            required
            value={path}
            onChange={(e) => setPath(e.target.value)}
            className="mb-3 w-full rounded-lg border border-[#2a2d37] bg-[#1a1d27] px-3 py-2 text-sm text-white focus:border-purple-500 focus:outline-none"
            placeholder="secret/data/my-service/api-key"
          />
          <label className="mb-1 block text-xs text-gray-400">Type</label>
          <select
            value={type}
            onChange={(e) => setType(e.target.value as Secret["type"])}
            className="mb-3 w-full rounded-lg border border-[#2a2d37] bg-[#1a1d27] px-3 py-2 text-sm text-white focus:border-purple-500 focus:outline-none"
          >
            <option value="api_key">API Key</option>
            <option value="oauth_token">OAuth Token</option>
            <option value="certificate">Certificate</option>
            <option value="password">Password</option>
            <option value="generic">Generic</option>
          </select>
          <label className="mb-1 block text-xs text-gray-400">Value</label>
          <div className="relative mb-4">
            <input
              type={showValue ? "text" : "password"}
              required
              value={value}
              onChange={(e) => setValue(e.target.value)}
              className="w-full rounded-lg border border-[#2a2d37] bg-[#1a1d27] px-3 py-2 pr-10 text-sm text-white focus:border-purple-500 focus:outline-none"
              placeholder="Enter secret value"
            />
            <button
              type="button"
              onClick={() => setShowValue((v) => !v)}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300"
              aria-label={showValue ? "Hide value" : "Show value"}
            >
              {showValue ? <EyeOff size={16} /> : <Eye size={16} />}
            </button>
          </div>
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
              <KeyRound size={14} />
              {isPending ? "Creating..." : "Create Secret"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
