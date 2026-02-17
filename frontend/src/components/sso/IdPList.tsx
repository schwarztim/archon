import { Edit, Trash2, Wifi, ToggleLeft, ToggleRight, Star } from "lucide-react";
import { Button } from "@/components/ui/Button";

interface IdPConfig {
  id: string;
  name: string;
  protocol: string;
  enabled: boolean;
  is_default: boolean;
  created_at: string;
}

interface IdPListProps {
  configs: IdPConfig[];
  onEdit: (id: string) => void;
  onDelete: (id: string) => void;
  onTest: (id: string) => void;
  onToggle: (id: string, enabled: boolean) => void;
  onSetDefault: (id: string) => void;
}

function protocolBadge(protocol: string) {
  const styles: Record<string, string> = {
    oidc: "bg-blue-500/20 text-blue-400",
    saml: "bg-orange-500/20 text-orange-400",
    ldap: "bg-green-500/20 text-green-400",
  };
  return (
    <span className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium uppercase ${styles[protocol] ?? "bg-gray-500/20 text-gray-400"}`}>
      {protocol}
    </span>
  );
}

export function IdPList({ configs, onEdit, onDelete, onTest, onToggle, onSetDefault }: IdPListProps) {
  if (configs.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-[#2a2d37] py-12">
        <p className="text-sm text-gray-500">No identity providers configured yet.</p>
        <p className="mt-1 text-xs text-gray-600">Add an OIDC, SAML, or LDAP provider to enable SSO.</p>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-[#2a2d37] bg-[#1a1d27] dark:bg-[#1a1d27]">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-[#2a2d37] text-left text-xs text-gray-500">
            <th className="px-4 py-2 font-medium">Name</th>
            <th className="px-4 py-2 font-medium">Type</th>
            <th className="px-4 py-2 font-medium">Status</th>
            <th className="px-4 py-2 font-medium">Default</th>
            <th className="px-4 py-2 font-medium text-right">Actions</th>
          </tr>
        </thead>
        <tbody>
          {configs.map((c) => (
            <tr key={c.id} className="border-b border-[#2a2d37] hover:bg-white/5">
              <td className="px-4 py-2 font-medium text-white">{c.name}</td>
              <td className="px-4 py-2">{protocolBadge(c.protocol)}</td>
              <td className="px-4 py-2">
                <button
                  onClick={() => onToggle(c.id, !c.enabled)}
                  className="flex items-center gap-1.5 text-xs"
                >
                  {c.enabled ? (
                    <>
                      <ToggleRight size={16} className="text-green-400" />
                      <span className="text-green-400">Active</span>
                    </>
                  ) : (
                    <>
                      <ToggleLeft size={16} className="text-gray-500" />
                      <span className="text-gray-500">Inactive</span>
                    </>
                  )}
                </button>
              </td>
              <td className="px-4 py-2">
                <button
                  onClick={() => onSetDefault(c.id)}
                  className="flex items-center"
                >
                  <Star
                    size={14}
                    className={c.is_default ? "fill-yellow-400 text-yellow-400" : "text-gray-600"}
                  />
                </button>
              </td>
              <td className="px-4 py-2">
                <div className="flex items-center justify-end gap-1">
                  <Button size="sm" variant="ghost" onClick={() => onTest(c.id)} title="Test Connection">
                    <Wifi size={14} />
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => onEdit(c.id)} title="Edit">
                    <Edit size={14} />
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => onDelete(c.id)} title="Delete" className="hover:text-red-400">
                    <Trash2 size={14} />
                  </Button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
