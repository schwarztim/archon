import { useState } from "react";
import {
  Search,
  Globe,
  Calculator,
  FileText,
  Code2,
  Server,
  Zap,
  Mail,
  MessageSquare,
  Wrench,
  Settings,
} from "lucide-react";

// ─── Types ───────────────────────────────────────────────────────────

export interface ToolConfig {
  id: string;
  params: Record<string, string>;
}

export interface ToolsData {
  selectedTools: ToolConfig[];
}

interface ToolsStepProps {
  data: ToolsData;
  onChange: (data: ToolsData) => void;
}

interface ToolItem {
  id: string;
  name: string;
  description: string;
  icon: string;
  category: string;
  params: { name: string; label: string; placeholder: string }[];
}

// ─── Constants ───────────────────────────────────────────────────────

const MCP_TOOLS: ToolItem[] = [
  { id: "web-search", name: "Web Search", description: "Search the web for information", icon: "globe", category: "Search", params: [{ name: "engine", label: "Search Engine", placeholder: "google" }] },
  { id: "calculator", name: "Calculator", description: "Perform mathematical calculations", icon: "calculator", category: "Utility", params: [] },
  { id: "file-reader", name: "File Reader", description: "Read and parse file contents", icon: "file", category: "Data", params: [{ name: "max_size_mb", label: "Max File Size (MB)", placeholder: "10" }] },
  { id: "code-executor", name: "Code Executor", description: "Execute code in a sandboxed environment", icon: "code", category: "Development", params: [{ name: "runtime", label: "Runtime", placeholder: "python3" }] },
  { id: "database-query", name: "Database Query", description: "Query relational databases", icon: "server", category: "Data", params: [{ name: "dialect", label: "DB Dialect", placeholder: "postgresql" }] },
  { id: "api-caller", name: "API Caller", description: "Make HTTP requests to external APIs", icon: "zap", category: "Integration", params: [{ name: "timeout_ms", label: "Timeout (ms)", placeholder: "5000" }] },
  { id: "email-sender", name: "Email Sender", description: "Send emails via configured SMTP", icon: "mail", category: "Communication", params: [{ name: "provider", label: "Email Provider", placeholder: "smtp" }] },
  { id: "slack-notifier", name: "Slack Notifier", description: "Send messages to Slack channels", icon: "message", category: "Communication", params: [{ name: "channel", label: "Default Channel", placeholder: "#general" }] },
  { id: "document-parser", name: "Document Parser", description: "Parse PDF, DOCX, and other document formats", icon: "file", category: "Data", params: [] },
  { id: "image-analyzer", name: "Image Analyzer", description: "Analyze and describe image content", icon: "zap", category: "AI", params: [{ name: "model", label: "Vision Model", placeholder: "gpt-4o" }] },
  { id: "vector-search", name: "Vector Search", description: "Semantic similarity search in vector stores", icon: "server", category: "Search", params: [{ name: "collection", label: "Collection", placeholder: "default" }] },
  { id: "git-operations", name: "Git Operations", description: "Git repository operations", icon: "code", category: "Development", params: [] },
];

const CATEGORIES = ["All", ...new Set(MCP_TOOLS.map((t) => t.category))];

function ToolIcon({ icon, size = 18 }: { icon: string; size?: number }) {
  switch (icon) {
    case "globe": return <Globe size={size} />;
    case "calculator": return <Calculator size={size} />;
    case "file": return <FileText size={size} />;
    case "code": return <Code2 size={size} />;
    case "server": return <Server size={size} />;
    case "zap": return <Zap size={size} />;
    case "mail": return <Mail size={size} />;
    case "message": return <MessageSquare size={size} />;
    default: return <Wrench size={size} />;
  }
}

const inputClass =
  "w-full rounded-lg border border-[#2a2d37] bg-[#1a1d27] px-3 py-2 text-sm text-white placeholder-gray-500 focus:border-purple-500 focus:outline-none";
const labelClass = "mb-1 block text-xs font-medium text-gray-400";

// ─── Component ───────────────────────────────────────────────────────

export function ToolsStep({ data, onChange }: ToolsStepProps) {
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("All");
  const [configuringTool, setConfiguringTool] = useState<string | null>(null);

  const selectedIds = new Set(data.selectedTools.map((t) => t.id));

  const filteredTools = MCP_TOOLS.filter((t) => {
    const matchesSearch =
      t.name.toLowerCase().includes(search.toLowerCase()) ||
      t.description.toLowerCase().includes(search.toLowerCase());
    const matchesCategory = category === "All" || t.category === category;
    return matchesSearch && matchesCategory;
  });

  const toggleTool = (id: string) => {
    if (selectedIds.has(id)) {
      onChange({ selectedTools: data.selectedTools.filter((t) => t.id !== id) });
    } else {
      onChange({ selectedTools: [...data.selectedTools, { id, params: {} }] });
    }
  };

  const updateToolParam = (toolId: string, paramName: string, value: string) => {
    onChange({
      selectedTools: data.selectedTools.map((t) =>
        t.id === toolId ? { ...t, params: { ...t.params, [paramName]: value } } : t,
      ),
    });
  };

  const toolDef = configuringTool ? MCP_TOOLS.find((t) => t.id === configuringTool) : null;
  const toolConfig = configuringTool ? data.selectedTools.find((t) => t.id === configuringTool) : null;

  return (
    <div className="space-y-4">
      {/* Search & Category Filter */}
      <div className="flex gap-3">
        <div className="relative flex-1">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
          <input
            type="text"
            placeholder="Search MCP tools..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className={`pl-9 ${inputClass}`}
          />
        </div>
        <select
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          className={`w-40 ${inputClass}`}
        >
          {CATEGORIES.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
      </div>

      {/* Selected count */}
      <p className="text-xs text-gray-500">
        {data.selectedTools.length} tool{data.selectedTools.length !== 1 ? "s" : ""} selected
      </p>

      {/* Tools Grid */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {filteredTools.map((tool) => {
          const isSelected = selectedIds.has(tool.id);
          return (
            <div
              key={tool.id}
              className={`group relative rounded-lg border p-3 transition-colors ${
                isSelected
                  ? "border-purple-500 bg-purple-500/10"
                  : "border-[#2a2d37] bg-[#1a1d27] hover:border-gray-600"
              }`}
            >
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-2">
                  <div className={`rounded-lg p-1.5 ${isSelected ? "bg-purple-500/20 text-purple-400" : "bg-[#12141e] text-gray-400"}`}>
                    <ToolIcon icon={tool.icon} />
                  </div>
                  <div>
                    <span className="text-sm font-medium text-white">{tool.name}</span>
                    <span className="ml-2 rounded bg-[#12141e] px-1.5 py-0.5 text-[10px] text-gray-500">
                      {tool.category}
                    </span>
                  </div>
                </div>
                <div className="flex gap-1">
                  {isSelected && tool.params.length > 0 && (
                    <button
                      type="button"
                      onClick={() => setConfiguringTool(configuringTool === tool.id ? null : tool.id)}
                      className="rounded p-1 text-gray-400 hover:bg-white/10 hover:text-white"
                      aria-label={`Configure ${tool.name}`}
                    >
                      <Settings size={14} />
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => toggleTool(tool.id)}
                    className={`h-5 w-5 rounded border ${
                      isSelected
                        ? "border-purple-500 bg-purple-500"
                        : "border-gray-600 bg-transparent hover:border-gray-500"
                    } flex items-center justify-center`}
                  >
                    {isSelected && (
                      <svg viewBox="0 0 12 12" className="h-3 w-3 text-white">
                        <path d="M10 3L4.5 8.5L2 6" stroke="currentColor" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                    )}
                  </button>
                </div>
              </div>
              <p className="mt-1.5 text-xs text-gray-500">{tool.description}</p>

              {/* Inline Parameter Config */}
              {configuringTool === tool.id && toolDef && toolConfig && (
                <div className="mt-3 space-y-2 border-t border-[#2a2d37] pt-3">
                  {toolDef.params.map((p) => (
                    <div key={p.name}>
                      <label className={labelClass}>{p.label}</label>
                      <input
                        type="text"
                        value={toolConfig.params[p.name] ?? ""}
                        onChange={(e) => updateToolParam(tool.id, p.name, e.target.value)}
                        placeholder={p.placeholder}
                        className={inputClass}
                      />
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
