import { Key } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";

interface SalesforceFormProps {
  config: Record<string, string>;
  onChange: (config: Record<string, string>) => void;
  onOAuthConnect?: () => void;
}

export function SalesforceForm({ config, onChange, onOAuthConnect }: SalesforceFormProps) {
  const set = (key: string, value: string) => onChange({ ...config, [key]: value });

  return (
    <div className="space-y-4">
      <div>
        <Button
          type="button"
          variant="outline"
          className="w-full border-purple-500/50 text-purple-600 dark:text-purple-400"
          onClick={onOAuthConnect}
        >
          <Key size={14} className="mr-1.5" />
          Connect with Salesforce
        </Button>
        <p className="mt-1 text-xs text-gray-500 dark:text-gray-500">
          Securely authenticate via OAuth 2.0. Tokens are stored in Vault.
        </p>
      </div>
      <div className="max-w-md">
        <label className="mb-1 block text-xs font-medium text-gray-600 dark:text-gray-400">Instance URL (optional)</label>
        <Input
          placeholder="https://myorg.salesforce.com"
          value={config.instance_url ?? ""}
          onChange={(e) => set("instance_url", e.target.value)}
          className="bg-gray-50 dark:bg-surface-base"
        />
      </div>
    </div>
  );
}
