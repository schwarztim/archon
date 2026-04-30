/**
 * StepCostBadge — small inline badge for an execution step's cost.
 *
 * Designed to drop into the step list on ExecutionDetailPage. Reads cost
 * data from the step's output (``output.cost``) when available; falls
 * back to dashes when no cost was recorded for the step. Hover surfaces
 * the per-token breakdown via the native ``title`` tooltip.
 */

import { DollarSign } from "lucide-react";
import type { StepCost } from "@/types/artifacts";

interface StepCostBadgeProps {
  cost: StepCost | null | undefined;
  /** Optional override classes for layout tweaks. */
  className?: string;
}

function formatCurrency(value: number): string {
  if (value === 0) return "$0.00";
  if (value < 0.01) {
    // Sub-cent precision so cheap calls don't all display as $0.00.
    return `$${value.toFixed(4)}`;
  }
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
  }).format(value);
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

export function StepCostBadge({ cost, className }: StepCostBadgeProps) {
  if (!cost || (cost.cost_usd === 0 && cost.input_tokens === 0)) {
    return (
      <span
        data-testid="step-cost-badge-empty"
        className={`inline-flex items-center gap-1 text-xs text-gray-500 ${className ?? ""}`}
      >
        <DollarSign size={10} />—
      </span>
    );
  }

  const totalTokens = cost.input_tokens + cost.output_tokens;
  const tooltip = [
    `Cost: ${formatCurrency(cost.cost_usd)}`,
    `Input tokens: ${formatTokens(cost.input_tokens)}`,
    `Output tokens: ${formatTokens(cost.output_tokens)}`,
    cost.model ? `Model: ${cost.model}` : null,
    cost.provider ? `Provider: ${cost.provider}` : null,
  ]
    .filter(Boolean)
    .join("\n");

  return (
    <span
      data-testid="step-cost-badge"
      title={tooltip}
      className={`inline-flex items-center gap-1 rounded-full bg-green-500/15 px-2 py-0.5 text-xs font-medium text-green-300 ${className ?? ""}`}
    >
      <DollarSign size={10} />
      {formatCurrency(cost.cost_usd)}
      <span className="ml-1 text-[10px] text-green-400/80">
        ({formatTokens(totalTokens)} tok)
      </span>
    </span>
  );
}
