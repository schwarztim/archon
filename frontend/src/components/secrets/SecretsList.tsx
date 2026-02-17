import { useState, useEffect, useCallback } from "react";
import type { SecretMetadata, SecretType } from "@/api/secrets";
import { listSecrets, deleteSecret, rotateSecret } from "@/api/secrets";

// ── Type badge colors ────────────────────────────────────────────────

const TYPE_BADGE: Record<SecretType, { label: string; className: string }> = {
  api_key: { label: "API Key", className: "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200" },
  oauth_token: { label: "OAuth", className: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200" },
  password: { label: "Password", className: "bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200" },
  certificate: { label: "Certificate", className: "bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200" },
  custom: { label: "Custom", className: "bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-200" },
};

function relativeTime(iso: string | null): string {
  if (!iso) return "Never";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "Just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

interface SecretsListProps {
  onSelect?: (path: string) => void;
  onViewAccessLog?: (path: string) => void;
}

export default function SecretsList({ onSelect, onViewAccessLog }: SecretsListProps) {
  const [secrets, setSecrets] = useState<SecretMetadata[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [rotatingPath, setRotatingPath] = useState<string | null>(null);

  const fetchSecrets = useCallback(async () => {
    try {
      setLoading(true);
      const res = await listSecrets({ limit: 100 });
      setSecrets(res.data);
    } catch {
      setError("Failed to load secrets");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchSecrets(); }, [fetchSecrets]);

  const handleRotate = async (path: string) => {
    if (!confirm(`Rotate secret "${path}"?`)) return;
    setRotatingPath(path);
    try {
      await rotateSecret(path, { reason: "Manual rotation from UI" });
      await fetchSecrets();
    } catch {
      setError(`Failed to rotate ${path}`);
    } finally {
      setRotatingPath(null);
    }
  };

  const handleDelete = async (path: string) => {
    if (!confirm(`Delete secret "${path}"? This action cannot be undone.`)) return;
    try {
      await deleteSecret(path);
      await fetchSecrets();
    } catch {
      setError(`Failed to delete ${path}`);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center p-8" role="status" aria-label="Loading secrets">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        <span className="ml-2 text-muted-foreground">Loading secrets…</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-4 text-destructive" role="alert">
        {error}
        <button className="ml-4 underline" onClick={fetchSecrets}>Retry</button>
      </div>
    );
  }

  if (secrets.length === 0) {
    return (
      <div className="rounded-lg border border-dashed p-8 text-center text-muted-foreground">
        No secrets found. Create your first secret to get started.
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border">
      <table className="w-full text-sm" aria-label="Secrets list">
        <thead className="border-b bg-muted/40">
          <tr>
            <th className="px-4 py-3 text-left font-medium">Name</th>
            <th className="px-4 py-3 text-left font-medium">Path</th>
            <th className="px-4 py-3 text-left font-medium">Type</th>
            <th className="px-4 py-3 text-left font-medium">Last Rotated</th>
            <th className="px-4 py-3 text-left font-medium">Status</th>
            <th className="px-4 py-3 text-right font-medium">Actions</th>
          </tr>
        </thead>
        <tbody>
          {secrets.map((s) => {
            const badge = TYPE_BADGE[s.secret_type] ?? TYPE_BADGE.custom;
            const name = s.path.split("/").pop() || s.path;
            return (
              <tr key={s.path} className="border-b hover:bg-muted/20 transition-colors">
                <td className="px-4 py-3 font-medium">
                  <button
                    className="hover:underline text-left"
                    onClick={() => onSelect?.(s.path)}
                    aria-label={`View ${name}`}
                  >
                    {name}
                  </button>
                </td>
                <td className="px-4 py-3 text-muted-foreground font-mono text-xs">{s.path}</td>
                <td className="px-4 py-3">
                  <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${badge.className}`}>
                    {badge.label}
                  </span>
                </td>
                <td className="px-4 py-3 text-muted-foreground">{relativeTime(s.last_rotated_at)}</td>
                <td className="px-4 py-3">
                  <ExpiryBadge meta={s} />
                </td>
                <td className="px-4 py-3 text-right space-x-2">
                  <button
                    className="rounded px-2 py-1 text-xs bg-primary/10 text-primary hover:bg-primary/20 transition-colors"
                    onClick={() => onSelect?.(s.path)}
                    aria-label={`View ${name}`}
                  >
                    View
                  </button>
                  <button
                    className="rounded px-2 py-1 text-xs bg-amber-100 text-amber-800 hover:bg-amber-200 dark:bg-amber-900 dark:text-amber-200 transition-colors disabled:opacity-50"
                    onClick={() => handleRotate(s.path)}
                    disabled={rotatingPath === s.path}
                    aria-label={`Rotate ${name}`}
                  >
                    {rotatingPath === s.path ? "Rotating…" : "Rotate"}
                  </button>
                  {onViewAccessLog && (
                    <button
                      className="rounded px-2 py-1 text-xs bg-secondary/60 text-secondary-foreground hover:bg-secondary transition-colors"
                      onClick={() => onViewAccessLog(s.path)}
                      aria-label={`Access log for ${name}`}
                    >
                      Log
                    </button>
                  )}
                  <button
                    className="rounded px-2 py-1 text-xs bg-destructive/10 text-destructive hover:bg-destructive/20 transition-colors"
                    onClick={() => handleDelete(s.path)}
                    aria-label={`Delete ${name}`}
                  >
                    Delete
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function ExpiryBadge({ meta }: { meta: SecretMetadata }) {
  if (!meta.rotation_policy_days) {
    return <span className="text-xs text-muted-foreground">—</span>;
  }

  if (meta.expires_at) {
    const daysLeft = Math.floor(
      (new Date(meta.expires_at).getTime() - Date.now()) / 86400000,
    );
    if (daysLeft < 0) {
      return (
        <span className="inline-flex items-center rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-800 dark:bg-red-900 dark:text-red-200">
          Expired
        </span>
      );
    }
    if (daysLeft <= (meta.notify_before_days ?? 14)) {
      return (
        <span className="inline-flex items-center rounded-full bg-yellow-100 px-2 py-0.5 text-xs font-medium text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200">
          {daysLeft}d left
        </span>
      );
    }
  }

  return (
    <span className="inline-flex items-center rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-800 dark:bg-green-900 dark:text-green-200">
      OK
    </span>
  );
}
