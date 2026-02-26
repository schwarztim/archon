import { Input } from "@/components/ui/Input";

interface PostgreSQLFormProps {
  config: Record<string, string>;
  onChange: (config: Record<string, string>) => void;
}

export function PostgreSQLForm({ config, onChange }: PostgreSQLFormProps) {
  const set = (key: string, value: string) => onChange({ ...config, [key]: value });

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
      <div>
        <label className="mb-1 block text-xs font-medium text-gray-600 dark:text-gray-400">Host *</label>
        <Input placeholder="localhost" value={config.host ?? ""} onChange={(e) => set("host", e.target.value)} className="bg-gray-50 dark:bg-surface-base" />
      </div>
      <div>
        <label className="mb-1 block text-xs font-medium text-gray-600 dark:text-gray-400">Port *</label>
        <Input type="number" placeholder="5432" value={config.port ?? "5432"} onChange={(e) => set("port", e.target.value)} className="bg-gray-50 dark:bg-surface-base" />
      </div>
      <div>
        <label className="mb-1 block text-xs font-medium text-gray-600 dark:text-gray-400">Database *</label>
        <Input placeholder="mydb" value={config.database ?? ""} onChange={(e) => set("database", e.target.value)} className="bg-gray-50 dark:bg-surface-base" />
      </div>
      <div>
        <label className="mb-1 block text-xs font-medium text-gray-600 dark:text-gray-400">Username *</label>
        <Input placeholder="postgres" value={config.username ?? ""} onChange={(e) => set("username", e.target.value)} className="bg-gray-50 dark:bg-surface-base" />
      </div>
      <div>
        <label className="mb-1 block text-xs font-medium text-gray-600 dark:text-gray-400">Password *</label>
        <Input type="password" placeholder="••••••" value={config.secret_credential ?? ""} onChange={(e) => set("secret_credential", e.target.value)} className="bg-gray-50 dark:bg-surface-base" />
      </div>
      <div>
        <label className="mb-1 block text-xs font-medium text-gray-600 dark:text-gray-400">SSL Mode</label>
        <select
          value={config.ssl ?? "disable"}
          onChange={(e) => set("ssl", e.target.value)}
          className="h-9 w-full rounded-md border border-gray-200 bg-gray-50 px-3 text-sm text-gray-900 dark:border-surface-border dark:bg-surface-base dark:text-white"
        >
          <option value="disable">Disable</option>
          <option value="require">Require</option>
          <option value="verify-ca">Verify CA</option>
          <option value="verify-full">Verify Full</option>
        </select>
      </div>
    </div>
  );
}
