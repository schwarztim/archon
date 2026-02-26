import { useState, useEffect } from "react";
import { Key, Webhook, Gauge, Copy, Trash2, Plus, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { useApiKeys, useCreateApiKey, useDeleteApiKey } from "@/hooks/useSettings";

function Card({
  icon: Icon,
  title,
  children,
}: {
  icon: React.ElementType;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-lg border border-surface-border bg-surface-raised p-5">
      <h2 className="mb-4 flex items-center gap-2 text-sm font-semibold">
        <Icon size={14} className="text-purple-400" />
        {title}
      </h2>
      {children}
    </div>
  );
}

export function APITab() {
  const { data, isLoading } = useApiKeys();
  const createKey = useCreateApiKey();
  const deleteKey = useDeleteApiKey();

  const keys = data?.data ?? [];
  const [newKeyName, setNewKeyName] = useState("");
  // Track newly created key to show the full key value once
  const [newlyCreatedKey, setNewlyCreatedKey] = useState<string | null>(null);
  const [webhookUrl, setWebhookUrl] = useState("");
  const [rateLimitRpm, setRateLimitRpm] = useState(1000);

  useEffect(() => {
    if (createKey.isSuccess && createKey.data?.data?.key) {
      setNewlyCreatedKey(createKey.data.data.key);
    }
  }, [createKey.isSuccess, createKey.data]);

  const handleCreateKey = () => {
    if (!newKeyName.trim()) return;
    setNewlyCreatedKey(null);
    createKey.mutate(
      { name: newKeyName, scopes: ["read", "write"] },
      { onSuccess: () => setNewKeyName("") },
    );
  };

  const handleRevokeKey = (id: string) => {
    deleteKey.mutate(id);
  };

  return (
    <div className="space-y-6">
      <Card icon={Key} title="API Keys">
        <p className="mb-4 text-sm text-gray-400">
          Create and manage API keys for programmatic access.
        </p>

        <div className="mb-4 flex gap-2">
          <Input
            placeholder="Key name..."
            value={newKeyName}
            onChange={(e) => setNewKeyName(e.target.value)}
            className="max-w-xs"
          />
          <Button size="sm" onClick={handleCreateKey} disabled={createKey.isPending || !newKeyName.trim()}>
            {createKey.isPending ? <Loader2 size={14} className="mr-1.5 animate-spin" /> : <Plus size={14} className="mr-1.5" />}
            Create Key
          </Button>
        </div>

        {newlyCreatedKey && (
          <div className="mb-4 rounded-md border border-green-500/20 bg-green-500/5 p-3 text-sm text-green-400">
            New key created — copy it now, it won't be shown again:{" "}
            <code className="font-mono">{newlyCreatedKey}</code>
            <Button
              variant="ghost"
              size="icon"
              className="ml-2"
              onClick={() => navigator.clipboard.writeText(newlyCreatedKey)}
              title="Copy key"
            >
              <Copy size={14} />
            </Button>
          </div>
        )}

        {isLoading ? (
          <div className="flex items-center gap-2 text-sm text-gray-400">
            <Loader2 size={14} className="animate-spin" /> Loading API keys…
          </div>
        ) : keys.length === 0 ? (
          <p className="text-sm text-gray-500">No API keys created yet.</p>
        ) : (
          <div className="space-y-2">
            {keys.map((k) => (
              <div
                key={k.id}
                className="flex items-center justify-between rounded-md border border-surface-border bg-surface-base px-3 py-2"
              >
                <div>
                  <span className="text-sm font-medium">{k.name}</span>
                  <span className="ml-2 text-xs text-gray-500">
                    {k.key_prefix}...
                  </span>
                </div>
                <div className="flex gap-1">
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => handleRevokeKey(k.id)}
                    disabled={deleteKey.isPending}
                    title="Revoke key"
                  >
                    <Trash2 size={14} className="text-red-400" />
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card icon={Webhook} title="Webhook Endpoints">
        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor="webhook-url">Webhook URL</Label>
            <div className="flex gap-2">
              <Input
                id="webhook-url"
                placeholder="https://example.com/webhook"
                value={webhookUrl}
                onChange={(e) => setWebhookUrl(e.target.value)}
              />
              <Button variant="secondary" size="sm" disabled>
                Add
              </Button>
            </div>
          </div>
          <p className="text-xs text-gray-500">No webhook endpoints configured.</p>
        </div>
      </Card>

      <Card icon={Gauge} title="Rate Limits">
        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor="rate-limit">Requests per minute: {rateLimitRpm}</Label>
            <input
              id="rate-limit"
              type="range"
              min={100}
              max={10000}
              step={100}
              value={rateLimitRpm}
              onChange={(e) => setRateLimitRpm(Number(e.target.value))}
              className="w-full accent-purple-500"
              aria-label="Rate limit slider"
            />
            <div className="flex justify-between text-xs text-gray-500">
              <span>100</span>
              <span>10,000</span>
            </div>
          </div>
        </div>
      </Card>
    </div>
  );
}
