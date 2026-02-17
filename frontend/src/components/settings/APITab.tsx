import { useState } from "react";
import { Key, Webhook, Gauge, Copy, Trash2, Plus, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";

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
    <div className="rounded-lg border border-[#2a2d37] bg-[#1a1d27] p-5">
      <h2 className="mb-4 flex items-center gap-2 text-sm font-semibold">
        <Icon size={14} className="text-purple-400" />
        {title}
      </h2>
      {children}
    </div>
  );
}

interface ApiKeyItem {
  id: string;
  name: string;
  key_prefix: string;
  key?: string;
  scopes: string[];
  created_at: string;
}

export function APITab() {
  const [keys, setKeys] = useState<ApiKeyItem[]>([]);
  const [newKeyName, setNewKeyName] = useState("");
  const [creating, setCreating] = useState(false);
  const [webhookUrl, setWebhookUrl] = useState("");
  const [rateLimitRpm, setRateLimitRpm] = useState(1000);

  const handleCreateKey = async () => {
    if (!newKeyName.trim()) return;
    setCreating(true);
    try {
      const res = await fetch("/api/v1/settings/api-keys", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ name: newKeyName, scopes: ["read", "write"] }),
      });
      if (res.ok) {
        const json = await res.json();
        setKeys((prev) => [...prev, json.data]);
        setNewKeyName("");
      }
    } finally {
      setCreating(false);
    }
  };

  const handleRevokeKey = async (id: string) => {
    const res = await fetch(`/api/v1/settings/api-keys/${id}`, {
      method: "DELETE",
      credentials: "include",
    });
    if (res.ok) {
      setKeys((prev) => prev.filter((k) => k.id !== id));
    }
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
          <Button size="sm" onClick={handleCreateKey} disabled={creating || !newKeyName.trim()}>
            {creating ? <Loader2 size={14} className="mr-1.5 animate-spin" /> : <Plus size={14} className="mr-1.5" />}
            Create Key
          </Button>
        </div>

        {keys.length === 0 ? (
          <p className="text-sm text-gray-500">No API keys created yet.</p>
        ) : (
          <div className="space-y-2">
            {keys.map((k) => (
              <div
                key={k.id}
                className="flex items-center justify-between rounded-md border border-[#2a2d37] bg-[#0f1117] px-3 py-2"
              >
                <div>
                  <span className="text-sm font-medium">{k.name}</span>
                  <span className="ml-2 text-xs text-gray-500">
                    {k.key ? k.key : `${k.key_prefix}...`}
                  </span>
                </div>
                <div className="flex gap-1">
                  {k.key && (
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => navigator.clipboard.writeText(k.key!)}
                      title="Copy key"
                    >
                      <Copy size={14} />
                    </Button>
                  )}
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => handleRevokeKey(k.id)}
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
