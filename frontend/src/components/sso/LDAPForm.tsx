import { useState } from "react";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { ClaimMapper, type ClaimMapping } from "./ClaimMapper";
import { TestConnectionButton } from "./TestConnectionButton";

interface LDAPFormProps {
  tenantId: string;
  ssoId?: string;
  initialData?: {
    name?: string;
    host?: string;
    port?: number;
    use_tls?: boolean;
    base_dn?: string;
    bind_dn?: string;
    bind_secret_set?: boolean;
    user_filter?: string;
    group_filter?: string;
    claim_mappings?: ClaimMapping[];
  };
  onSave: (data: Record<string, unknown>) => Promise<void>;
}

function FieldRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-[180px_1fr] sm:items-start sm:gap-4">
      <Label className="pt-2 text-gray-400">{label}</Label>
      <div>{children}</div>
    </div>
  );
}

export function LDAPForm({ tenantId, ssoId, initialData, onSave }: LDAPFormProps) {
  const [name, setName] = useState(initialData?.name ?? "");
  const [host, setHost] = useState(initialData?.host ?? "");
  const [port, setPort] = useState(initialData?.port ?? 389);
  const [useTls, setUseTls] = useState(initialData?.use_tls ?? false);
  const [baseDn, setBaseDn] = useState(initialData?.base_dn ?? "");
  const [bindDn, setBindDn] = useState(initialData?.bind_dn ?? "");
  const [bindSecret, setBindSecret] = useState("");
  const [userFilter, setUserFilter] = useState(initialData?.user_filter ?? "(objectClass=person)");
  const [groupFilter, setGroupFilter] = useState(initialData?.group_filter ?? "(objectClass=group)");
  const [mappings, setMappings] = useState<ClaimMapping[]>(
    initialData?.claim_mappings ?? [
      { idp_claim: "mail", archon_field: "Email" },
      { idp_claim: "sAMAccountName", archon_field: "Username" },
      { idp_claim: "givenName", archon_field: "First Name" },
      { idp_claim: "sn", archon_field: "Last Name" },
      { idp_claim: "memberOf", archon_field: "Groups" },
    ],
  );
  const [saving, setSaving] = useState(false);

  async function handleSubmit() {
    setSaving(true);
    try {
      await onSave({
        name: name || "LDAP/AD Provider",
        protocol: "ldap",
        host,
        port,
        use_tls: useTls,
        base_dn: baseDn,
        bind_dn: bindDn,
        ...(bindSecret ? { bind_secret: bindSecret } : {}),
        user_filter: userFilter,
        group_filter: groupFilter,
        claim_mappings: mappings,
      });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-6 rounded-lg border border-[#2a2d37] bg-[#1a1d27] p-6 dark:bg-[#1a1d27]">
      <div className="space-y-4">
        <FieldRow label="Provider Name">
          <Input
            placeholder="e.g. Active Directory"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </FieldRow>
        <FieldRow label="Host">
          <Input
            placeholder="ldap.example.com"
            value={host}
            onChange={(e) => setHost(e.target.value)}
          />
        </FieldRow>
        <FieldRow label="Port">
          <div className="flex items-center gap-4">
            <Input
              type="number"
              value={port}
              onChange={(e) => setPort(Number(e.target.value))}
              className="w-24"
            />
            <label className="flex items-center gap-2 text-sm text-gray-400">
              <input
                type="checkbox"
                checked={useTls}
                onChange={(e) => {
                  setUseTls(e.target.checked);
                  if (e.target.checked && port === 389) setPort(636);
                  if (!e.target.checked && port === 636) setPort(389);
                }}
                className="rounded border-gray-600"
              />
              Use TLS (LDAPS)
            </label>
          </div>
        </FieldRow>
        <FieldRow label="Base DN">
          <Input
            placeholder="dc=example,dc=com"
            value={baseDn}
            onChange={(e) => setBaseDn(e.target.value)}
          />
        </FieldRow>
        <FieldRow label="Bind DN">
          <Input
            placeholder="cn=admin,dc=example,dc=com"
            value={bindDn}
            onChange={(e) => setBindDn(e.target.value)}
          />
        </FieldRow>
        <FieldRow label="Bind Password">
          <div className="flex items-center gap-2">
            {initialData?.bind_secret_set && !bindSecret ? (
              <>
                <span className="font-mono text-sm text-gray-500">••••••••</span>
                <Button size="sm" variant="outline" onClick={() => setBindSecret(" ")}>
                  Update
                </Button>
              </>
            ) : (
              <Input
                type="password"
                placeholder="Enter bind password (stored in Vault)"
                value={bindSecret}
                onChange={(e) => setBindSecret(e.target.value)}
              />
            )}
          </div>
        </FieldRow>
        <FieldRow label="User Filter">
          <Input
            placeholder="(objectClass=person)"
            value={userFilter}
            onChange={(e) => setUserFilter(e.target.value)}
          />
        </FieldRow>
        <FieldRow label="Group Filter">
          <Input
            placeholder="(objectClass=group)"
            value={groupFilter}
            onChange={(e) => setGroupFilter(e.target.value)}
          />
        </FieldRow>
      </div>

      <div>
        <h3 className="mb-3 text-sm font-semibold text-white">Attribute Mappings</h3>
        <div className="rounded-md border border-[#2a2d37] bg-[#0f1117] p-4 dark:bg-[#0f1117]">
          <ClaimMapper mappings={mappings} onChange={setMappings} />
        </div>
      </div>

      <div className="flex items-center gap-3">
        <Button onClick={handleSubmit} disabled={saving || !host || !baseDn}>
          {saving && <Loader2 size={14} className="mr-1.5 animate-spin" />}
          {ssoId ? "Update" : "Create"} LDAP Provider
        </Button>
        {ssoId && <TestConnectionButton tenantId={tenantId} ssoId={ssoId} />}
      </div>
    </div>
  );
}
