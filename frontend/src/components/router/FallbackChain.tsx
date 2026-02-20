import { useState, useCallback } from "react";
import { GripVertical, X } from "lucide-react";
import { Button } from "@/components/ui/Button";

/* ─── Types ──────────────────────────────────────────────────────── */

interface ModelOption {
  id: string;
  name: string;
  provider: string;
}

interface FallbackChainProps {
  modelIds: string[];
  availableModels: ModelOption[];
  onChange: (modelIds: string[]) => void;
}

/* ─── Component ──────────────────────────────────────────────────── */

export default function FallbackChain({
  modelIds,
  availableModels,
  onChange,
}: FallbackChainProps) {
  const [dragIndex, setDragIndex] = useState<number | null>(null);

  const getModelInfo = useCallback(
    (id: string): ModelOption | undefined =>
      availableModels.find((m) => m.id === id),
    [availableModels],
  );

  const handleDragStart = useCallback((index: number) => {
    setDragIndex(index);
  }, []);

  const handleDragOver = useCallback(
    (e: React.DragEvent, index: number) => {
      e.preventDefault();
      if (dragIndex === null || dragIndex === index) return;
      const next = [...modelIds];
      const [moved] = next.splice(dragIndex, 1);
      next.splice(index, 0, moved!);
      onChange(next);
      setDragIndex(index);
    },
    [dragIndex, modelIds, onChange],
  );

  const handleDragEnd = useCallback(() => {
    setDragIndex(null);
  }, []);

  const removeModel = useCallback(
    (index: number) => {
      onChange(modelIds.filter((_, i) => i !== index));
    },
    [modelIds, onChange],
  );

  const addModel = useCallback(
    (modelId: string) => {
      if (modelId && !modelIds.includes(modelId)) {
        onChange([...modelIds, modelId]);
      }
    },
    [modelIds, onChange],
  );

  const unusedModels = availableModels.filter((m) => !modelIds.includes(m.id));

  return (
    <div
      className="space-y-3"
      role="region"
      aria-label="Fallback chain configuration"
    >
      <h4 className="text-sm font-medium text-foreground">
        Fallback Order{" "}
        <span className="text-muted-foreground font-normal">(drag to reorder)</span>
      </h4>

      {modelIds.length === 0 && (
        <p className="text-sm text-muted-foreground py-2" role="status">
          No fallback models configured. Add models below.
        </p>
      )}

      <div className="space-y-1">
        {modelIds.map((modelId, index) => {
          const model = getModelInfo(modelId);
          return (
            <div
              key={modelId}
              className={`flex items-center gap-2 rounded-md border px-3 py-2 transition-all bg-card dark:bg-card ${
                dragIndex === index ? "ring-2 ring-primary" : ""
              }`}
              draggable
              onDragStart={() => handleDragStart(index)}
              onDragOver={(e) => handleDragOver(e, index)}
              onDragEnd={handleDragEnd}
              role="listitem"
              aria-label={`Fallback #${index + 1}: ${model?.name ?? modelId}`}
            >
              <button
                className="cursor-grab active:cursor-grabbing text-muted-foreground hover:text-foreground"
                aria-label="Drag to reorder"
                tabIndex={0}
              >
                <GripVertical className="h-4 w-4" aria-hidden="true" />
              </button>

              <span className="text-sm font-mono text-muted-foreground w-6">
                {index + 1}.
              </span>

              <span className="text-sm font-medium text-foreground flex-1">
                {model?.name ?? modelId}
              </span>

              {model?.provider && (
                <span className="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
                  {model.provider}
                </span>
              )}

              <Button
                variant="ghost"
                size="sm"
                onClick={() => removeModel(index)}
                className="h-6 w-6 p-0 text-muted-foreground hover:text-destructive"
                aria-label={`Remove ${model?.name ?? modelId} from fallback chain`}
              >
                <X className="h-3.5 w-3.5" />
              </Button>
            </div>
          );
        })}
      </div>

      {unusedModels.length > 0 && (
        <div className="flex items-center gap-2">
          <select
            className="h-8 rounded-md border bg-background dark:bg-muted/30 px-2 text-sm flex-1"
            defaultValue=""
            onChange={(e) => {
              addModel(e.target.value);
              e.target.value = "";
            }}
            aria-label="Add model to fallback chain"
          >
            <option value="" disabled>
              + Add model to fallback chain…
            </option>
            {unusedModels.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name} ({m.provider})
              </option>
            ))}
          </select>
        </div>
      )}
    </div>
  );
}
