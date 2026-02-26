import { useState, useRef } from "react";
import { Loader2, Upload } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { Textarea } from "@/components/ui/Textarea";
import { ClaimMapper, type ClaimMapping } from "./ClaimMapper";
import { TestConnectionButton } from "./TestConnectionButton";

interface SAMLFormProps {
  tenantId: string;
  ssoId?: string;
  initialData?: {
    name?: string;
    metadata_url?: string;
    metadata_xml?: string;
    entity_id?: string;
    acs_url?: string;
    certificate_set?: boolean;
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

export function SAMLForm({ tenantId, ssoId, initialData, onSave }: SAMLFormProps) {
  const [name, setName] = useState(initialData?.name ?? "");
  const [metadataUrl, setMetadataUrl] = useState(initialData?.metadata_url ?? "");
  const [metadataXml, setMetadataXml] = useState(initialData?.metadata_xml ?? "");
  const [entityId, setEntityId] = useState(initialData?.entity_id ?? "");
  const [certificate, setCertificate] = useState("");
  const [mappings, setMappings] = useState<ClaimMapping[]>(
    initialData?.claim_mappings ?? [
      { idp_claim: "email", archon_field: "Email" },
      { idp_claim: "displayName", archon_field: "Display Name" },
      { idp_claim: "groups", archon_field: "Groups" },
      { idp_claim: "role", archon_field: "Role" },
    ],
  );
  const [saving, setSaving] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const acsUrl = initialData?.acs_url || `${window.location.origin}/api/v1/auth/saml/acs`;

  function handleFileUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => setMetadataXml(reader.result as string);
    reader.readAsText(file);
  }

  async function handleSubmit() {
    setSaving(true);
    try {
      await onSave({
        name: name || "SAML Provider",
        protocol: "saml",
        metadata_url: metadataUrl,
        metadata_xml: metadataXml,
        entity_id: entityId,
        acs_url: acsUrl,
        ...(certificate ? { certificate } : {}),
        claim_mappings: mappings,
      });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-6 rounded-lg border border-surface-border bg-surface-raised p-6 dark:bg-surface-raised">
      <div className="space-y-4">
        <FieldRow label="Provider Name">
          <Input
            placeholder="e.g. Okta SAML"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </FieldRow>
        <FieldRow label="Metadata URL">
          <Input
            placeholder="https://idp.example.com/saml/metadata"
            value={metadataUrl}
            onChange={(e) => setMetadataUrl(e.target.value)}
          />
        </FieldRow>
        <FieldRow label="Metadata XML">
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <Button
                size="sm"
                variant="outline"
                onClick={() => fileRef.current?.click()}
              >
                <Upload size={14} className="mr-1.5" />
                Upload XML
              </Button>
              <input
                ref={fileRef}
                type="file"
                accept=".xml"
                onChange={handleFileUpload}
                className="hidden"
              />
              {metadataXml && (
                <span className="text-xs text-green-400">XML loaded ({metadataXml.length} chars)</span>
              )}
            </div>
            {metadataXml && (
              <Textarea
                value={metadataXml}
                onChange={(e) => setMetadataXml(e.target.value)}
                rows={4}
                className="font-mono text-xs"
              />
            )}
          </div>
        </FieldRow>
        <FieldRow label="Entity ID">
          <Input
            placeholder="Auto-populated from metadata or enter manually"
            value={entityId}
            onChange={(e) => setEntityId(e.target.value)}
          />
        </FieldRow>
        <FieldRow label="ACS URL">
          <Input readOnly value={acsUrl} className="bg-surface-base text-gray-500 dark:bg-surface-base" />
        </FieldRow>
        <FieldRow label="IdP Certificate (PEM)">
          <div className="flex items-center gap-2">
            {initialData?.certificate_set && !certificate ? (
              <>
                <span className="font-mono text-sm text-gray-500">Certificate stored in Vault</span>
                <Button size="sm" variant="outline" onClick={() => setCertificate(" ")}>
                  Update
                </Button>
              </>
            ) : (
              <Textarea
                placeholder={"-----BEGIN CERTIFICATE-----\n...\n-----END CERTIFICATE-----"}
                value={certificate}
                onChange={(e) => setCertificate(e.target.value)}
                rows={4}
                className="font-mono text-xs"
              />
            )}
          </div>
        </FieldRow>
      </div>

      <div>
        <h3 className="mb-3 text-sm font-semibold text-white">Attribute Mappings</h3>
        <div className="rounded-md border border-surface-border bg-surface-base p-4 dark:bg-surface-base">
          <ClaimMapper mappings={mappings} onChange={setMappings} />
        </div>
      </div>

      <div className="flex items-center gap-3">
        <Button onClick={handleSubmit} disabled={saving || (!metadataUrl && !metadataXml)}>
          {saving && <Loader2 size={14} className="mr-1.5 animate-spin" />}
          {ssoId ? "Update" : "Create"} SAML Provider
        </Button>
        {ssoId && <TestConnectionButton tenantId={tenantId} ssoId={ssoId} />}
      </div>
    </div>
  );
}
