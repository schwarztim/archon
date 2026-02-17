import { useState, useEffect, useCallback } from "react";
import type { SecretAccessEntry } from "@/api/secrets";
import { getAccessLog } from "@/api/secrets";

const ACTION_STYLES: Record<string, string> = {
  read: "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200",
  write: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
  rotate: "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200",
  delete: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200",
  reveal: "bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200",
};

interface AccessLogProps {
  secretPath: string;
}

export default function AccessLog({ secretPath }: AccessLogProps) {
  const [entries, setEntries] = useState<SecretAccessEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [total, setTotal] = useState(0);

  const fetchLog = useCallback(async () => {
    try {
      setLoading(true);
      const res = await getAccessLog(secretPath, { limit: 50 });
      setEntries(res.data);
      setTotal(res.meta.pagination?.total ?? res.data.length);
    } catch {
      setError("Failed to load access log");
    } finally {
      setLoading(false);
    }
  }, [secretPath]);

  useEffect(() => { fetchLog(); }, [fetchLog]);

  if (loading) {
    return (
      <div className="flex items-center justify-center p-8" role="status">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        <span className="ml-2 text-muted-foreground">Loading access log…</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-4 text-destructive" role="alert">
        {error}
        <button className="ml-4 underline" onClick={fetchLog}>Retry</button>
      </div>
    );
  }

  if (entries.length === 0) {
    return (
      <div className="rounded-lg border border-dashed p-6 text-center text-muted-foreground">
        No access log entries for <code className="font-mono text-xs">{secretPath}</code>
      </div>
    );
  }

  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-semibold">
          Access Log for <code className="font-mono text-xs">{secretPath}</code>
        </h3>
        <span className="text-xs text-muted-foreground">{total} entries</span>
      </div>
      <div className="overflow-x-auto rounded-lg border">
        <table className="w-full text-sm" aria-label="Secret access log">
          <thead className="border-b bg-muted/40">
            <tr>
              <th className="px-4 py-2 text-left font-medium">When</th>
              <th className="px-4 py-2 text-left font-medium">User</th>
              <th className="px-4 py-2 text-left font-medium">Action</th>
              <th className="px-4 py-2 text-left font-medium">Component</th>
              <th className="px-4 py-2 text-left font-medium">Details</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((e) => (
              <tr key={e.id} className="border-b last:border-0 hover:bg-muted/20">
                <td className="px-4 py-2 whitespace-nowrap text-muted-foreground">
                  {new Date(e.created_at).toLocaleString()}
                </td>
                <td className="px-4 py-2">{e.user_email || e.user_id || "System"}</td>
                <td className="px-4 py-2">
                  <span
                    className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${ACTION_STYLES[e.action] ?? "bg-gray-100 text-gray-800"}`}
                  >
                    {e.action}
                  </span>
                </td>
                <td className="px-4 py-2 text-muted-foreground text-xs">{e.component || "—"}</td>
                <td className="px-4 py-2 text-xs text-muted-foreground max-w-xs truncate">
                  {e.details || "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
