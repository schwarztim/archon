import { useState } from "react";
import { setRotationPolicy } from "@/api/secrets";

interface RotationPolicyFormProps {
  secretPath: string;
  initialDays?: number;
  initialAutoRotate?: boolean;
  initialNotifyDays?: number;
  onSaved?: () => void;
}

const PRESET_DAYS = [30, 60, 90, 180, 365];

export default function RotationPolicyForm({
  secretPath,
  initialDays = 90,
  initialAutoRotate = true,
  initialNotifyDays = 14,
  onSaved,
}: RotationPolicyFormProps) {
  const [days, setDays] = useState(initialDays);
  const [autoRotate, setAutoRotate] = useState(initialAutoRotate);
  const [notifyDays, setNotifyDays] = useState(initialNotifyDays);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSuccess(false);
    setSaving(true);

    try {
      await setRotationPolicy(secretPath, {
        rotation_policy_days: days,
        auto_rotate: autoRotate,
        notify_before_days: notifyDays,
      });
      setSuccess(true);
      onSaved?.();
    } catch {
      setError("Failed to save rotation policy");
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4 rounded-lg border p-4">
      <h3 className="text-sm font-semibold">
        Rotation Policy for <code className="font-mono text-xs">{secretPath}</code>
      </h3>

      {/* Rotation period */}
      <div>
        <label htmlFor="rot-days" className="block text-sm font-medium mb-1">
          Rotation Period (days)
        </label>
        <div className="flex items-center gap-2">
          <input
            id="rot-days"
            type="number"
            min={1}
            max={365}
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="w-24 rounded border px-2 py-1 text-sm bg-background"
            aria-label="Rotation period in days"
          />
          <div className="flex gap-1">
            {PRESET_DAYS.map((d) => (
              <button
                key={d}
                type="button"
                onClick={() => setDays(d)}
                className={`rounded px-2 py-1 text-xs transition-colors ${
                  days === d
                    ? "bg-primary text-primary-foreground"
                    : "bg-muted/40 hover:bg-muted"
                }`}
                aria-label={`Set to ${d} days`}
              >
                {d}d
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Notification */}
      <div>
        <label htmlFor="notify-days" className="block text-sm font-medium mb-1">
          Notify Before Expiry (days)
        </label>
        <div className="flex items-center gap-2">
          <input
            id="notify-days"
            type="number"
            min={0}
            max={90}
            value={notifyDays}
            onChange={(e) => setNotifyDays(Number(e.target.value))}
            className="w-24 rounded border px-2 py-1 text-sm bg-background"
            aria-label="Notification days before expiry"
          />
          <span className="text-xs text-muted-foreground">days before rotation due</span>
        </div>
      </div>

      {/* Auto-rotate toggle */}
      <div className="flex items-center gap-3">
        <label htmlFor="auto-rotate" className="flex items-center gap-2 cursor-pointer">
          <input
            id="auto-rotate"
            type="checkbox"
            checked={autoRotate}
            onChange={(e) => setAutoRotate(e.target.checked)}
            className="h-4 w-4 rounded border"
            aria-label="Enable auto-rotation"
          />
          <span className="text-sm font-medium">Auto-rotate when due</span>
        </label>
      </div>

      {error && (
        <div className="rounded border border-destructive/50 bg-destructive/10 p-2 text-xs text-destructive" role="alert">
          {error}
        </div>
      )}

      {success && (
        <div className="rounded border border-green-200 bg-green-50 p-2 text-xs text-green-800 dark:bg-green-950 dark:text-green-200 dark:border-green-800" role="status">
          Rotation policy saved successfully.
        </div>
      )}

      <button
        type="submit"
        disabled={saving}
        className="rounded bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50 transition-colors"
      >
        {saving ? "Saving…" : "Save Policy"}
      </button>
    </form>
  );
}
