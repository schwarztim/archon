import { ArrowLeftRight } from "lucide-react";
import type { ConfigDiff as ConfigDiffType } from "@/types/models";

interface DiffViewProps {
  diff: ConfigDiffType | null;
  loading: boolean;
}

export function DiffView({ diff, loading }: DiffViewProps) {
  if (loading) {
    return (
      <div className="flex h-32 items-center justify-center text-gray-500 text-sm">
        Loading diff…
      </div>
    );
  }

  if (!diff) {
    return (
      <div className="flex h-32 items-center justify-center text-gray-500 text-sm">
        Select two environments to compare
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-surface-border bg-surface-raised p-4">
      <div className="mb-3 flex items-center gap-2">
        <ArrowLeftRight size={14} className="text-purple-400" />
        <span className="text-sm font-medium text-white">
          {diff.source_env} → {diff.target_env}
        </span>
      </div>

      <div className="mb-3 flex gap-4 text-xs text-gray-400">
        <span>Source: {diff.source_version?.slice(0, 8) ?? "none"}</span>
        <span>Target: {diff.target_version?.slice(0, 8) ?? "none"}</span>
      </div>

      {diff.differences.length === 0 ? (
        <p className="text-xs text-green-400">✓ Configurations are identical</p>
      ) : (
        <div className="space-y-2">
          {diff.differences.map((d, idx) => (
            <div key={idx} className="rounded-md bg-black/20 p-2">
              <span className="mb-1 block text-xs font-medium text-white">
                {String(d.field ?? "")}
              </span>
              <div className="grid grid-cols-2 gap-2 text-[11px]">
                <div>
                  <span className="text-red-400">- </span>
                  <span className="text-gray-400">{String(d.source_value ?? "null")}</span>
                </div>
                <div>
                  <span className="text-green-400">+ </span>
                  <span className="text-gray-400">{String(d.target_value ?? "null")}</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
