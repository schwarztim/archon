import { useState, useEffect, useCallback } from "react";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import SecretsList from "@/components/secrets/SecretsList";
import PathTree from "@/components/secrets/PathTree";
import RotationDashboard from "@/components/secrets/RotationDashboard";
import AccessLog from "@/components/secrets/AccessLog";
import VaultStatusBanner from "@/components/secrets/VaultStatusBanner";
import RotationPolicyForm from "@/components/secrets/RotationPolicyForm";
import type { SecretMetadata, SecretType } from "@/api/secrets";
import { listSecrets, createSecret } from "@/api/secrets";

const SECRET_TYPES: { value: SecretType; label: string }[] = [
  { value: "api_key", label: "API Key" },
  { value: "oauth_token", label: "OAuth Token" },
  { value: "password", label: "Password" },
  { value: "certificate", label: "Certificate" },
  { value: "custom", label: "Custom" },
];

export default function SecretsPage() {
  const [tab, setTab] = useState("list");
  const [secrets, setSecrets] = useState<SecretMetadata[]>([]);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [accessLogPath, setAccessLogPath] = useState<string | null>(null);

  /* ── Create form state ────────────────────────────────────────── */
  const [newName, setNewName] = useState("");
  const [newPath, setNewPath] = useState("");
  const [newType, setNewType] = useState<SecretType>("custom");
  const [newValue, setNewValue] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const fetchSecrets = useCallback(async () => {
    try {
      const res = await listSecrets({ limit: 100 });
      setSecrets(res.data);
    } catch {
      /* list component handles its own errors */
    }
  }, []);

  useEffect(() => { fetchSecrets(); }, [fetchSecrets]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newPath.trim()) return;
    setCreating(true);
    setCreateError(null);
    try {
      await createSecret({
        path: newPath.trim(),
        data: { value: newValue },
        secret_type: newType,
      });
      setShowCreate(false);
      setNewName("");
      setNewPath("");
      setNewValue("");
      setNewType("custom");
      await fetchSecrets();
    } catch {
      setCreateError("Failed to create secret");
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Secrets Vault</h1>
          <p className="text-sm text-muted-foreground">
            Manage secrets, rotation policies, and access controls
          </p>
        </div>
        <button
          className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
          onClick={() => setShowCreate(!showCreate)}
          aria-label={showCreate ? "Cancel create" : "Create secret"}
        >
          {showCreate ? "Cancel" : "+ Create Secret"}
        </button>
      </div>

      {/* Vault Status Banner */}
      <VaultStatusBanner />

      {/* Create Secret Form */}
      {showCreate && (
        <form
          onSubmit={handleCreate}
          className="rounded-lg border bg-card p-4 space-y-3"
        >
          <h2 className="text-sm font-semibold">Create New Secret</h2>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <div>
              <label htmlFor="secret-name" className="block text-xs font-medium mb-1">
                Name
              </label>
              <input
                id="secret-name"
                type="text"
                value={newName}
                onChange={(e) => {
                  setNewName(e.target.value);
                  if (!newPath || newPath === newName.toLowerCase().replace(/\s+/g, "-")) {
                    setNewPath(e.target.value.toLowerCase().replace(/\s+/g, "-"));
                  }
                }}
                placeholder="My API Key"
                className="w-full rounded border px-2 py-1.5 text-sm bg-background"
                aria-label="Secret name"
              />
            </div>
            <div>
              <label htmlFor="secret-path" className="block text-xs font-medium mb-1">
                Path
              </label>
              <input
                id="secret-path"
                type="text"
                value={newPath}
                onChange={(e) => setNewPath(e.target.value)}
                placeholder="providers/openai/api-key"
                className="w-full rounded border px-2 py-1.5 text-sm bg-background font-mono"
                required
                aria-label="Secret Vault path"
              />
            </div>
            <div>
              <label htmlFor="secret-type" className="block text-xs font-medium mb-1">
                Type
              </label>
              <select
                id="secret-type"
                value={newType}
                onChange={(e) => setNewType(e.target.value as SecretType)}
                className="w-full rounded border px-2 py-1.5 text-sm bg-background"
                aria-label="Secret type"
              >
                {SECRET_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="secret-value" className="block text-xs font-medium mb-1">
                Value
              </label>
              <input
                id="secret-value"
                type="password"
                value={newValue}
                onChange={(e) => setNewValue(e.target.value)}
                placeholder="••••••••"
                className="w-full rounded border px-2 py-1.5 text-sm bg-background"
                aria-label="Secret value"
              />
            </div>
          </div>
          {createError && (
            <div className="text-xs text-destructive" role="alert">{createError}</div>
          )}
          <button
            type="submit"
            disabled={creating || !newPath.trim()}
            className="rounded bg-primary px-4 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50 transition-colors"
          >
            {creating ? "Creating…" : "Create"}
          </button>
        </form>
      )}

      {/* Main Tabs */}
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="list">Secrets</TabsTrigger>
          <TabsTrigger value="tree">Path Tree</TabsTrigger>
          <TabsTrigger value="rotation">Rotation Dashboard</TabsTrigger>
          {accessLogPath && <TabsTrigger value="access-log">Access Log</TabsTrigger>}
          {selectedPath && <TabsTrigger value="policy">Rotation Policy</TabsTrigger>}
        </TabsList>

        <TabsContent value="list">
          <SecretsList
            onSelect={(path) => {
              setSelectedPath(path);
              setTab("policy");
            }}
            onViewAccessLog={(path) => {
              setAccessLogPath(path);
              setTab("access-log");
            }}
          />
        </TabsContent>

        <TabsContent value="tree">
          <PathTree
            secrets={secrets}
            onSelectSecret={(path) => {
              setSelectedPath(path);
              setTab("policy");
            }}
          />
        </TabsContent>

        <TabsContent value="rotation">
          <RotationDashboard />
        </TabsContent>

        <TabsContent value="access-log">
          {accessLogPath ? (
            <AccessLog secretPath={accessLogPath} />
          ) : (
            <div className="rounded-lg border border-dashed p-8 text-center text-muted-foreground">
              Select a secret to view its access log.
            </div>
          )}
        </TabsContent>

        <TabsContent value="policy">
          {selectedPath ? (
            <RotationPolicyForm
              secretPath={selectedPath}
              onSaved={fetchSecrets}
            />
          ) : (
            <div className="rounded-lg border border-dashed p-8 text-center text-muted-foreground">
              Select a secret to configure its rotation policy.
            </div>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}
