import { useState, useEffect } from "react";
import {
  ShieldCheck,
  Loader2,
  CheckCircle2,
  XCircle,
  X,
  Plus,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { Textarea } from "@/components/ui/Textarea";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { apiGet, apiPut, apiPost } from "@/api/client";

// ── Types ──────────────────────────────────────────────────────────

interface ClaimMapping {
  email_claim: string;
  name_claim: string;
  role_claim: string;
  tenant_claim: string;
}

interface OIDCConfig {
  discovery_url: string;
  client_id: string;
  client_secret_set: boolean;
  scopes: string[];
  redirect_uri: string;
  claim_mapping: ClaimMapping;
}

interface SAMLAttributeMapping {
  email_attr: string;
  name_attr: string;
  role_attr: string;
  tenant_attr: string;
}

interface SAMLConfig {
  metadata_url: string;
  entity_id: string;
  acs_url: string;
  certificate: string;
  attribute_mapping: SAMLAttributeMapping;
}

interface SSOConfigData {
  protocol: string | null;
  oidc: OIDCConfig;
  saml: SAMLConfig;
}

// ── Helpers ────────────────────────────────────────────────────────

const defaultOidc: OIDCConfig = {
  discovery_url: "",
  client_id: "",
  client_secret_set: false,
  scopes: ["openid", "profile", "email"],
  redirect_uri: `${window.location.origin}/auth/callback`,
  claim_mapping: {
    email_claim: "email",
    name_claim: "name",
    role_claim: "roles",
    tenant_claim: "tenant_id",
  },
};

const defaultSaml: SAMLConfig = {
  metadata_url: "",
  entity_id: "",
  acs_url: `${window.location.origin}/api/v1/auth/saml/acs`,
  certificate: "",
  attribute_mapping: {
    email_attr: "email",
    name_attr: "name",
    role_attr: "roles",
    tenant_attr: "tenant_id",
  },
};

function FieldRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-[180px_1fr] sm:items-center sm:gap-4">
      <Label className="text-gray-400">{label}</Label>
      <div>{children}</div>
    </div>
  );
}

// ── Component ──────────────────────────────────────────────────────

export function SSOConfigPage() {
  const [protocol, setProtocol] = useState<string>("oidc");
  const [oidc, setOidc] = useState<OIDCConfig>(defaultOidc);
  const [saml, setSaml] = useState<SAMLConfig>(defaultSaml);
  const [clientSecret, setClientSecret] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ status: string; message: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [newScope, setNewScope] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const res = await apiGet<SSOConfigData>("/sso/config");
        const d = res.data;
        if (d.protocol) setProtocol(d.protocol);
        if (d.oidc) setOidc({ ...defaultOidc, ...d.oidc, redirect_uri: defaultOidc.redirect_uri });
        if (d.saml) setSaml({ ...defaultSaml, ...d.saml, acs_url: defaultSaml.acs_url });
      } catch {
        setError("Failed to load SSO configuration.");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  async function handleSave() {
    setSaving(true);
    setError(null);
    setSuccess(null);
    try {
      await apiPut("/sso/config", {
        protocol,
        oidc,
        saml,
        ...(clientSecret ? { client_secret: clientSecret } : {}),
      });
      setClientSecret("");
      setSuccess("SSO configuration saved.");
      // Re-fetch to get updated client_secret_set flag
      const res = await apiGet<SSOConfigData>("/sso/config");
      if (res.data.oidc) setOidc((prev) => ({ ...prev, client_secret_set: res.data.oidc.client_secret_set }));
    } catch {
      setError("Failed to save SSO configuration.");
    } finally {
      setSaving(false);
    }
  }

  async function handleTestConnection() {
    setTesting(true);
    setTestResult(null);
    try {
      const res = await apiPost<{ status: string; message: string }>("/sso/test-connection", {});
      setTestResult(res.data);
    } catch {
      setTestResult({ status: "error", message: "Connection test failed." });
    } finally {
      setTesting(false);
    }
  }

  function addScope() {
    const s = newScope.trim();
    if (s && !oidc.scopes.includes(s)) {
      setOidc((prev) => ({ ...prev, scopes: [...prev.scopes, s] }));
    }
    setNewScope("");
  }

  function removeScope(scope: string) {
    setOidc((prev) => ({ ...prev, scopes: prev.scopes.filter((s) => s !== scope) }));
  }

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <p className="text-gray-400">Loading...</p>
      </div>
    );
  }

  return (
    <div className="p-6">
      {error && (
        <div className="mb-4 rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">{error}</div>
      )}
      {success && (
        <div className="mb-4 rounded-lg border border-green-500/30 bg-green-500/10 p-3 text-sm text-green-400">{success}</div>
      )}

      <div className="mb-4 flex items-center gap-3">
        <ShieldCheck size={24} className="text-purple-400" />
        <h1 className="text-2xl font-bold text-white">SSO Configuration</h1>
      </div>
      <p className="mb-6 text-gray-400">
        Configure single sign-on with your identity provider using OIDC or SAML.
      </p>

      <Tabs value={protocol} onValueChange={setProtocol}>
        <TabsList className="bg-[#1a1d27]">
          <TabsTrigger value="oidc">OIDC</TabsTrigger>
          <TabsTrigger value="saml">SAML</TabsTrigger>
        </TabsList>

        {/* ── OIDC Form ─────────────────────────────────────────── */}
        <TabsContent value="oidc">
          <div className="space-y-6 rounded-lg border border-[#2a2d37] bg-[#1a1d27] p-6">
            <div className="space-y-4">
              <FieldRow label="Discovery URL">
                <Input
                  placeholder="https://idp.example.com/.well-known/openid-configuration"
                  value={oidc.discovery_url}
                  onChange={(e) => setOidc((p) => ({ ...p, discovery_url: e.target.value }))}
                />
              </FieldRow>

              <FieldRow label="Client ID">
                <Input
                  placeholder="archon-client-id"
                  value={oidc.client_id}
                  onChange={(e) => setOidc((p) => ({ ...p, client_id: e.target.value }))}
                />
              </FieldRow>

              <FieldRow label="Client Secret">
                <div className="flex items-center gap-2">
                  {oidc.client_secret_set && !clientSecret ? (
                    <>
                      <span className="font-mono text-sm text-gray-500">••••••••</span>
                      <Button size="sm" variant="outline" onClick={() => setClientSecret(" ")}>
                        Update
                      </Button>
                    </>
                  ) : (
                    <Input
                      type="password"
                      placeholder="Enter client secret"
                      value={clientSecret}
                      onChange={(e) => setClientSecret(e.target.value)}
                    />
                  )}
                </div>
              </FieldRow>

              <FieldRow label="Scopes">
                <div className="flex flex-wrap items-center gap-2">
                  {oidc.scopes.map((s) => (
                    <span
                      key={s}
                      className="inline-flex items-center gap-1 rounded-full bg-purple-500/20 px-2.5 py-0.5 text-xs font-medium text-purple-400"
                    >
                      {s}
                      <button type="button" onClick={() => removeScope(s)} className="hover:text-white">
                        <X size={12} />
                      </button>
                    </span>
                  ))}
                  <div className="flex items-center gap-1">
                    <Input
                      placeholder="Add scope"
                      value={newScope}
                      onChange={(e) => setNewScope(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), addScope())}
                      className="h-7 w-28 text-xs"
                    />
                    <Button size="sm" variant="ghost" onClick={addScope} className="h-7 px-1.5">
                      <Plus size={14} />
                    </Button>
                  </div>
                </div>
              </FieldRow>

              <FieldRow label="Redirect URI">
                <Input readOnly value={oidc.redirect_uri} className="bg-[#0f1117] text-gray-500" />
              </FieldRow>
            </div>

            {/* Claim Mapping */}
            <div>
              <h3 className="mb-3 text-sm font-semibold text-white">Claim Mapping</h3>
              <div className="space-y-2 rounded-md border border-[#2a2d37] bg-[#0f1117] p-4">
                {(
                  [
                    ["email", "email_claim", "email"],
                    ["name", "name_claim", "name"],
                    ["role", "role_claim", "roles"],
                    ["tenant", "tenant_claim", "tenant_id"],
                  ] as const
                ).map(([label, field, placeholder]) => (
                  <div key={field} className="grid grid-cols-[100px_20px_1fr] items-center gap-2">
                    <span className="text-xs font-medium text-gray-400">{label}</span>
                    <span className="text-center text-gray-600">→</span>
                    <Input
                      placeholder={placeholder}
                      value={oidc.claim_mapping[field]}
                      onChange={(e) =>
                        setOidc((p) => ({
                          ...p,
                          claim_mapping: { ...p.claim_mapping, [field]: e.target.value },
                        }))
                      }
                      className="h-8 text-xs"
                    />
                  </div>
                ))}
              </div>
            </div>

            {/* Actions */}
            <div className="flex items-center gap-3">
              <Button onClick={handleSave} disabled={saving}>
                {saving && <Loader2 size={14} className="mr-1.5 animate-spin" />}
                Save
              </Button>
              <Button variant="outline" onClick={handleTestConnection} disabled={testing}>
                {testing && <Loader2 size={14} className="mr-1.5 animate-spin" />}
                Test Connection
              </Button>
              {testResult && (
                <span className={`flex items-center gap-1 text-sm ${testResult.status === "success" ? "text-green-400" : "text-red-400"}`}>
                  {testResult.status === "success" ? <CheckCircle2 size={14} /> : <XCircle size={14} />}
                  {testResult.message}
                </span>
              )}
            </div>
          </div>
        </TabsContent>

        {/* ── SAML Form ─────────────────────────────────────────── */}
        <TabsContent value="saml">
          <div className="space-y-6 rounded-lg border border-[#2a2d37] bg-[#1a1d27] p-6">
            <div className="space-y-4">
              <FieldRow label="Metadata URL">
                <Input
                  placeholder="https://idp.example.com/saml/metadata"
                  value={saml.metadata_url}
                  onChange={(e) => setSaml((p) => ({ ...p, metadata_url: e.target.value }))}
                />
              </FieldRow>

              <FieldRow label="Entity ID">
                <Input
                  placeholder="urn:archon:sp"
                  value={saml.entity_id}
                  onChange={(e) => setSaml((p) => ({ ...p, entity_id: e.target.value }))}
                />
              </FieldRow>

              <FieldRow label="ACS URL">
                <Input readOnly value={saml.acs_url} className="bg-[#0f1117] text-gray-500" />
              </FieldRow>

              <FieldRow label="Certificate (PEM)">
                <Textarea
                  placeholder="-----BEGIN CERTIFICATE-----&#10;...&#10;-----END CERTIFICATE-----"
                  value={saml.certificate}
                  onChange={(e) => setSaml((p) => ({ ...p, certificate: e.target.value }))}
                  rows={5}
                  className="font-mono text-xs"
                />
              </FieldRow>
            </div>

            {/* Attribute Mapping */}
            <div>
              <h3 className="mb-3 text-sm font-semibold text-white">Attribute Mapping</h3>
              <div className="space-y-2 rounded-md border border-[#2a2d37] bg-[#0f1117] p-4">
                {(
                  [
                    ["email", "email_attr", "email"],
                    ["name", "name_attr", "name"],
                    ["role", "role_attr", "roles"],
                    ["tenant", "tenant_attr", "tenant_id"],
                  ] as const
                ).map(([label, field, placeholder]) => (
                  <div key={field} className="grid grid-cols-[100px_20px_1fr] items-center gap-2">
                    <span className="text-xs font-medium text-gray-400">{label}</span>
                    <span className="text-center text-gray-600">→</span>
                    <Input
                      placeholder={placeholder}
                      value={saml.attribute_mapping[field]}
                      onChange={(e) =>
                        setSaml((p) => ({
                          ...p,
                          attribute_mapping: { ...p.attribute_mapping, [field]: e.target.value },
                        }))
                      }
                      className="h-8 text-xs"
                    />
                  </div>
                ))}
              </div>
            </div>

            {/* Actions */}
            <div className="flex items-center gap-3">
              <Button onClick={handleSave} disabled={saving}>
                {saving && <Loader2 size={14} className="mr-1.5 animate-spin" />}
                Save
              </Button>
              <Button variant="outline" onClick={handleTestConnection} disabled={testing}>
                {testing && <Loader2 size={14} className="mr-1.5 animate-spin" />}
                Test Connection
              </Button>
              {testResult && (
                <span className={`flex items-center gap-1 text-sm ${testResult.status === "success" ? "text-green-400" : "text-red-400"}`}>
                  {testResult.status === "success" ? <CheckCircle2 size={14} /> : <XCircle size={14} />}
                  {testResult.message}
                </span>
              )}
            </div>
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}
