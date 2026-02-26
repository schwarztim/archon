import { Input } from "@/components/ui/Input";

interface GenericRESTFormProps {
  config: Record<string, string>;
  onChange: (config: Record<string, string>) => void;
}

const AUTH_TYPES = ["None", "API Key", "Bearer", "Basic", "OAuth2"];

export function GenericRESTForm({ config, onChange }: GenericRESTFormProps) {
  const set = (key: string, value: string) => onChange({ ...config, [key]: value });
  const authType = config.auth_type ?? "None";

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div>
          <label className="mb-1 block text-xs font-medium text-gray-600 dark:text-gray-400">Base URL *</label>
          <Input placeholder="https://api.example.com" value={config.base_url ?? ""} onChange={(e) => set("base_url", e.target.value)} className="bg-gray-50 dark:bg-surface-base" />
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-gray-600 dark:text-gray-400">Auth Type</label>
          <select
            value={authType}
            onChange={(e) => set("auth_type", e.target.value)}
            className="h-9 w-full rounded-md border border-gray-200 bg-gray-50 px-3 text-sm text-gray-900 dark:border-surface-border dark:bg-surface-base dark:text-white"
          >
            {AUTH_TYPES.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
        </div>
      </div>

      {authType === "API Key" && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <label className="mb-1 block text-xs font-medium text-gray-600 dark:text-gray-400">Header Name</label>
            <Input placeholder="X-API-Key" value={config.auth_key_name ?? ""} onChange={(e) => set("auth_key_name", e.target.value)} className="bg-gray-50 dark:bg-surface-base" />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-gray-600 dark:text-gray-400">API Key</label>
            <Input type="password" placeholder="••••••" value={config.auth_key_value ?? ""} onChange={(e) => set("auth_key_value", e.target.value)} className="bg-gray-50 dark:bg-surface-base" />
          </div>
        </div>
      )}

      {authType === "Bearer" && (
        <div>
          <label className="mb-1 block text-xs font-medium text-gray-600 dark:text-gray-400">Bearer Token</label>
          <Input type="password" placeholder="••••••" value={config.auth_key_value ?? ""} onChange={(e) => set("auth_key_value", e.target.value)} className="bg-gray-50 dark:bg-surface-base" />
        </div>
      )}

      {authType === "Basic" && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <label className="mb-1 block text-xs font-medium text-gray-600 dark:text-gray-400">Username</label>
            <Input placeholder="user" value={config.username ?? ""} onChange={(e) => set("username", e.target.value)} className="bg-gray-50 dark:bg-surface-base" />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-gray-600 dark:text-gray-400">Password</label>
            <Input type="password" placeholder="••••••" value={config.secret_credential ?? ""} onChange={(e) => set("secret_credential", e.target.value)} className="bg-gray-50 dark:bg-surface-base" />
          </div>
        </div>
      )}

      <div>
        <label className="mb-1 block text-xs font-medium text-gray-600 dark:text-gray-400">Custom Headers (JSON)</label>
        <Input placeholder='{"Content-Type":"application/json"}' value={config.headers_json ?? ""} onChange={(e) => set("headers_json", e.target.value)} className="bg-gray-50 dark:bg-surface-base" />
      </div>
    </div>
  );
}
