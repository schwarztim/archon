import { ShieldCheck, UserX } from "lucide-react";
import { Button } from "@/components/ui/Button";

export interface TenantMember {
  id: string;
  name: string;
  email: string;
  role: string;
  last_login: string | null;
  status: string;
  sso_provisioned: boolean;
}

interface MemberTableProps {
  members: TenantMember[];
  onImpersonate?: (userId: string) => void;
}

function roleBadge(role: string) {
  const styles: Record<string, string> = {
    super_admin: "bg-red-500/20 text-red-400",
    tenant_admin: "bg-purple-500/20 text-purple-400",
    developer: "bg-blue-500/20 text-blue-400",
    viewer: "bg-gray-500/20 text-gray-400",
  };
  return (
    <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${styles[role] ?? "bg-gray-500/20 text-gray-400"}`}>
      {role.replace("_", " ")}
    </span>
  );
}

export function MemberTable({ members, onImpersonate }: MemberTableProps) {
  if (members.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-[#2a2d37] py-12">
        <p className="text-sm text-gray-500">No members in this tenant.</p>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-[#2a2d37] bg-[#1a1d27] dark:bg-[#1a1d27]">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-[#2a2d37] text-left text-xs text-gray-500">
            <th className="px-4 py-2 font-medium">Name</th>
            <th className="px-4 py-2 font-medium">Email</th>
            <th className="px-4 py-2 font-medium">Role</th>
            <th className="px-4 py-2 font-medium">Source</th>
            <th className="px-4 py-2 font-medium">Last Login</th>
            <th className="px-4 py-2 font-medium">Status</th>
            <th className="px-4 py-2 font-medium text-right">Actions</th>
          </tr>
        </thead>
        <tbody>
          {members.map((m) => (
            <tr key={m.id} className="border-b border-[#2a2d37] hover:bg-white/5">
              <td className="px-4 py-2 font-medium text-white">{m.name}</td>
              <td className="px-4 py-2 text-gray-400">{m.email}</td>
              <td className="px-4 py-2">{roleBadge(m.role)}</td>
              <td className="px-4 py-2">
                {m.sso_provisioned ? (
                  <span className="inline-flex items-center gap-1 rounded-full bg-blue-500/20 px-2 py-0.5 text-xs font-medium text-blue-400">
                    <ShieldCheck size={12} />
                    SSO
                  </span>
                ) : (
                  <span className="inline-block rounded-full bg-gray-500/20 px-2 py-0.5 text-xs font-medium text-gray-400">
                    Local
                  </span>
                )}
              </td>
              <td className="px-4 py-2 text-gray-500">
                {m.last_login ? new Date(m.last_login).toLocaleDateString() : "Never"}
              </td>
              <td className="px-4 py-2">
                <span
                  className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${
                    m.status === "active"
                      ? "bg-green-500/20 text-green-400"
                      : "bg-gray-500/20 text-gray-400"
                  }`}
                >
                  {m.status}
                </span>
              </td>
              <td className="px-4 py-2 text-right">
                {onImpersonate && (
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => onImpersonate(m.id)}
                    title="Impersonate user"
                    className="text-gray-500 hover:text-yellow-400"
                  >
                    <UserX size={14} />
                  </Button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
