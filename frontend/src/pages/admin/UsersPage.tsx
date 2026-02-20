import { useState } from "react";
import {
  Users,
  Plus,
  Search,
  Shield,
  ShieldCheck,
  ShieldOff,
  Mail,
  Edit,
  Trash2,
  X,
  Check,
} from "lucide-react";
import { useAuth } from "@/providers/auth-provider";
import { apiGet, apiPost, apiPut, apiDelete } from "@/api/client";
import type { ApiResponse } from "@/types";
import { useApiQuery, useApiMutation } from "@/hooks/useApi";

// ─── Types ───────────────────────────────────────────────────────────

interface ManagedUser {
  id: string;
  name: string;
  email: string;
  roles: string[];
  status: "active" | "inactive" | "suspended" | "pending";
  last_login: string | null;
  mfa_enabled: boolean;
  created_at: string;
}

interface InvitePayload {
  email: string;
  name: string;
  roles: string[];
}

interface EditPayload {
  name?: string;
  roles?: string[];
  status?: string;
}

// ─── Helpers ─────────────────────────────────────────────────────────

const STATUS_COLORS: Record<string, string> = {
  active: "bg-green-500/20 text-green-400",
  inactive: "bg-gray-500/20 text-gray-400",
  suspended: "bg-red-500/20 text-red-400",
  pending: "bg-yellow-500/20 text-yellow-400",
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

const AVAILABLE_ROLES = ["admin", "developer", "viewer", "auditor"];

// ─── Component ───────────────────────────────────────────────────────

export function UsersPage() {
  const { hasRole } = useAuth();
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [showInvite, setShowInvite] = useState(false);
  const [editUser, setEditUser] = useState<ManagedUser | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
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
  if (statusFilter !== "all") params.status = statusFilter;

  const { data, isLoading, error } = useApiQuery<ManagedUser[]>(
    ["admin-users", params],
    () => apiGet<ManagedUser[]>("/admin/users", params),
  );

  const users = data?.data ?? [];
  const total = data?.meta?.pagination?.total ?? users.length;

  // ── Mutations ──────────────────────────────────────────────────────
  const inviteMutation = useApiMutation<ManagedUser, InvitePayload>(
    (payload) => apiPost<ManagedUser>("/admin/users/invite", payload),
    [["admin-users"]],
  );

  const updateMutation = useApiMutation<ManagedUser, { id: string } & EditPayload>(
    ({ id, ...payload }) => apiPut<ManagedUser>(`/admin/users/${id}`, payload),
    [["admin-users"]],
  );

  const deleteMutation = useApiMutation<void, string>(
    (id) => apiDelete(`/admin/users/${id}`).then(() => undefined as unknown as ApiResponse<void>),
    [["admin-users"]],
  );

  const bulkMutation = useApiMutation<void, { action: string; user_ids: string[] }>(
    (payload) => apiPost<void>("/admin/users/bulk", payload),
    [["admin-users"]],
  );

  // ── Handlers ───────────────────────────────────────────────────────
  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleAll = () => {
    if (selectedIds.size === users.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(users.map((u) => u.id)));
    }
  };

  const handleBulkAction = (action: string) => {
    if (selectedIds.size === 0) return;
    bulkMutation.mutate({ action, user_ids: Array.from(selectedIds) });
    setSelectedIds(new Set());
  };

  // ── Loading / Error ────────────────────────────────────────────────
  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <p className="text-gray-400">Loading users...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6">
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-4 text-red-400">
          Failed to load users.
        </div>
      </div>
    );
  }

  return (
    <div className="p-6">
      {/* Header */}
      <div className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Users size={24} className="text-purple-400" />
          <h1 className="text-2xl font-bold text-white">User Management</h1>
        </div>
        <button
          onClick={() => setShowInvite(true)}
          className="flex items-center gap-2 rounded-lg bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700"
        >
          <Plus size={16} />
          Invite User
        </button>
      </div>

      {/* Search & Filters */}
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[200px]">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
          <input
            type="text"
            placeholder="Search by name or email..."
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
          <option value="inactive">Inactive</option>
          <option value="suspended">Suspended</option>
          <option value="pending">Pending</option>
        </select>
      </div>

      {/* Bulk Actions */}
      {selectedIds.size > 0 && (
        <div className="mb-4 flex items-center gap-3 rounded-lg border border-purple-500/30 bg-purple-500/10 p-3">
          <span className="text-sm text-purple-300">{selectedIds.size} selected</span>
          <button
            onClick={() => handleBulkAction("suspend")}
            className="rounded bg-yellow-600/20 px-3 py-1 text-xs text-yellow-400 hover:bg-yellow-600/30"
          >
            Suspend
          </button>
          <button
            onClick={() => handleBulkAction("activate")}
            className="rounded bg-green-600/20 px-3 py-1 text-xs text-green-400 hover:bg-green-600/30"
          >
            Activate
          </button>
          <button
            onClick={() => handleBulkAction("delete")}
            className="rounded bg-red-600/20 px-3 py-1 text-xs text-red-400 hover:bg-red-600/30"
          >
            Delete
          </button>
        </div>
      )}

      {/* Table */}
      <div className="rounded-lg border border-[#2a2d37] bg-[#1a1d27]">
        <div className="overflow-x-auto">
          {users.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12">
              <Users size={32} className="mb-2 text-gray-600" />
              <p className="text-sm text-gray-500">No users found.</p>
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[#2a2d37] text-left text-xs text-gray-500">
                  <th className="px-4 py-2 font-medium">
                    <input
                      type="checkbox"
                      checked={selectedIds.size === users.length && users.length > 0}
                      onChange={toggleAll}
                      className="rounded border-gray-600"
                    />
                  </th>
                  <th className="px-4 py-2 font-medium">Name</th>
                  <th className="px-4 py-2 font-medium">Email</th>
                  <th className="px-4 py-2 font-medium">Roles</th>
                  <th className="px-4 py-2 font-medium">Status</th>
                  <th className="px-4 py-2 font-medium">Last Login</th>
                  <th className="px-4 py-2 font-medium">MFA</th>
                  <th className="px-4 py-2 font-medium text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.id} className="border-b border-[#2a2d37] hover:bg-white/5">
                    <td className="px-4 py-2">
                      <input
                        type="checkbox"
                        checked={selectedIds.has(u.id)}
                        onChange={() => toggleSelect(u.id)}
                        className="rounded border-gray-600"
                      />
                    </td>
                    <td className="px-4 py-2 font-medium text-white">{u.name}</td>
                    <td className="px-4 py-2 text-gray-400">{u.email}</td>
                    <td className="px-4 py-2">
                      <div className="flex flex-wrap gap-1">
                        {u.roles.map((r) => (
                          <span
                            key={r}
                            className="rounded bg-purple-500/20 px-1.5 py-0.5 text-xs text-purple-300"
                          >
                            {r}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="px-4 py-2">{statusBadge(u.status)}</td>
                    <td className="px-4 py-2 text-gray-400">
                      {u.last_login ? new Date(u.last_login).toLocaleDateString() : "Never"}
                    </td>
                    <td className="px-4 py-2">
                      {u.mfa_enabled ? (
                        <ShieldCheck size={16} className="text-green-400" />
                      ) : (
                        <Shield size={16} className="text-gray-500" />
                      )}
                    </td>
                    <td className="px-4 py-2 text-right">
                      <div className="flex items-center justify-end gap-1">
                        <button
                          onClick={() => setEditUser(u)}
                          className="rounded p-1 text-gray-400 hover:bg-white/10 hover:text-white"
                          aria-label={`Edit ${u.name}`}
                        >
                          <Edit size={14} />
                        </button>
                        <button
                          onClick={() => {
                            if (confirm(`Delete user ${u.name}?`)) {
                              deleteMutation.mutate(u.id);
                            }
                          }}
                          className="rounded p-1 text-gray-400 hover:bg-red-500/20 hover:text-red-400"
                          aria-label={`Delete ${u.name}`}
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

      {/* Invite Modal */}
      {showInvite && (
        <InviteModal
          onClose={() => setShowInvite(false)}
          onSubmit={(payload) => {
            inviteMutation.mutate(payload, { onSuccess: () => setShowInvite(false) });
          }}
          isPending={inviteMutation.isPending}
        />
      )}

      {/* Edit Modal */}
      {editUser && (
        <EditUserModal
          user={editUser}
          onClose={() => setEditUser(null)}
          onSubmit={(payload) => {
            updateMutation.mutate(
              { id: editUser.id, ...payload },
              { onSuccess: () => setEditUser(null) },
            );
          }}
          isPending={updateMutation.isPending}
        />
      )}
    </div>
  );
}

// ─── Invite Modal ────────────────────────────────────────────────────

function InviteModal({
  onClose,
  onSubmit,
  isPending,
}: {
  onClose: () => void;
  onSubmit: (payload: InvitePayload) => void;
  isPending: boolean;
}) {
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [roles, setRoles] = useState<string[]>(["viewer"]);

  const toggleRole = (role: string) => {
    setRoles((prev) =>
      prev.includes(role) ? prev.filter((r) => r !== role) : [...prev, role],
    );
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="w-full max-w-md rounded-lg border border-[#2a2d37] bg-[#12141e] p-6">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-white">Invite User</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-white" aria-label="Close">
            <X size={20} />
          </button>
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (email && name && roles.length > 0) {
              onSubmit({ email, name, roles });
            }
          }}
        >
          <label className="mb-1 block text-xs text-gray-400">Email</label>
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="mb-3 w-full rounded-lg border border-[#2a2d37] bg-[#1a1d27] px-3 py-2 text-sm text-white focus:border-purple-500 focus:outline-none"
            placeholder="user@company.com"
          />
          <label className="mb-1 block text-xs text-gray-400">Name</label>
          <input
            type="text"
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="mb-3 w-full rounded-lg border border-[#2a2d37] bg-[#1a1d27] px-3 py-2 text-sm text-white focus:border-purple-500 focus:outline-none"
            placeholder="Full Name"
          />
          <label className="mb-1 block text-xs text-gray-400">Roles</label>
          <div className="mb-4 flex flex-wrap gap-2">
            {AVAILABLE_ROLES.map((r) => (
              <button
                key={r}
                type="button"
                onClick={() => toggleRole(r)}
                className={`rounded-full px-3 py-1 text-xs font-medium capitalize ${
                  roles.includes(r)
                    ? "bg-purple-600 text-white"
                    : "bg-[#1a1d27] text-gray-400 border border-[#2a2d37]"
                }`}
              >
                {r}
              </button>
            ))}
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
              <Mail size={14} />
              {isPending ? "Sending..." : "Send Invite"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ─── Edit User Modal ─────────────────────────────────────────────────

function EditUserModal({
  user,
  onClose,
  onSubmit,
  isPending,
}: {
  user: ManagedUser;
  onClose: () => void;
  onSubmit: (payload: EditPayload) => void;
  isPending: boolean;
}) {
  const [name, setName] = useState(user.name);
  const [roles, setRoles] = useState<string[]>(user.roles);
  const [status, setStatus] = useState(user.status);

  const toggleRole = (role: string) => {
    setRoles((prev) =>
      prev.includes(role) ? prev.filter((r) => r !== role) : [...prev, role],
    );
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="w-full max-w-md rounded-lg border border-[#2a2d37] bg-[#12141e] p-6">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-white">Edit User</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-white" aria-label="Close">
            <X size={20} />
          </button>
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            onSubmit({ name, roles, status });
          }}
        >
          <label className="mb-1 block text-xs text-gray-400">Name</label>
          <input
            type="text"
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="mb-3 w-full rounded-lg border border-[#2a2d37] bg-[#1a1d27] px-3 py-2 text-sm text-white focus:border-purple-500 focus:outline-none"
          />
          <label className="mb-1 block text-xs text-gray-400">Status</label>
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value as ManagedUser["status"])}
            className="mb-3 w-full rounded-lg border border-[#2a2d37] bg-[#1a1d27] px-3 py-2 text-sm text-white focus:border-purple-500 focus:outline-none"
          >
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
            <option value="suspended">Suspended</option>
          </select>
          <label className="mb-1 block text-xs text-gray-400">Roles</label>
          <div className="mb-4 flex flex-wrap gap-2">
            {AVAILABLE_ROLES.map((r) => (
              <button
                key={r}
                type="button"
                onClick={() => toggleRole(r)}
                className={`rounded-full px-3 py-1 text-xs font-medium capitalize ${
                  roles.includes(r)
                    ? "bg-purple-600 text-white"
                    : "bg-[#1a1d27] text-gray-400 border border-[#2a2d37]"
                }`}
              >
                {r}
              </button>
            ))}
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
              <Check size={14} />
              {isPending ? "Saving..." : "Save Changes"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
