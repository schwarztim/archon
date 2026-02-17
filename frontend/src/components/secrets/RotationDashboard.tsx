import { useState, useEffect, useCallback } from "react";
import type { RotationDashboardItem, RotationStatus } from "@/api/secrets";
import { getRotationDashboard } from "@/api/secrets";

const STATUS_CONFIG: Record<
  RotationStatus,
  { label: string; className: string; icon: string }
> = {
  overdue: {
    label: "Overdue",
    className: "bg-red-100 text-red-800 border-red-200 dark:bg-red-900 dark:text-red-200 dark:border-red-800",
    icon: "🔴",
  },
  approaching: {
    label: "Approaching",
    className: "bg-yellow-100 text-yellow-800 border-yellow-200 dark:bg-yellow-900 dark:text-yellow-200 dark:border-yellow-800",
    icon: "🟡",
  },
  recently_rotated: {
    label: "Recently Rotated",
    className: "bg-green-100 text-green-800 border-green-200 dark:bg-green-900 dark:text-green-200 dark:border-green-800",
    icon: "🟢",
  },
  never_rotated: {
    label: "Never Rotated",
    className: "bg-gray-100 text-gray-600 border-gray-200 dark:bg-gray-800 dark:text-gray-300 dark:border-gray-700",
    icon: "⚪",
  },
  ok: {
    label: "OK",
    className: "bg-green-50 text-green-700 border-green-200 dark:bg-green-950 dark:text-green-300 dark:border-green-800",
    icon: "✅",
  },
};

export default function RotationDashboard() {
  const [items, setItems] = useState<RotationDashboardItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetch = useCallback(async () => {
    try {
      setLoading(true);
      const res = await getRotationDashboard();
      setItems(res.data);
    } catch {
      setError("Failed to load rotation dashboard");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetch(); }, [fetch]);

  if (loading) {
    return (
      <div className="flex items-center justify-center p-8" role="status">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        <span className="ml-2 text-muted-foreground">Loading dashboard…</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-4 text-destructive" role="alert">
        {error}
        <button className="ml-4 underline" onClick={fetch}>Retry</button>
      </div>
    );
  }

  const grouped = items.reduce<Record<RotationStatus, RotationDashboardItem[]>>(
    (acc, item) => {
      const status = item.rotation_status as RotationStatus;
      if (!acc[status]) acc[status] = [];
      acc[status].push(item);
      return acc;
    },
    {} as Record<RotationStatus, RotationDashboardItem[]>,
  );

  const order: RotationStatus[] = ["overdue", "approaching", "recently_rotated", "never_rotated", "ok"];

  return (
    <div className="space-y-6">
      {/* Summary cards */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
        {order.map((status) => {
          const cfg = STATUS_CONFIG[status];
          const count = grouped[status]?.length ?? 0;
          return (
            <div
              key={status}
              className={`rounded-lg border p-4 text-center ${cfg.className}`}
            >
              <div className="text-2xl">{cfg.icon}</div>
              <div className="mt-1 text-2xl font-bold">{count}</div>
              <div className="text-xs font-medium">{cfg.label}</div>
            </div>
          );
        })}
      </div>

      {/* Grouped lists */}
      {order.map((status) => {
        const group = grouped[status];
        if (!group || group.length === 0) return null;
        const cfg = STATUS_CONFIG[status];
        return (
          <div key={status}>
            <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold">
              <span>{cfg.icon}</span> {cfg.label}
              <span className="text-xs font-normal text-muted-foreground">
                ({group.length})
              </span>
            </h3>
            <div className="rounded-lg border overflow-hidden">
              <table className="w-full text-sm" aria-label={`${cfg.label} secrets`}>
                <thead className="border-b bg-muted/40">
                  <tr>
                    <th className="px-4 py-2 text-left font-medium">Path</th>
                    <th className="px-4 py-2 text-left font-medium">Type</th>
                    <th className="px-4 py-2 text-left font-medium">Last Rotated</th>
                    <th className="px-4 py-2 text-left font-medium">Next Rotation</th>
                    <th className="px-4 py-2 text-left font-medium">Days Left</th>
                  </tr>
                </thead>
                <tbody>
                  {group.map((item) => (
                    <tr key={item.path} className="border-b last:border-0 hover:bg-muted/20">
                      <td className="px-4 py-2 font-mono text-xs">{item.path}</td>
                      <td className="px-4 py-2 capitalize">{item.secret_type.replace("_", " ")}</td>
                      <td className="px-4 py-2 text-muted-foreground">
                        {item.last_rotated_at
                          ? new Date(item.last_rotated_at).toLocaleDateString()
                          : "Never"}
                      </td>
                      <td className="px-4 py-2 text-muted-foreground">
                        {item.next_rotation_at
                          ? new Date(item.next_rotation_at).toLocaleDateString()
                          : "—"}
                      </td>
                      <td className="px-4 py-2">
                        {item.days_until_rotation != null ? (
                          <span className={item.days_until_rotation < 0 ? "text-red-600 font-bold" : ""}>
                            {item.days_until_rotation}
                          </span>
                        ) : (
                          "—"
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        );
      })}

      {items.length === 0 && (
        <div className="rounded-lg border border-dashed p-8 text-center text-muted-foreground">
          No secrets with rotation policies configured.
        </div>
      )}
    </div>
  );
}
