import { useState, useEffect, useCallback } from "react";
import { ToggleLeft, Loader2 } from "lucide-react";

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

interface Flag {
  name: string;
  description: string;
  enabled: boolean;
}

export function FeatureFlagsTab() {
  const [flags, setFlags] = useState<Flag[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [toggling, setToggling] = useState<string | null>(null);

  const fetchFlags = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/v1/settings/feature-flags", {
        credentials: "include",
      });
      if (res.ok) {
        const json = await res.json();
        setFlags(json.data);
      } else {
        setError("Failed to load feature flags");
      }
    } catch {
      setError("Failed to load feature flags");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchFlags();
  }, [fetchFlags]);

  const handleToggle = async (flagName: string, enabled: boolean) => {
    setToggling(flagName);
    try {
      const res = await fetch(`/api/v1/settings/feature-flags/${flagName}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ enabled }),
      });
      if (res.ok) {
        setFlags((prev) =>
          prev.map((f) => (f.name === flagName ? { ...f, enabled } : f)),
        );
      }
    } finally {
      setToggling(null);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-sm text-gray-400">
        <Loader2 size={14} className="animate-spin" /> Loading feature flags…
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-lg border border-red-500/20 bg-red-500/5 p-4 text-sm text-red-400">
        {error}
      </div>
    );
  }

  return (
    <Card icon={ToggleLeft} title="Feature Flags">
      <p className="mb-4 text-sm text-gray-400">
        Toggle experimental features. Changes take effect immediately.
      </p>
      <div className="space-y-3">
        {flags.map((flag) => (
          <div
            key={flag.name}
            className="flex items-center justify-between rounded-md border border-[#2a2d37] bg-[#0f1117] px-4 py-3"
          >
            <div>
              <span className="text-sm font-medium">{flag.name.replace(/_/g, " ")}</span>
              <p className="text-xs text-gray-500">{flag.description}</p>
            </div>
            <button
              type="button"
              role="switch"
              aria-checked={flag.enabled}
              aria-label={`Toggle ${flag.name}`}
              disabled={toggling === flag.name}
              onClick={() => handleToggle(flag.name, !flag.enabled)}
              className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors ${
                flag.enabled ? "bg-purple-500" : "bg-gray-600"
              } ${toggling === flag.name ? "opacity-50" : ""}`}
            >
              <span
                className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow transition-transform ${
                  flag.enabled ? "translate-x-5" : "translate-x-0"
                }`}
              />
            </button>
          </div>
        ))}
      </div>
    </Card>
  );
}
