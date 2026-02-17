import { useState, useCallback, useEffect } from "react";
import { ReactFlowProvider } from "@xyflow/react";
import { AgentCanvas } from "@/components/canvas/AgentCanvas";
import { TopBar } from "@/components/canvas/TopBar";
import { NodePalette } from "@/components/palette";
import { PropertyPanel } from "@/components/properties";
import { useCanvasStore } from "@/stores/canvasStore";
import { useAgent } from "@/hooks/useAgents";

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

  const { clearCanvas, setNodes, setEdges, markClean } = useCanvasStore();
  const { data: agentResponse } = useAgent(agentId);

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

  const handleToggleTheme = useCallback(() => {
    setIsDark((d) => !d);
  }, []);

  const handleNewAgent = useCallback(() => {
    clearCanvas();
    setAgentName("Untitled Agent");
    setAgentId(null);
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
        />
        <div className="flex flex-1 overflow-hidden">
          <NodePalette />
          <main className="flex-1">
            <AgentCanvas />
          </main>
          <PropertyPanel />
        </div>
      </div>
    </ReactFlowProvider>
  );
}
