import { useState } from "react";
import {
  GripVertical,
  Trash2,
  Edit,
  Brain,
  Wrench,
  GitBranch,
  Check,
  Shield,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Textarea } from "@/components/ui/Textarea";

export interface PlanStep {
  id: string;
  name: string;
  type: "llm" | "tool" | "condition" | "auth" | "default";
  description: string;
}

const TYPE_BADGE: Record<string, { color: string; icon: typeof Brain }> = {
  llm: { color: "bg-blue-500/20 text-blue-400", icon: Brain },
  tool: { color: "bg-green-500/20 text-green-400", icon: Wrench },
  condition: { color: "bg-yellow-500/20 text-yellow-400", icon: GitBranch },
  auth: { color: "bg-red-500/20 text-red-400", icon: Shield },
  default: { color: "bg-gray-500/20 text-gray-400", icon: Brain },
};

interface PlanCardProps {
  step: PlanStep;
  index: number;
  onMove: (from: number, to: number) => void;
  onDelete: (index: number) => void;
  onUpdate: (index: number, patch: Partial<PlanStep>) => void;
  totalSteps: number;
}

export function PlanCard({
  step,
  index,
  onMove,
  onDelete,
  onUpdate,
  totalSteps,
}: PlanCardProps) {
  const [isEditing, setIsEditing] = useState(false);
  const badge = TYPE_BADGE[step.type] ?? TYPE_BADGE.default;
  const BadgeIcon = badge?.icon;

  return (
    <div className="rounded-lg border border-surface-border bg-surface-base p-4 transition-colors hover:border-purple-500/30">
      <div className="flex items-start gap-3">
        {/* Reorder handle */}
        <div className="flex flex-col gap-0.5 pt-1">
          <button
            type="button"
            onClick={() => onMove(index, index - 1)}
            disabled={index === 0}
            className="text-gray-600 hover:text-white disabled:opacity-30"
            aria-label="Move up"
          >
            <GripVertical size={14} />
          </button>
          <button
            type="button"
            onClick={() => onMove(index, index + 1)}
            disabled={index === totalSteps - 1}
            className="text-gray-600 hover:text-white disabled:opacity-30"
            aria-label="Move down"
          >
            <GripVertical size={14} />
          </button>
        </div>

        {/* Content */}
        <div className="min-w-0 flex-1">
          {isEditing ? (
            <div className="space-y-2">
              <Input
                value={step.name}
                onChange={(e) => onUpdate(index, { name: e.target.value })}
                className="bg-surface-raised text-white border-surface-border"
                aria-label="Step name"
              />
              <select
                value={step.type}
                onChange={(e) =>
                  onUpdate(index, {
                    type: e.target.value as PlanStep["type"],
                  })
                }
                className="h-8 rounded-md border border-surface-border bg-surface-raised px-2 text-xs text-white"
                aria-label="Step type"
              >
                <option value="llm">LLM</option>
                <option value="tool">Tool</option>
                <option value="condition">Condition</option>
                <option value="auth">Auth</option>
              </select>
              <Textarea
                rows={2}
                value={step.description}
                onChange={(e) =>
                  onUpdate(index, { description: e.target.value })
                }
                className="bg-surface-raised text-white border-surface-border text-xs"
                aria-label="Step description"
              />
              <Button
                size="sm"
                variant="outline"
                onClick={() => setIsEditing(false)}
              >
                <Check size={12} className="mr-1" /> Done
              </Button>
            </div>
          ) : (
            <>
              <div className="mb-1 flex items-center gap-2">
                <span className="text-xs font-mono text-gray-600">
                  {index + 1}.
                </span>
                <h4 className="text-sm font-medium text-white">{step.name}</h4>
                <span
                  className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium ${badge?.color}`}
                >
                  {BadgeIcon && <BadgeIcon size={10} />}
                  {step.type.toUpperCase()}
                </span>
              </div>
              <p className="text-xs text-gray-400">{step.description}</p>
            </>
          )}
        </div>

        {/* Actions */}
        {!isEditing && (
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => setIsEditing(true)}
              className="rounded p-1 text-gray-500 hover:bg-white/5 hover:text-white"
              aria-label="Edit step"
            >
              <Edit size={14} />
            </button>
            <button
              type="button"
              onClick={() => onDelete(index)}
              className="rounded p-1 text-gray-500 hover:bg-red-500/10 hover:text-red-400"
              aria-label="Delete step"
            >
              <Trash2 size={14} />
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
