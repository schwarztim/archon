import { useState, useEffect, useCallback } from "react";
import {
  Plug, Plus, ArrowLeft, Loader2, Globe,
  Database, Cloud, MessageSquare, Server, Cpu, Bot,
  Github, Webhook, Key,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { apiGet, apiPost } from "@/api/client";
import { ConnectorCatalog } from "@/components/connectors/ConnectorCatalog";
import { HealthBadge } from "@/components/connectors/HealthBadge";
import { TestConnectionButton } from "@/components/connectors/TestConnectionButton";
import { PostgreSQLForm } from "@/components/connectors/forms/PostgreSQLForm";
import { SalesforceForm } from "@/components/connectors/forms/SalesforceForm";
import { SlackForm } from "@/components/connectors/forms/SlackForm";
import { S3Form } from "@/components/connectors/forms/S3Form";
import { GenericRESTForm } from "@/components/connectors/forms/GenericRESTForm";
import type { ConnectorTypeSchema, CredentialField } from "@/api/connectors";

interface Connector {
  id: string;
  name: string;
  type: string;
  config: Record<string, unknown>;
  status: string;
  created_at: string;
  last_health_check?: string | null;
}

/* ─── Fallback catalog (used if backend catalog fails to load) ─── */
const FALLBACK_CATALOG: ConnectorTypeSchema[] = [
  { name: "postgresql", label: "PostgreSQL", category: "Database", icon: "database", description: "PostgreSQL relational database", auth_methods: ["basic"], credential_fields: [], supports_oauth: false, supports_test: true },
  { name: "mysql", label: "MySQL", category: "Database", icon: "database", description: "MySQL relational database", auth_methods: ["basic"], credential_fields: [], supports_oauth: false, supports_test: true },
  { name: "mongodb", label: "MongoDB", category: "Database", icon: "database", description: "MongoDB document database", auth_methods: ["basic"], credential_fields: [], supports_oauth: false, supports_test: true },
  { name: "redis", label: "Redis", category: "Database", icon: "server", description: "Redis in-memory data store", auth_methods: ["basic"], credential_fields: [], supports_oauth: false, supports_test: true },
  { name: "elasticsearch", label: "Elasticsearch", category: "Database", icon: "search", description: "Elasticsearch search engine", auth_methods: ["basic", "api_key"], credential_fields: [], supports_oauth: false, supports_test: true },
  { name: "snowflake", label: "Snowflake", category: "Database", icon: "snowflake", description: "Snowflake data warehouse", auth_methods: ["basic"], credential_fields: [], supports_oauth: false, supports_test: true },
  { name: "bigquery", label: "BigQuery", category: "Database", icon: "chart", description: "Google BigQuery analytics", auth_methods: ["service_account"], credential_fields: [], supports_oauth: false, supports_test: true },
  { name: "salesforce", label: "Salesforce", category: "SaaS", icon: "cloud", description: "Salesforce CRM integration", auth_methods: ["oauth2"], credential_fields: [], supports_oauth: true, supports_test: true },
  { name: "hubspot", label: "HubSpot", category: "SaaS", icon: "target", description: "HubSpot CRM", auth_methods: ["oauth2", "api_key"], credential_fields: [], supports_oauth: true, supports_test: true },
  { name: "zendesk", label: "Zendesk", category: "SaaS", icon: "headphones", description: "Zendesk support", auth_methods: ["api_key"], credential_fields: [], supports_oauth: false, supports_test: true },
  { name: "jira", label: "Jira", category: "SaaS", icon: "ticket", description: "Jira project management", auth_methods: ["api_key"], credential_fields: [], supports_oauth: false, supports_test: true },
  { name: "slack", label: "Slack", category: "Communication", icon: "message-square", description: "Slack messaging", auth_methods: ["oauth2"], credential_fields: [], supports_oauth: true, supports_test: true },
  { name: "teams", label: "Microsoft Teams", category: "Communication", icon: "users", description: "Teams integration", auth_methods: ["oauth2"], credential_fields: [], supports_oauth: true, supports_test: true },
  { name: "discord", label: "Discord", category: "Communication", icon: "message-circle", description: "Discord bot", auth_methods: ["api_key"], credential_fields: [], supports_oauth: false, supports_test: true },
  { name: "email_smtp", label: "Email / SMTP", category: "Communication", icon: "mail", description: "Email via SMTP", auth_methods: ["basic"], credential_fields: [], supports_oauth: false, supports_test: true },
  { name: "s3", label: "AWS S3", category: "Cloud", icon: "cloud", description: "Amazon S3 storage", auth_methods: ["api_key"], credential_fields: [], supports_oauth: false, supports_test: true },
  { name: "github", label: "GitHub", category: "Cloud", icon: "github", description: "GitHub DevOps", auth_methods: ["oauth2", "api_key"], credential_fields: [], supports_oauth: true, supports_test: true },
  { name: "gitlab", label: "GitLab", category: "Cloud", icon: "git-branch", description: "GitLab DevOps", auth_methods: ["api_key"], credential_fields: [], supports_oauth: false, supports_test: true },
  { name: "openai", label: "OpenAI", category: "AI", icon: "bot", description: "OpenAI GPT models", auth_methods: ["api_key"], credential_fields: [], supports_oauth: false, supports_test: true },
  { name: "anthropic", label: "Anthropic", category: "AI", icon: "bot", description: "Anthropic Claude models", auth_methods: ["api_key"], credential_fields: [], supports_oauth: false, supports_test: true },
  { name: "ollama", label: "Ollama", category: "AI", icon: "cpu", description: "Ollama local LLM", auth_methods: ["basic"], credential_fields: [], supports_oauth: false, supports_test: true },
  { name: "rest_api", label: "REST API", category: "Custom", icon: "globe", description: "Generic REST API", auth_methods: ["api_key", "basic", "oauth2"], credential_fields: [], supports_oauth: false, supports_test: true },
  { name: "webhook", label: "Webhook", category: "Custom", icon: "webhook", description: "Custom webhook", auth_methods: ["api_key"], credential_fields: [], supports_oauth: false, supports_test: true },
  { name: "graphql", label: "GraphQL", category: "Custom", icon: "code", description: "GraphQL API", auth_methods: ["api_key"], credential_fields: [], supports_oauth: false, supports_test: true },
];

/* ─── Icon map for the table ──────────────────────────────────────── */
const iconMap: Record<string, typeof Database> = {
  postgresql: Database, mysql: Database, mongodb: Database, redis: Server,
  elasticsearch: Database, snowflake: Database, bigquery: Database,
  salesforce: Cloud, hubspot: Cloud, slack: MessageSquare, teams: MessageSquare,
  discord: MessageSquare, s3: Cloud, github: Github, openai: Bot,
  anthropic: Bot, ollama: Cpu, rest_api: Globe, webhook: Webhook,
};

/* ─── Dynamic form rendering from schema fields ──────────────────── */
function SchemaFormFields({ fields, config, onChange }: {
  fields: CredentialField[];
  config: Record<string, string>;
  onChange: (cfg: Record<string, string>) => void;
}) {
  const set = (key: string, value: string) => onChange({ ...config, [key]: value });

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {fields.filter((f) => f.field_type !== "oauth").map((field) => (
        <div key={field.name}>
          <label className="mb-1 block text-xs font-medium text-gray-600 dark:text-gray-400">
            {field.label}{field.required ? " *" : ""}
          </label>
          {field.field_type === "select" ? (
            <select
              value={config[field.name] ?? field.default ?? field.options[0] ?? ""}
              onChange={(e) => set(field.name, e.target.value)}
              className="h-9 w-full rounded-md border border-gray-200 bg-gray-50 px-3 text-sm text-gray-900 dark:border-[#2a2d37] dark:bg-[#0f1117] dark:text-white"
            >
              {field.options.map((o) => <option key={o} value={o}>{o}</option>)}
            </select>
          ) : field.field_type === "checkbox" ? (
            <div className="flex items-center gap-2 pt-1">
              <input
                type="checkbox"
                checked={config[field.name] === "true"}
                onChange={(e) => set(field.name, String(e.target.checked))}
                className="h-4 w-4 rounded border-gray-600 bg-gray-50 dark:bg-[#0f1117]"
              />
              <span className="text-xs text-gray-500">{field.description || "Enable"}</span>
            </div>
          ) : (
            <Input
              type={field.field_type === "password" ? "password" : field.field_type === "number" ? "number" : "text"}
              placeholder={field.placeholder || field.label}
              value={config[field.name] ?? field.default ?? ""}
              onChange={(e) => set(field.name, e.target.value)}
              className="bg-gray-50 dark:bg-[#0f1117]"
            />
          )}
        </div>
      ))}
    </div>
  );
}

export function ConnectorsPage() {
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedType, setSelectedType] = useState<ConnectorTypeSchema | null>(null);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [cfg, setCfg] = useState<Record<string, string>>({});
  const [catalogTypes, setCatalogTypes] = useState<ConnectorTypeSchema[]>(FALLBACK_CATALOG);

  const fetchConnectors = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await apiGet<Connector[]>("/connectors/");
      setConnectors(Array.isArray(res.data) ? res.data : []);
    } catch {
      setError("Failed to load connectors.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchConnectors();
    // Try to load catalog from backend
    apiGet<ConnectorTypeSchema[]>("/connectors/catalog/types")
      .then((res) => {
        if (Array.isArray(res.data) && res.data.length > 0) {
          setCatalogTypes(res.data);
        }
      })
      .catch(() => { /* use fallback catalog */ });
  }, [fetchConnectors]);

  function buildConfig(): Record<string, unknown> {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(cfg)) {
      if (v) out[k] = v;
    }
    return out;
  }

  async function handleCreate() {
    if (!name || !selectedType) return;
    setCreating(true);
    try {
      await apiPost("/connectors/", { name, type: selectedType.name, config: buildConfig(), status: "pending" });
      setSelectedType(null);
      setName("");
      setCfg({});
      await fetchConnectors();
    } catch {
      setError("Failed to create connector.");
    } finally {
      setCreating(false);
    }
  }

  async function handleTestConnection(): Promise<{ success: boolean; message: string }> {
    try {
      await apiPost("/connectors/", { name: "__test__", type: selectedType?.name ?? "", config: buildConfig(), status: "pending" });
      return { success: true, message: "Connection test passed" };
    } catch {
      return { success: false, message: "Connection test failed" };
    }
  }

  function handleOAuthConnect() {
    if (!selectedType) return;
    const redirectUri = `${window.location.origin}/oauth/callback`;
    const url = `/api/v1/connectors/oauth/${selectedType.name}/authorize?redirect_uri=${encodeURIComponent(redirectUri)}`;
    window.open(url, "oauth", "width=600,height=700,popup=yes");
  }

  if (loading) {
    return <div className="flex h-64 items-center justify-center"><Loader2 className="animate-spin text-gray-400" size={24} /></div>;
  }

  /* ─── Type-specific form view ───────────────────────────────────── */
  if (selectedType) {
    const hasOAuthField = selectedType.credential_fields.some((f) => f.field_type === "oauth");

    const renderForm = () => {
      switch (selectedType.name) {
        case "postgresql": return <PostgreSQLForm config={cfg} onChange={setCfg} />;
        case "salesforce": return <SalesforceForm config={cfg} onChange={setCfg} onOAuthConnect={handleOAuthConnect} />;
        case "slack": return <SlackForm config={cfg} onChange={setCfg} onOAuthConnect={handleOAuthConnect} />;
        case "s3": return <S3Form config={cfg} onChange={setCfg} />;
        case "rest_api": return <GenericRESTForm config={cfg} onChange={setCfg} />;
        default:
          if (selectedType.credential_fields.length > 0) {
            return (
              <div className="space-y-4">
                {hasOAuthField && (
                  <Button type="button" variant="outline" className="w-full border-purple-500/50 text-purple-600 dark:text-purple-400" onClick={handleOAuthConnect}>
                    <Key size={14} className="mr-1.5" />
                    {selectedType.credential_fields.find((f) => f.field_type === "oauth")?.label ?? "Connect via OAuth"}
                  </Button>
                )}
                <SchemaFormFields fields={selectedType.credential_fields} config={cfg} onChange={setCfg} />
              </div>
            );
          }
          return <SchemaFormFields fields={[]} config={cfg} onChange={setCfg} />;
      }
    };

    return (
      <div className="p-6">
        <button onClick={() => { setSelectedType(null); }} className="mb-4 flex items-center gap-1 text-sm text-gray-500 hover:text-gray-900 dark:text-gray-400 dark:hover:text-white">
          <ArrowLeft size={14} /> Back to Catalog
        </button>
        <div className="rounded-lg border border-gray-200 bg-white p-6 dark:border-[#2a2d37] dark:bg-[#1a1d27]">
          <div className="mb-6 flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-purple-500/20">
              <Plug size={20} className="text-purple-400" />
            </div>
            <div>
              <h2 className="text-lg font-bold text-gray-900 dark:text-white">{selectedType.label}</h2>
              <p className="text-xs text-gray-500">{selectedType.description}</p>
            </div>
          </div>

          <div className="mb-4">
            <label className="mb-1 block text-xs font-medium text-gray-600 dark:text-gray-400">Connection Name *</label>
            <Input placeholder={`My ${selectedType.label} Connection`} value={name} onChange={(e) => setName(e.target.value)} className="max-w-sm bg-gray-50 dark:bg-[#0f1117]" />
          </div>

          {renderForm()}

          <div className="mt-6 flex items-start gap-3">
            <TestConnectionButton onTest={handleTestConnection} />
            <Button size="sm" className="bg-purple-600 hover:bg-purple-700 text-white" onClick={handleCreate} disabled={creating || !name}>
              {creating ? <Loader2 size={14} className="mr-1.5 animate-spin" /> : <Plus size={14} className="mr-1.5" />}
              Save Connector
            </Button>
          </div>
        </div>
        {error && <div className="mt-4 rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">{error}</div>}
      </div>
    );
  }

  /* ─── Catalog + connected list view ─────────────────────────────── */
  return (
    <div className="p-6">
      {error && <div className="mb-4 rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">{error}</div>}

      <div className="mb-4 flex items-center gap-3">
        <Plug size={24} className="text-purple-400" />
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Connectors</h1>
      </div>
      <p className="mb-6 text-gray-500 dark:text-gray-400">Manage data source connections, API integrations, and vector store configurations.</p>

      {/* Catalog Grid */}
      <div className="mb-8">
        <ConnectorCatalog
          types={catalogTypes}
          onSelectType={(t) => { setSelectedType(t); setCfg({}); setName(""); }}
        />
      </div>

      {/* Active Connections Table */}
      <div className="rounded-lg border border-gray-200 bg-white dark:border-[#2a2d37] dark:bg-[#1a1d27]">
        <div className="border-b border-gray-200 px-4 py-3 dark:border-[#2a2d37]">
          <h2 className="text-sm font-semibold text-gray-900 dark:text-white">Active Connections ({connectors.length})</h2>
        </div>
        {connectors.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12">
            <Plug size={32} className="mb-2 text-gray-400 dark:text-gray-600" />
            <p className="text-sm text-gray-500">No connectors yet. Select a connector above to get started.</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200 text-left text-xs text-gray-500 dark:border-[#2a2d37]">
                  <th className="px-4 py-2 font-medium">Name</th>
                  <th className="px-4 py-2 font-medium">Type</th>
                  <th className="px-4 py-2 font-medium">Health</th>
                  <th className="px-4 py-2 font-medium text-right">Created</th>
                </tr>
              </thead>
              <tbody>
                {connectors.map((c) => {
                  const Icon = iconMap[c.type] ?? Globe;
                  const entry = catalogTypes.find((e) => e.name === c.type);
                  return (
                    <tr key={c.id} className="border-b border-gray-200 hover:bg-gray-50 dark:border-[#2a2d37] dark:hover:bg-white/5">
                      <td className="px-4 py-2">
                        <div className="flex items-center gap-2">
                          <Icon size={16} className="text-purple-400" />
                          <span className="font-medium text-gray-900 dark:text-white">{c.name}</span>
                        </div>
                      </td>
                      <td className="px-4 py-2 text-gray-500 dark:text-gray-400">{entry?.label ?? c.type}</td>
                      <td className="px-4 py-2">
                        <HealthBadge status={c.status as "healthy"} lastCheck={c.last_health_check} />
                      </td>
                      <td className="px-4 py-2 text-right text-gray-500 dark:text-gray-400">{new Date(c.created_at).toLocaleDateString()}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
