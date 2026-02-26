import { useState, useEffect } from "react";
import { ShieldCheck, Check, X } from "lucide-react";
import { apiGet, apiPut } from "@/api/client";

interface RBACMatrixData {
  resources: string[];
  actions: string[];
  roles: Record<
    string,
    {
      id?: string;
      permissions: Record<string, string[]>;
      is_builtin: boolean;
      description: string;
    }
  >;
}

interface RBACMatrixProps {
  onCreateRole?: () => void;
}

function resourceLabel(r: string): string {
  return r
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function roleLabel(r: string): string {
  return r.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function RBACMatrix({}: RBACMatrixProps) {
  const [data, setData] = useState<RBACMatrixData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const res = await apiGet<RBACMatrixData>("/rbac/matrix");
        setData(res.data);
      } catch {
        // silently fail
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  async function togglePermission(
    roleName: string,
    resource: string,
    action: string,
    currentlyAllowed: boolean,
  ) {
    if (!data) return;
    const role = data.roles[roleName];
    if (!role || role.is_builtin || !role.id) return;

    const currentActions = role.permissions[resource] ?? [];
    const newActions = currentlyAllowed
      ? currentActions.filter((a) => a !== action)
      : [...currentActions, action];

    const newPerms = { ...role.permissions, [resource]: newActions };

    try {
      await apiPut(`/rbac/roles/${role.id}`, { permissions: newPerms });
      setData({
        ...data,
        roles: {
          ...data.roles,
          [roleName]: { ...role, permissions: newPerms },
        },
      });
    } catch {
      // silently fail
    }
  }

  if (loading) {
    return (
      <div className="flex h-40 items-center justify-center">
        <p className="text-gray-400">Loading RBAC matrix…</p>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="flex h-40 items-center justify-center">
        <p className="text-gray-500">Failed to load RBAC matrix.</p>
      </div>
    );
  }

  const roleNames = Object.keys(data.roles);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <ShieldCheck size={20} className="text-purple-400" />
          <h3 className="text-lg font-semibold text-white">RBAC Permission Matrix</h3>
        </div>
        <div className="flex items-center gap-3 text-xs text-gray-500">
          <span className="flex items-center gap-1">
            <span className="inline-block h-3 w-3 rounded bg-green-500/30" /> Permitted
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block h-3 w-3 rounded bg-gray-500/30" /> Denied
          </span>
        </div>
      </div>

      <div className="overflow-x-auto rounded-lg border border-surface-border">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-surface-border bg-surface-base dark:bg-surface-base">
              <th className="sticky left-0 z-10 bg-surface-base px-3 py-2 text-left font-medium text-gray-500 dark:bg-surface-base">
                Resource
              </th>
              {roleNames.map((role) => (
                <th
                  key={role}
                  colSpan={data.actions.length}
                  className="border-l border-surface-border px-2 py-2 text-center font-medium text-gray-400"
                >
                  <div className="flex flex-col items-center gap-0.5">
                    <span>{roleLabel(role)}</span>
                    {data.roles[role]?.is_builtin ? (
                      <span className="text-[10px] text-gray-600">built-in</span>
                    ) : (
                      <span className="text-[10px] text-purple-400">custom</span>
                    )}
                  </div>
                </th>
              ))}
            </tr>
            <tr className="border-b border-surface-border bg-surface-base dark:bg-surface-base">
              <th className="sticky left-0 z-10 bg-surface-base px-3 py-1 dark:bg-surface-base" />
              {roleNames.map((role) =>
                data.actions.map((action) => (
                  <th
                    key={`${role}-${action}`}
                    className="border-l border-surface-border px-1 py-1 text-center text-[10px] font-normal uppercase text-gray-600"
                  >
                    {action[0]}
                  </th>
                )),
              )}
            </tr>
          </thead>
          <tbody>
            {data.resources.map((resource) => (
              <tr key={resource} className="border-b border-surface-border hover:bg-white/5">
                <td className="sticky left-0 z-10 bg-surface-raised px-3 py-1.5 font-medium text-gray-300 dark:bg-surface-raised">
                  {resourceLabel(resource)}
                </td>
                {roleNames.map((role) =>
                  data.actions.map((action) => {
                    const allowed = (data.roles[role]?.permissions[resource] ?? []).includes(action);
                    const isEditable = !data.roles[role]?.is_builtin;
                    return (
                      <td
                        key={`${role}-${resource}-${action}`}
                        className={`border-l border-surface-border px-1 py-1.5 text-center ${
                          isEditable ? "cursor-pointer hover:bg-white/10" : ""
                        }`}
                        onClick={() => isEditable && togglePermission(role, resource, action, allowed)}
                        title={`${roleLabel(role)}: ${action} ${resourceLabel(resource)}`}
                      >
                        {allowed ? (
                          <Check size={12} className="mx-auto text-green-400" />
                        ) : (
                          <X size={12} className="mx-auto text-gray-700" />
                        )}
                      </td>
                    );
                  }),
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
