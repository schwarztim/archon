/**
 * RoutingDecisionPill — surfaces the model + provider + reason chosen by
 * the model router for a step. Reads from ``step.output.routing`` (see
 * ``backend/app/services/model_router.py`` for the producer side).
 */

import { GitBranch } from "lucide-react";
import type { RoutingDecision } from "@/types/artifacts";

interface RoutingDecisionPillProps {
  routing: RoutingDecision | null | undefined;
  className?: string;
}

const PROVIDER_TINTS: Record<string, string> = {
  openai: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
  anthropic: "bg-violet-500/15 text-violet-300 border-violet-500/30",
  google: "bg-blue-500/15 text-blue-300 border-blue-500/30",
  azure: "bg-amber-500/15 text-amber-300 border-amber-500/30",
};

export function RoutingDecisionPill({
  routing,
  className,
}: RoutingDecisionPillProps) {
  if (!routing) {
    return (
      <span
        data-testid="routing-pill-empty"
        className={`inline-flex items-center gap-1 text-xs text-gray-500 ${className ?? ""}`}
      >
        <GitBranch size={10} />no routing
      </span>
    );
  }
  const tint =
    PROVIDER_TINTS[routing.provider.toLowerCase()] ??
    "bg-gray-500/15 text-gray-300 border-gray-500/30";
  const tooltip = [
    `Model: ${routing.model}`,
    `Provider: ${routing.provider}`,
    routing.reason ? `Reason: ${routing.reason}` : null,
    routing.candidates && routing.candidates.length > 0
      ? `Candidates: ${routing.candidates.join(", ")}`
      : null,
  ]
    .filter(Boolean)
    .join("\n");

  return (
    <span
      data-testid="routing-pill"
      title={tooltip}
      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium ${tint} ${className ?? ""}`}
    >
      <GitBranch size={10} />
      <span className="font-mono">{routing.model}</span>
      <span className="text-[10px] opacity-80">/ {routing.provider}</span>
    </span>
  );
}
