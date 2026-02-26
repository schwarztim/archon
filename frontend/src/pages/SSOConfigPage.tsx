import { useState, useEffect } from "react";
import {
  ShieldCheck,
  Plus,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { apiGet, apiPut, apiPost, apiDelete } from "@/api/client";
import { OIDCForm } from "@/components/sso/OIDCForm";
import { SAMLForm } from "@/components/sso/SAMLForm";
import { LDAPForm } from "@/components/sso/LDAPForm";
import { IdPList } from "@/components/sso/IdPList";
import { RBACMatrix } from "@/components/rbac/RBACMatrix";
import { CustomRoleForm } from "@/components/rbac/CustomRoleForm";

// ── Types ──────────────────────────────────────────────────────────

interface IdPConfig {
  id: string;
  name: string;
  protocol: string;
  enabled: boolean;
  is_default: boolean;
  created_at: string;
  [key: string]: unknown;
}

// ── Component ──────────────────────────────────────────────────────

export function SSOConfigPage() {
  const [activeTab, setActiveTab] = useState<string>("providers");
  const [addProtocol, setAddProtocol] = useState<string | null>(null);
  const [configs, setConfigs] = useState<IdPConfig[]>([]);
  const [editId, setEditId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [showRoleForm, setShowRoleForm] = useState(false);

  // Use a default tenant id for the current session
  const tenantId = "current";

  useEffect(() => {
    void loadConfigs();
  }, []);

  async function loadConfigs() {
    setLoading(true);
    try {
      const res = await apiGet<IdPConfig[]>(`/tenants/${tenantId}/sso`);
      setConfigs(Array.isArray(res.data) ? res.data : []);
    } catch {
      // No configs yet is fine
      setConfigs([]);
    } finally {
      setLoading(false);
    }
  }

  async function handleSaveProvider(data: Record<string, unknown>) {
    setError(null);
    setSuccess(null);
    try {
      if (editId) {
        await apiPut(`/tenants/${tenantId}/sso/${editId}`, data);
        setSuccess("Identity provider updated.");
      } else {
        await apiPost(`/tenants/${tenantId}/sso`, data);
        setSuccess("Identity provider created.");
      }
      setAddProtocol(null);
      setEditId(null);
      await loadConfigs();
    } catch {
      setError("Failed to save identity provider configuration.");
    }
  }

  async function handleDelete(id: string) {
    try {
      await apiDelete(`/tenants/${tenantId}/sso/${id}`);
      await loadConfigs();
      setSuccess("Identity provider deleted.");
    } catch {
      setError("Failed to delete identity provider.");
    }
  }

  async function handleToggle(id: string, enabled: boolean) {
    try {
      await apiPut(`/tenants/${tenantId}/sso/${id}`, { enabled });
      await loadConfigs();
    } catch {
      setError("Failed to update identity provider.");
    }
  }

  async function handleSetDefault(id: string) {
    try {
      await apiPut(`/tenants/${tenantId}/sso/${id}`, { is_default: true });
      await loadConfigs();
    } catch {
      setError("Failed to set default identity provider.");
    }
  }

  async function handleCreateRole(data: {
    name: string;
    description: string;
    permissions: Record<string, string[]>;
  }) {
    try {
      await apiPost("/rbac/roles", data);
      setShowRoleForm(false);
      setSuccess("Custom role created.");
    } catch {
      setError("Failed to create custom role.");
    }
  }

  function handleEdit(id: string) {
    const config = configs.find((c) => c.id === id);
    if (config) {
      setEditId(id);
      setAddProtocol(config.protocol);
    }
  }

  async function handleTest(id: string) {
    try {
      const res = await apiPost<{ status: string; message: string }>(
        `/tenants/${tenantId}/sso/${id}/test`,
        {},
      );
      if (res.data.status === "success") {
        setSuccess(res.data.message);
      } else {
        setError(res.data.message);
      }
    } catch {
      setError("Connection test failed.");
    }
  }

  const editConfig = editId ? configs.find((c) => c.id === editId) : undefined;

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
        <h1 className="text-2xl font-bold text-white">SSO & Identity</h1>
      </div>
      <p className="mb-6 text-gray-400">
        Configure identity providers (OIDC, SAML, LDAP), manage roles, and view the RBAC permission matrix.
      </p>

      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList className="bg-surface-raised dark:bg-surface-raised">
          <TabsTrigger value="providers">Identity Providers</TabsTrigger>
          <TabsTrigger value="rbac">RBAC Matrix</TabsTrigger>
          <TabsTrigger value="roles">Custom Roles</TabsTrigger>
        </TabsList>

        {/* ── Identity Providers Tab ──────────────────────────── */}
        <TabsContent value="providers">
          <div className="space-y-4">
            {!addProtocol && (
              <>
                <div className="flex items-center gap-2">
                  <Button size="sm" onClick={() => setAddProtocol("oidc")}>
                    <Plus size={14} className="mr-1.5" />Add OIDC
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => setAddProtocol("saml")}>
                    <Plus size={14} className="mr-1.5" />Add SAML
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => setAddProtocol("ldap")}>
                    <Plus size={14} className="mr-1.5" />Add LDAP
                  </Button>
                </div>
                <IdPList
                  configs={configs}
                  onEdit={handleEdit}
                  onDelete={handleDelete}
                  onTest={handleTest}
                  onToggle={handleToggle}
                  onSetDefault={handleSetDefault}
                />
              </>
            )}

            {addProtocol === "oidc" && (
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-semibold text-white">
                    {editId ? "Edit OIDC Provider" : "Add OIDC Provider"}
                  </h3>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => { setAddProtocol(null); setEditId(null); }}
                  >
                    Cancel
                  </Button>
                </div>
                <OIDCForm
                  tenantId={tenantId}
                  ssoId={editId ?? undefined}
                  initialData={editConfig as Record<string, unknown> | undefined}
                  onSave={handleSaveProvider}
                />
              </div>
            )}

            {addProtocol === "saml" && (
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-semibold text-white">
                    {editId ? "Edit SAML Provider" : "Add SAML Provider"}
                  </h3>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => { setAddProtocol(null); setEditId(null); }}
                  >
                    Cancel
                  </Button>
                </div>
                <SAMLForm
                  tenantId={tenantId}
                  ssoId={editId ?? undefined}
                  initialData={editConfig as Record<string, unknown> | undefined}
                  onSave={handleSaveProvider}
                />
              </div>
            )}

            {addProtocol === "ldap" && (
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-semibold text-white">
                    {editId ? "Edit LDAP Provider" : "Add LDAP Provider"}
                  </h3>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => { setAddProtocol(null); setEditId(null); }}
                  >
                    Cancel
                  </Button>
                </div>
                <LDAPForm
                  tenantId={tenantId}
                  ssoId={editId ?? undefined}
                  initialData={editConfig as Record<string, unknown> | undefined}
                  onSave={handleSaveProvider}
                />
              </div>
            )}
          </div>
        </TabsContent>

        {/* ── RBAC Matrix Tab ─────────────────────────────────── */}
        <TabsContent value="rbac">
          <RBACMatrix onCreateRole={() => { setActiveTab("roles"); setShowRoleForm(true); }} />
        </TabsContent>

        {/* ── Custom Roles Tab ────────────────────────────────── */}
        <TabsContent value="roles">
          <div className="space-y-4">
            {!showRoleForm && (
              <Button size="sm" onClick={() => setShowRoleForm(true)}>
                <Plus size={14} className="mr-1.5" />Create Custom Role
              </Button>
            )}
            {showRoleForm && (
              <CustomRoleForm
                onSave={handleCreateRole}
                onCancel={() => setShowRoleForm(false)}
              />
            )}
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}
