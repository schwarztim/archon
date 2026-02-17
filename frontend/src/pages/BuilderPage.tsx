import { useState, useCallback, useEffect, useRef } from "react";
import { ReactFlowProvider } from "@xyflow/react";
import { AgentCanvas } from "@/components/canvas/AgentCanvas";
import { TopBar } from "@/components/canvas/TopBar";
import { NodePalette } from "@/components/palette";
import { PropertyPanel } from "@/components/properties";
import { TestRunPanel } from "@/components/builder/TestRunPanel";
import { ValidationOverlay } from "@/components/builder/ValidationOverlay";
import { useCanvasStore } from "@/stores/canvasStore";
import { useAgent, useUpdateAgent, useCreateAgent } from "@/hooks/useAgents";

/** Auto-save interval in milliseconds (30 seconds) */
const AUTO_SAVE_INTERVAL_MS = 30_000;

export function BuilderPage() {
  const [agentId, setAgentId] = useState<string | null>(() => {
    const params = new URLSearchParams(window.location.search);
    return params.get("agentId");
  });
  const [agentName, setAgentName] = useState("Untitled Agent");
  const [isDark, setIsDark] = useState(() => {
    if (typeof window === "undefined") return false;
    return (
      window.matchMedia("(prefers-color-scheme: dark)").matches ||
      document.documentElement.classList.contains("dark")
    );
  });
  const [testPanelOpen, setTestPanelOpen] = useState(false);

  const { clearCanvas, setNodes, setEdges, markClean, isDirty, nodes, edges, showValidation, setLastAutoSave } = useCanvasStore();
  const { data: agentResponse } = useAgent(agentId);
  const updateAgent = useUpdateAgent();
  const createAgent = useCreateAgent();
  const autoSaveRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Load agent from API when agentId is present
  useEffect(() => {
    if (!agentResponse?.data) return;
    const agent = agentResponse.data;
    setAgentName(agent.name);
    if (agent.nodes) setNodes(agent.nodes);
    if (agent.edges) setEdges(agent.edges);
    markClean();
  }, [agentResponse, setNodes, setEdges, markClean]);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", isDark);
  }, [isDark]);

  // Auto-save draft every 30 seconds
  useEffect(() => {
    autoSaveRef.current = setInterval(() => {
      const store = useCanvasStore.getState();
      if (!store.isDirty || !agentId) return;

      void updateAgent.mutateAsync({
        id: agentId,
        name: agentName,
        nodes: store.nodes,
        edges: store.edges,
      }).then(() => {
        store.markClean();
        store.setLastAutoSave(Date.now());
      }).catch(() => {
        // Auto-save failures are silent — user can still manually save
      });
    }, AUTO_SAVE_INTERVAL_MS);

    return () => {
      if (autoSaveRef.current) clearInterval(autoSaveRef.current);
    };
  }, [agentId, agentName, updateAgent]);

  const handleToggleTheme = useCallback(() => {
    setIsDark((d) => !d);
  }, []);

  const handleNewAgent = useCallback(() => {
    clearCanvas();
    setAgentName("Untitled Agent");
    setAgentId(null);
    setTestPanelOpen(false);
    // Clean up URL param
    const url = new URL(window.location.href);
    url.searchParams.delete("agentId");
    window.history.replaceState({}, "", url.toString());
  }, [clearCanvas]);

  const handleAgentSaved = useCallback((id: string) => {
    setAgentId(id);
    const url = new URL(window.location.href);
    url.searchParams.set("agentId", id);
    window.history.replaceState({}, "", url.toString());
  }, []);

  const handleToggleTestPanel = useCallback(() => {
    setTestPanelOpen((o) => !o);
  }, []);

  return (
    <ReactFlowProvider>
      <div className="flex h-screen flex-col bg-background text-foreground">
        <TopBar
          agentId={agentId}
          agentName={agentName}
          onAgentNameChange={setAgentName}
          onNewAgent={handleNewAgent}
          onToggleTheme={handleToggleTheme}
          onAgentSaved={handleAgentSaved}
          isDark={isDark}
          onToggleTestPanel={handleToggleTestPanel}
        />
        <div className="flex flex-1 overflow-hidden">
          <NodePalette />
          <main className="relative flex-1">
            <AgentCanvas />
            <ValidationOverlay showErrors={showValidation} />
          </main>
          <PropertyPanel />
          {testPanelOpen && (
            <TestRunPanel
              agentId={agentId}
              open={testPanelOpen}
              onClose={() => setTestPanelOpen(false)}
            />
          )}
        </div>
      </div>
    </ReactFlowProvider>
  );
}
