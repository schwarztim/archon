import { useState } from "react";
import { Loader2, Plus, Check, X } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { Textarea } from "@/components/ui/Textarea";

const RESOURCES = [
  "agents", "executions", "models", "connectors", "secrets",
  "users", "settings", "governance", "dlp", "cost_management",
  "sentinel_scan", "mcp_apps",
];

const ACTIONS = ["create", "read", "update", "delete"];

function resourceLabel(r: string): string {
  return r.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

interface CustomRoleFormProps {
  initialData?: {
    id?: string;
    name?: string;
    description?: string;
    permissions?: Record<string, string[]>;
  };
  onSave: (data: {
    name: string;
    description: string;
    permissions: Record<string, string[]>;
  }) => Promise<void>;
  onCancel: () => void;
}

export function CustomRoleForm({ initialData, onSave, onCancel }: CustomRoleFormProps) {
  const [name, setName] = useState(initialData?.name ?? "");
  const [description, setDescription] = useState(initialData?.description ?? "");
  const [permissions, setPermissions] = useState<Record<string, string[]>>(
    initialData?.permissions ?? {},
  );
  const [saving, setSaving] = useState(false);

  function togglePermission(resource: string, action: string) {
    const current = permissions[resource] ?? [];
    const updated = current.includes(action)
      ? current.filter((a) => a !== action)
      : [...current, action];
    setPermissions({ ...permissions, [resource]: updated });
  }

  function toggleAll(resource: string) {
    const current = permissions[resource] ?? [];
    const allSet = ACTIONS.every((a) => current.includes(a));
    setPermissions({
      ...permissions,
      [resource]: allSet ? [] : [...ACTIONS],
    });
  }

  async function handleSubmit() {
    if (!name.trim()) return;
    setSaving(true);
    try {
      await onSave({ name, description, permissions });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-5 rounded-lg border border-[#2a2d37] bg-[#1a1d27] p-6 dark:bg-[#1a1d27]">
      <h3 className="text-sm font-semibold text-white">
        {initialData?.id ? "Edit Custom Role" : "Create Custom Role"}
      </h3>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <div>
          <Label className="text-gray-400">Role Name</Label>
          <Input
            placeholder="e.g. content_manager"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="mt-1"
          />
        </div>
        <div>
          <Label className="text-gray-400">Description</Label>
          <Textarea
            placeholder="What this role is for…"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={2}
            className="mt-1"
          />
        </div>
      </div>

      <div>
        <h4 className="mb-2 text-xs font-semibold uppercase text-gray-500">Permissions</h4>
        <div className="overflow-x-auto rounded border border-[#2a2d37]">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-[#2a2d37] bg-[#0f1117] dark:bg-[#0f1117]">
                <th className="px-3 py-2 text-left font-medium text-gray-500">Resource</th>
                <th className="px-2 py-2 text-center font-medium text-gray-500">All</th>
                {ACTIONS.map((a) => (
                  <th key={a} className="px-2 py-2 text-center font-medium capitalize text-gray-500">
                    {a}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {RESOURCES.map((resource) => {
                const current = permissions[resource] ?? [];
                const allSet = ACTIONS.every((a) => current.includes(a));
                return (
                  <tr key={resource} className="border-b border-[#2a2d37] hover:bg-white/5">
                    <td className="px-3 py-1.5 font-medium text-gray-300">
                      {resourceLabel(resource)}
                    </td>
                    <td className="px-2 py-1.5 text-center">
                      <button onClick={() => toggleAll(resource)}>
                        {allSet ? (
                          <Check size={14} className="mx-auto text-green-400" />
                        ) : (
                          <X size={14} className="mx-auto text-gray-600" />
                        )}
                      </button>
                    </td>
                    {ACTIONS.map((action) => (
                      <td key={action} className="px-2 py-1.5 text-center">
                        <button onClick={() => togglePermission(resource, action)}>
                          {current.includes(action) ? (
                            <Check size={14} className="mx-auto text-green-400" />
                          ) : (
                            <X size={14} className="mx-auto text-gray-600 hover:text-gray-400" />
                          )}
                        </button>
                      </td>
                    ))}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      <div className="flex items-center gap-3">
        <Button onClick={handleSubmit} disabled={saving || !name.trim()}>
          {saving && <Loader2 size={14} className="mr-1.5 animate-spin" />}
          <Plus size={14} className="mr-1" />
          {initialData?.id ? "Update Role" : "Create Role"}
        </Button>
        <Button variant="outline" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </div>
  );
}
