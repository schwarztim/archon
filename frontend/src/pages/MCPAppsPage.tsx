import { useState, useCallback } from "react";
import {
  Table,
  BarChart3,
  FormInput,
  CheckSquare,
  Code,
  FileText,
  Image,
  Blocks,
  Search,
  Clock,
  ArrowLeft,
  type LucideIcon,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import { cn } from "@/utils/cn";
import { ChatInterface } from "@/components/mcp/ChatInterface";
import type { ChatMessage, MCPComponentPayload } from "@/api/mcp";

// ─── Types ───────────────────────────────────────────────────────────

interface AppCard {
  id: string;
  name: string;
  description: string;
  icon: LucideIcon;
  category: string;
}

// ─── Available MCP Apps ─────────────────────────────────────────────

const MCP_APPS: AppCard[] = [
  { id: "data-explorer", name: "Data Explorer", description: "Query and visualize data with sortable tables and charts", icon: Table, category: "Data" },
  { id: "analytics", name: "Analytics Dashboard", description: "Interactive charts and metrics visualization", icon: BarChart3, category: "Data" },
  { id: "form-builder", name: "Form Builder", description: "Dynamic forms that submit data back to agents", icon: FormInput, category: "Input" },
  { id: "approval-flow", name: "Approval Flow", description: "Approve or reject actions with audit trail", icon: CheckSquare, category: "Workflow" },
  { id: "code-review", name: "Code Review", description: "Syntax-highlighted code blocks with annotations", icon: Code, category: "Dev" },
  { id: "doc-viewer", name: "Document Viewer", description: "Rich markdown rendering with formatting", icon: FileText, category: "Content" },
  { id: "media-gallery", name: "Media Gallery", description: "Image grid with lightbox preview", icon: Image, category: "Content" },
];

// ─── Sample demo messages with embedded components ──────────────────

function buildDemoMessages(): ChatMessage[] {
  return [
    {
      id: "m1",
      role: "user",
      content: "Show me the latest agent execution results.",
      timestamp: new Date().toISOString(),
    },
    {
      id: "m2",
      role: "assistant",
      content: "Here are the latest execution results:",
      timestamp: new Date().toISOString(),
      components: [
        {
          type: "data_table",
          props: {
            columns: [
              { key: "agent", label: "Agent", sortable: true },
              { key: "duration", label: "Duration", sortable: true },
              { key: "tokens", label: "Tokens Used", sortable: true },
              { key: "status", label: "Status" },
            ],
            rows: [
              { agent: "DocForge Agent", duration: "2.1s", tokens: "1,240", status: "Completed" },
              { agent: "Governance Bot", duration: "0.8s", tokens: "560", status: "Completed" },
              { agent: "Cost Optimizer", duration: "1.5s", tokens: "890", status: "Running" },
              { agent: "SentinelScan", duration: "3.2s", tokens: "2,100", status: "Completed" },
            ],
          },
        } satisfies MCPComponentPayload,
      ],
    },
    {
      id: "m3",
      role: "user",
      content: "Show me a chart of token usage by agent.",
      timestamp: new Date().toISOString(),
    },
    {
      id: "m4",
      role: "assistant",
      content: "Here's the token usage breakdown:",
      timestamp: new Date().toISOString(),
      components: [
        {
          type: "chart",
          props: {
            chartType: "bar",
            data: [
              { agent: "DocForge", tokens: 1240 },
              { agent: "Governance", tokens: 560 },
              { agent: "Cost Opt.", tokens: 890 },
              { agent: "Sentinel", tokens: 2100 },
            ],
            xKey: "agent",
            yKey: "tokens",
            title: "Token Usage by Agent",
            height: 250,
          },
        } satisfies MCPComponentPayload,
      ],
    },
  ];
}

// ─── Component ──────────────────────────────────────────────────────

export function MCPAppsPage() {
  const [search, setSearch] = useState("");
  const [activeApp, setActiveApp] = useState<AppCard | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sessionId] = useState<string | null>(null);
  const [recentSessions] = useState<{ appId: string; time: string }[]>([
    { appId: "data-explorer", time: "2 min ago" },
    { appId: "approval-flow", time: "15 min ago" },
    { appId: "analytics", time: "1 hour ago" },
  ]);

  const filtered = MCP_APPS.filter(
    (app) =>
      app.name.toLowerCase().includes(search.toLowerCase()) ||
      app.description.toLowerCase().includes(search.toLowerCase()) ||
      app.category.toLowerCase().includes(search.toLowerCase()),
  );

  const categories = [...new Set(MCP_APPS.map((a) => a.category))];

  function openApp(app: AppCard) {
    setActiveApp(app);
    setMessages(buildDemoMessages());
  }

  function closeApp() {
    setActiveApp(null);
    setMessages([]);
  }

  const handleSendMessage = useCallback(
    (text: string) => {
      const userMsg: ChatMessage = {
        id: `u-${Date.now()}`,
        role: "user",
        content: text,
        timestamp: new Date().toISOString(),
      };

      // Simulated agent response with component
      const botMsg: ChatMessage = {
        id: `b-${Date.now()}`,
        role: "assistant",
        content: "Here's the data you requested:",
        timestamp: new Date().toISOString(),
        components: [
          {
            type: "data_table",
            props: {
              columns: [
                { key: "item", label: "Item" },
                { key: "type", label: "Type" },
                { key: "status", label: "Status" },
              ],
              rows: [
                { item: "DataTable", type: "Display", status: "Active" },
                { item: "Chart", type: "Visualization", status: "Active" },
                { item: "Form", type: "Input", status: "Beta" },
              ],
            },
          } satisfies MCPComponentPayload,
        ],
      };

      setMessages((prev) => [...prev, userMsg, botMsg]);
    },
    [],
  );

  // ── Active Chat View ────────────────────────────────────────────

  if (activeApp) {
    return (
      <div className="flex h-full flex-col p-6">
        {/* Header */}
        <div className="mb-4 flex items-center gap-3">
          <button
            onClick={closeApp}
            className="rounded p-1 text-gray-400 hover:bg-white/10 hover:text-white"
            aria-label="Back to apps"
          >
            <ArrowLeft size={20} />
          </button>
          <activeApp.icon size={24} className="text-purple-400" />
          <div>
            <h1 className="text-lg font-bold text-white">{activeApp.name}</h1>
            <p className="text-xs text-gray-500">{activeApp.description}</p>
          </div>
        </div>

        {/* Chat */}
        <div className="flex-1 min-h-0">
          <ChatInterface
            sessionId={sessionId}
            messages={messages}
            onSendMessage={handleSendMessage}
          />
        </div>
      </div>
    );
  }

  // ── Apps Grid View ──────────────────────────────────────────────

  return (
    <div className="p-6">
      {/* Header */}
      <div className="mb-4 flex items-center gap-3">
        <Blocks size={24} className="text-purple-400" />
        <h1 className="text-2xl font-bold text-white">MCP Apps</h1>
      </div>
      <p className="mb-6 text-gray-400">
        Build interactive AI experiences with live components that render inside agent conversations.
      </p>

      {/* Search */}
      <div className="mb-6">
        <div className="relative max-w-md">
          <Search
            size={16}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500"
          />
          <input
            className="w-full rounded-md border border-[#2a2d37] bg-[#1a1d27] py-2 pl-9 pr-3 text-sm text-gray-200 placeholder-gray-600 focus:border-purple-500 focus:outline-none"
            placeholder="Search apps…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
      </div>

      {/* Recent Sessions */}
      {recentSessions.length > 0 && !search && (
        <div className="mb-8">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-gray-400">
            Recent Sessions
          </h2>
          <div className="flex gap-3 overflow-x-auto pb-2">
            {recentSessions.map((s, i) => {
              const app = MCP_APPS.find((a) => a.id === s.appId);
              if (!app) return null;
              return (
                <button
                  key={i}
                  onClick={() => openApp(app)}
                  className="flex shrink-0 items-center gap-2 rounded-lg border border-[#2a2d37] bg-[#1a1d27] px-4 py-2.5 transition-colors hover:border-purple-500/40"
                >
                  <app.icon size={16} className="text-purple-400" />
                  <span className="text-sm text-white">{app.name}</span>
                  <span className="flex items-center gap-1 text-xs text-gray-500">
                    <Clock size={10} />
                    {s.time}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* Component Library (by category) */}
      {categories.map((cat) => {
        const apps = filtered.filter((a) => a.category === cat);
        if (apps.length === 0) return null;
        return (
          <div key={cat} className="mb-8">
            <h2 className="mb-4 text-sm font-semibold uppercase tracking-wider text-gray-400">
              {cat}
            </h2>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {apps.map((app) => (
                <button
                  key={app.id}
                  onClick={() => openApp(app)}
                  className={cn(
                    "flex flex-col items-start rounded-lg border border-[#2a2d37] bg-[#1a1d27] p-5 text-left transition-colors hover:border-purple-500/40",
                  )}
                >
                  <app.icon size={28} className="mb-3 text-purple-400" />
                  <h3 className="mb-1 text-sm font-semibold text-white">
                    {app.name}
                  </h3>
                  <p className="text-xs text-gray-500">{app.description}</p>
                </button>
              ))}
            </div>
          </div>
        );
      })}

      {filtered.length === 0 && (
        <p className="py-12 text-center text-gray-500">
          No apps match your search.
        </p>
      )}
    </div>
  );
}
