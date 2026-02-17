import { useCallback, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { useCanvasStore } from "@/stores/canvasStore";
import { useCreateAgent, useUpdateAgent } from "@/hooks/useAgents";
import type { CustomNodeData } from "@/types";

interface TopBarProps {
  agentId: string | null;
  agentName: string;
  onAgentNameChange: (name: string) => void;
  onNewAgent: () => void;
  onToggleTheme: () => void;
  onAgentSaved?: (id: string) => void;
  isDark: boolean;
  onToggleTestPanel?: () => void;
}

/** Validate graph before saving. Returns error messages or empty array. */
function validateGraph(
  nodes: { data: Record<string, unknown>; type?: string }[],
  edges: { source: string; target: string; sourceHandle?: string | null; targetHandle?: string | null }[],
): string[] {
  const errors: string[] = [];

  const hasInput = nodes.some((n) => {
    const cat = (n.data as CustomNodeData).category;
    return cat === "input";
  });
  const hasOutput = nodes.some((n) => {
    const cat = (n.data as CustomNodeData).category;
    return cat === "output";
  });

  if (!hasInput) errors.push("Graph must have at least 1 Input node.");
  if (!hasOutput) errors.push("Graph must have at least 1 Output node.");

  // Validate edges connect to existing nodes
  const nodeIds = new Set(nodes.map((n) => (n as unknown as { id: string }).id));
  for (const edge of edges) {
    if (!nodeIds.has(edge.source)) {
      errors.push(`Edge source "${edge.source}" not found.`);
    }
    if (!nodeIds.has(edge.target)) {
      errors.push(`Edge target "${edge.target}" not found.`);
    }
  }

  return errors;
}

export function TopBar({
  agentId,
  agentName,
  onAgentNameChange,
  onNewAgent,
  onToggleTheme,
  onAgentSaved,
  isDark,
  onToggleTestPanel,
}: TopBarProps) {
  const { nodes, edges, undo, redo, history, future, isDirty, markClean, showValidation, setShowValidation } =
    useCanvasStore();
  const createAgent = useCreateAgent();
  const updateAgent = useUpdateAgent();
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState<{ type: "error" | "success"; message: string } | null>(null);

  const showToast = useCallback((type: "error" | "success", message: string) => {
    setToast({ type, message });
    setTimeout(() => setToast(null), 4000);
  }, []);

  const handleSave = useCallback(async () => {
    // Validate before saving
    const errors = validateGraph(nodes, edges);
    if (errors.length > 0) {
      setShowValidation(true);
      showToast("error", errors.join(" "));
      return;
    }

    setSaving(true);
    try {
      if (agentId) {
        await updateAgent.mutateAsync({
          id: agentId,
          name: agentName,
          nodes,
          edges,
        });
        showToast("success", "Agent saved successfully.");
      } else {
        const res = await createAgent.mutateAsync({ name: agentName, nodes, edges });
        if (res?.data?.id) {
          onAgentSaved?.(res.data.id);
        }
        showToast("success", "Agent created successfully.");
      }
      markClean();
    } catch {
      showToast("error", "Failed to save agent. Please try again.");
    } finally {
      setSaving(false);
    }
  }, [
    agentId,
    agentName,
    nodes,
    edges,
    createAgent,
    updateAgent,
    markClean,
    showToast,
    onAgentSaved,
    setShowValidation,
  ]);

  const handleExportJSON = useCallback(() => {
    const data = JSON.stringify(
      { name: agentName, nodes, edges, exportedAt: new Date().toISOString() },
      null,
      2,
    );
    const blob = new Blob([data], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${agentName || "agent"}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }, [agentName, nodes, edges]);

  const handleImportJSON = useCallback(() => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".json";
    input.onchange = async (e) => {
      const file = (e.target as HTMLInputElement).files?.[0];
      if (!file) return;
      try {
        const text = await file.text();
        const data = JSON.parse(text) as {
          name?: string;
          nodes?: typeof nodes;
          edges?: typeof edges;
        };
        if (data.name) onAgentNameChange(data.name);
        if (data.nodes) useCanvasStore.getState().setNodes(data.nodes);
        if (data.edges) useCanvasStore.getState().setEdges(data.edges);
        showToast("success", "Graph imported successfully.");
      } catch {
        showToast("error", "Failed to import JSON file.");
      }
    };
    input.click();
  }, [onAgentNameChange, showToast]);

  return (
    <header
      className="relative flex h-12 items-center justify-between border-b border-border bg-card px-4"
      role="toolbar"
      aria-label="Agent builder toolbar"
    >
      {/* Left: Logo + Agent name */}
      <div className="flex items-center gap-3">
        <span className="text-sm font-bold tracking-tight">Archon</span>
        <div className="h-5 w-px bg-border" />
        <Input
          value={agentName}
          onChange={(e) => onAgentNameChange(e.target.value)}
          className="h-7 w-48 text-xs"
          placeholder="Agent name"
          aria-label="Agent name"
        />
        {isDirty && (
          <span className="text-xs text-amber-500" aria-live="polite">
            unsaved
          </span>
        )}
      </div>

      {/* Center: Undo/Redo */}
      <div className="flex items-center gap-1">
        <Button
          variant="ghost"
          size="sm"
          onClick={undo}
          disabled={history.length === 0}
          aria-label="Undo"
        >
          ↩
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={redo}
          disabled={future.length === 0}
          aria-label="Redo"
        >
          ↪
        </Button>
      </div>

      {/* Right: Actions */}
      <div className="flex items-center gap-2">
        <Button variant="ghost" size="sm" onClick={onNewAgent} aria-label="New agent">
          New
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={handleImportJSON}
          aria-label="Import JSON"
        >
          Import
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={handleExportJSON}
          aria-label="Export as JSON"
        >
          Export
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setShowValidation(!showValidation)}
          aria-label={showValidation ? "Hide validation errors" : "Show validation errors"}
        >
          {showValidation ? "✓ Validate" : "Validate"}
        </Button>
        {onToggleTestPanel && (
          <Button
            variant="ghost"
            size="sm"
            onClick={onToggleTestPanel}
            aria-label="Toggle test panel"
          >
            ▶ Test
          </Button>
        )}
        <Button
          variant="outline"
          size="sm"
          onClick={() => void handleSave()}
          disabled={saving}
          aria-label="Save agent"
        >
          {saving ? "Saving…" : "Save"}
        </Button>
        <Button
          variant="ghost"
          size="icon"
          onClick={onToggleTheme}
          aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
        >
          {isDark ? "☀️" : "🌙"}
        </Button>
      </div>

      {/* Toast notification */}
      {toast && (
        <div
          className={`absolute top-14 right-4 z-50 rounded-md px-4 py-2 text-sm shadow-lg ${
            toast.type === "error"
              ? "bg-destructive text-destructive-foreground"
              : "bg-green-600 text-white"
          }`}
          role="alert"
          aria-live="assertive"
        >
          {toast.message}
        </div>
      )}
    </header>
  );
}
