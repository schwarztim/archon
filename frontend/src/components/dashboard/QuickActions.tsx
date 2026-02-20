import { useNavigate } from "react-router-dom";
import { Plus, Play, Layers, Upload, ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/Button";

interface QuickActionsProps {
  onCreateAgent: () => void;
  onRunAgent: () => void;
}

export function QuickActions({ onCreateAgent, onRunAgent }: QuickActionsProps) {
  const navigate = useNavigate();

  const actions = [
    { label: "Create Agent", icon: <Plus size={16} />, action: onCreateAgent },
    { label: "Run Agent", icon: <Play size={16} />, action: onRunAgent },
    { label: "Browse Templates", icon: <Layers size={16} />, action: () => navigate("/templates") },
    { label: "Import Agent", icon: <Upload size={16} />, action: () => handleImport() },
  ];

  function handleImport() {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".json";
    input.onchange = async (e) => {
      const file = (e.target as HTMLInputElement).files?.[0];
      if (!file) return;
      try {
        const text = await file.text();
        JSON.parse(text);
        navigate("/agents");
      } catch {
        // Import error handled silently
      }
    };
    input.click();
  }

  return (
    <div className="rounded-lg border border-[#2a2d37] bg-[#1a1d27] p-4">
      <h2 className="mb-3 text-sm font-semibold text-white">Quick Actions</h2>
      <div className="flex flex-wrap gap-3">
        {actions.map((a) => (
          <Button
            key={a.label}
            variant="outline"
            size="sm"
            onClick={a.action}
            className="gap-2"
          >
            {a.icon}
            {a.label}
            <ArrowRight size={14} className="ml-1 opacity-50" />
          </Button>
        ))}
      </div>
    </div>
  );
}
