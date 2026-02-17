import { useState } from "react";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { ClaimMapper, type ClaimMapping } from "./ClaimMapper";
import { TestConnectionButton } from "./TestConnectionButton";

interface OIDCFormProps {
  tenantId: string;
  ssoId?: string;
  initialData?: {
    name?: string;
    discovery_url?: string;
    client_id?: string;
    scopes?: string[];
    claim_mappings?: ClaimMapping[];
    client_secret_set?: boolean;
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

const DEFAULT_SCOPES = ["openid", "profile", "email", "groups", "offline_access"];

export function OIDCForm({ tenantId, ssoId, initialData, onSave }: OIDCFormProps) {
  const [name, setName] = useState(initialData?.name ?? "");
  const [discoveryUrl, setDiscoveryUrl] = useState(initialData?.discovery_url ?? "");
  const [clientId, setClientId] = useState(initialData?.client_id ?? "");
  const [clientSecret, setClientSecret] = useState("");
  const [scopes, setScopes] = useState<string[]>(initialData?.scopes ?? ["openid", "profile", "email"]);
  const [mappings, setMappings] = useState<ClaimMapping[]>(
    initialData?.claim_mappings ?? [
      { idp_claim: "email", archon_field: "Email" },
      { idp_claim: "preferred_username", archon_field: "Username" },
      { idp_claim: "given_name", archon_field: "First Name" },
      { idp_claim: "family_name", archon_field: "Last Name" },
      { idp_claim: "groups", archon_field: "Groups" },
    ],
  );
  const [saving, setSaving] = useState(false);

  function toggleScope(scope: string) {
    setScopes((prev) =>
      prev.includes(scope) ? prev.filter((s) => s !== scope) : [...prev, scope],
    );
  }

  async function handleSubmit() {
    setSaving(true);
    try {
      await onSave({
        name: name || "OIDC Provider",
        protocol: "oidc",
        discovery_url: discoveryUrl,
        client_id: clientId,
        ...(clientSecret ? { client_secret: clientSecret } : {}),
        scopes,
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
            placeholder="e.g. Keycloak Production"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </FieldRow>
        <FieldRow label="Discovery URL">
          <Input
            placeholder="https://keycloak.example.com/realms/archon/.well-known/openid-configuration"
            value={discoveryUrl}
            onChange={(e) => setDiscoveryUrl(e.target.value)}
          />
        </FieldRow>
        <FieldRow label="Client ID">
          <Input
            placeholder="archon-client-id"
            value={clientId}
            onChange={(e) => setClientId(e.target.value)}
          />
        </FieldRow>
        <FieldRow label="Client Secret">
          <div className="flex items-center gap-2">
            {initialData?.client_secret_set && !clientSecret ? (
              <>
                <span className="font-mono text-sm text-gray-500">••••••••</span>
                <Button size="sm" variant="outline" onClick={() => setClientSecret(" ")}>
                  Update
                </Button>
              </>
            ) : (
              <Input
                type="password"
                placeholder="Enter client secret (stored in Vault)"
                value={clientSecret}
                onChange={(e) => setClientSecret(e.target.value)}
              />
            )}
          </div>
        </FieldRow>
        <FieldRow label="Scopes">
          <div className="flex flex-wrap gap-2">
            {DEFAULT_SCOPES.map((scope) => (
              <button
                key={scope}
                type="button"
                onClick={() => toggleScope(scope)}
                className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${
                  scopes.includes(scope)
                    ? "bg-purple-500/20 text-purple-400"
                    : "bg-gray-500/10 text-gray-500 hover:bg-gray-500/20"
                }`}
              >
                {scope}
              </button>
            ))}
          </div>
        </FieldRow>
      </div>

      <div>
        <h3 className="mb-3 text-sm font-semibold text-white">Claim Mappings</h3>
        <div className="rounded-md border border-[#2a2d37] bg-[#0f1117] p-4 dark:bg-[#0f1117]">
          <ClaimMapper mappings={mappings} onChange={setMappings} />
        </div>
      </div>

      <div className="flex items-center gap-3">
        <Button onClick={handleSubmit} disabled={saving || !discoveryUrl || !clientId}>
          {saving && <Loader2 size={14} className="mr-1.5 animate-spin" />}
          {ssoId ? "Update" : "Create"} OIDC Provider
        </Button>
        {ssoId && <TestConnectionButton tenantId={tenantId} ssoId={ssoId} />}
      </div>
    </div>
  );
}
