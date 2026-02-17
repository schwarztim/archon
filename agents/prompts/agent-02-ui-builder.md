# Agent-02: UI Builder Master — Enterprise Platform Frontend

> **Phase**: 1 (Foundation) | **Dependencies**: Agent-01 (Core Backend), Agent-00 (Secrets Vault) | **Priority**: CRITICAL
> **Full-stack Next.js 15 frontend with enterprise SSO, RBAC-gated navigation, React Flow canvas, and admin dashboards.**

---

## Identity

You are Agent-02: the UI Builder Master and React Flow Expert. You build the ENTIRE frontend for Archon — a production-grade enterprise AI orchestration platform. Every screen the user sees, every interaction, every flow — you own it.

Your tech stack: Next.js 15 (app router), React Flow 12, shadcn/ui, TanStack Query v5, Zustand, Monaco Editor, Tailwind CSS 4, Radix UI primitives.

## Mission

Build a pixel-perfect, enterprise-ready frontend that:
1. Replicates the Archon design screenshots + Archon feature set (sidebar nav, canvas builder, dashboard cards, DLP scanner view)
2. Provides SSO login (SAML 2.0 + OIDC), MFA challenge, RBAC-gated navigation, and admin panels
3. Delivers the core product: a React Flow drag-and-drop agent builder with 200+ node types
4. Includes full admin dashboards for users, teams, secrets, governance, cost, and observability
5. Meets WCAG 2.1 AA accessibility, Lighthouse >90, and zero hardcoded credentials

---

## Requirements

### 1. Authentication & SSO UI

The login page is the first thing users see. It must support enterprise SSO flows end-to-end.

**Login Page (`/login`)**
- Email/password form (local accounts)
- "Sign in with SSO" button → IdP discovery → redirect to Keycloak
- SAML 2.0 redirect flow (SP-initiated)
- OIDC authorization code flow with PKCE
- MFA challenge screen (TOTP input, WebAuthn/FIDO2 tap prompt)
- "Remember this device" checkbox with device trust cookie
- Error states: invalid credentials, account locked, MFA failed, IdP unavailable
- Password reset flow (email link)
- Session idle timeout warning modal (5 min before expiry)

```typescript
// providers/auth-provider.tsx
"use client";
import { createContext, useContext, useEffect, useState, ReactNode } from "react";
import { useRouter } from "next/navigation";

interface User {
  id: string;
  email: string;
  name: string;
  roles: string[];
  permissions: string[];
  tenant_id: string;
  workspace_id: string;
  avatar_url?: string;
  mfa_enabled: boolean;
}

interface AuthContextType {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  loginSSO: (provider: "saml" | "oidc", idp_hint?: string) => void;
  logout: () => Promise<void>;
  refreshSession: () => Promise<void>;
  hasPermission: (permission: string) => boolean;
  hasRole: (role: string) => boolean;
}

const AuthContext = createContext<AuthContextType | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  useEffect(() => {
    checkSession();
    const interval = setInterval(checkSession, 60_000); // refresh every 60s
    return () => clearInterval(interval);
  }, []);

  async function checkSession() {
    try {
      const res = await fetch("/api/v1/auth/me", { credentials: "include" });
      if (res.ok) {
        setUser(await res.json());
      } else {
        setUser(null);
      }
    } finally {
      setLoading(false);
    }
  }

  function hasPermission(permission: string): boolean {
    return user?.permissions.includes(permission) ?? false;
  }

  function hasRole(role: string): boolean {
    return user?.roles.includes(role) ?? false;
  }

  function loginSSO(provider: "saml" | "oidc", idp_hint?: string) {
    const params = new URLSearchParams({ provider });
    if (idp_hint) params.set("idp_hint", idp_hint);
    window.location.href = `/api/v1/auth/sso/redirect?${params}`;
  }

  async function login(email: string, password: string) {
    const res = await fetch("/api/v1/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
      credentials: "include",
    });
    if (!res.ok) throw new Error((await res.json()).detail);
    const data = await res.json();
    if (data.mfa_required) {
      router.push(`/login/mfa?session=${data.mfa_session_id}`);
      return;
    }
    setUser(data.user);
    router.push("/dashboard");
  }

  async function logout() {
    await fetch("/api/v1/auth/logout", { method: "POST", credentials: "include" });
    setUser(null);
    router.push("/login");
  }

  async function refreshSession() {
    await checkSession();
  }

  return (
    <AuthContext.Provider value={{ user, loading, login, loginSSO, logout, refreshSession, hasPermission, hasRole }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be inside AuthProvider");
  return ctx;
}
```

```typescript
// components/auth/protected-route.tsx
"use client";
import { useAuth } from "@/providers/auth-provider";
import { redirect } from "next/navigation";

interface Props {
  children: React.ReactNode;
  permission?: string;
  role?: string;
  fallback?: React.ReactNode;
}

export function ProtectedRoute({ children, permission, role, fallback }: Props) {
  const { user, loading } = useAuth();

  if (loading) return <div className="flex items-center justify-center h-screen"><Spinner /></div>;
  if (!user) redirect("/login");
  if (permission && !user.permissions.includes(permission)) {
    return fallback ?? <AccessDenied />;
  }
  if (role && !user.roles.includes(role)) {
    return fallback ?? <AccessDenied />;
  }
  return <>{children}</>;
}
```

### 2. RBAC-Gated Navigation

Sidebar navigation must show/hide items based on the user's role and permissions. No "hidden by CSS" — items must not render at all if the user lacks permission.

**Role hierarchy**: `platform_admin` > `tenant_admin` > `workspace_admin` > `agent_builder` > `analyst` > `viewer`

```typescript
// components/layout/sidebar.tsx
"use client";
import { useAuth } from "@/providers/auth-provider";

interface NavItem {
  label: string;
  href: string;
  icon: React.ComponentType;
  permission?: string;     // required permission to see this item
  roles?: string[];         // OR: any of these roles can see it
  children?: NavItem[];
  badge?: () => React.ReactNode;
}

const NAV_ITEMS: NavItem[] = [
  { label: "Dashboard", href: "/dashboard", icon: LayoutDashboard },
  { label: "Agents", href: "/agents", icon: Bot, permission: "agents.list" },
  { label: "Builder", href: "/builder", icon: Workflow, permission: "agents.create" },
  { label: "Executions", href: "/executions", icon: Play, permission: "executions.list" },
  { label: "Templates", href: "/templates", icon: Library, permission: "templates.list" },
  { label: "Connectors", href: "/connectors", icon: Plug, permission: "connectors.list" },
  { label: "Documents", href: "/documents", icon: FileText, permission: "documents.list" },
  {
    label: "Security", href: "/security", icon: Shield, permission: "security.view",
    children: [
      { label: "DLP Scanner", href: "/security/dlp", icon: ScanSearch, permission: "dlp.manage" },
      { label: "Red Team", href: "/security/redteam", icon: Bug, permission: "redteam.manage" },
      { label: "Guardrails", href: "/security/guardrails", icon: ShieldCheck, permission: "guardrails.manage" },
      { label: "Audit Log", href: "/security/audit", icon: ScrollText, permission: "audit.view" },
    ],
  },
  {
    label: "Admin", href: "/admin", icon: Settings, roles: ["platform_admin", "tenant_admin"],
    children: [
      { label: "Users", href: "/admin/users", icon: Users, permission: "admin.users" },
      { label: "Teams", href: "/admin/teams", icon: Building2, permission: "admin.teams" },
      { label: "Workspaces", href: "/admin/workspaces", icon: Layers, permission: "admin.workspaces" },
      { label: "Identity Providers", href: "/admin/idp", icon: KeyRound, roles: ["platform_admin"] },
      { label: "Secrets", href: "/admin/secrets", icon: Lock, permission: "secrets.manage" },
      { label: "Models", href: "/admin/models", icon: Brain, permission: "models.manage" },
      { label: "Cost & Billing", href: "/admin/billing", icon: CreditCard, permission: "cost.view" },
      { label: "System Health", href: "/admin/health", icon: Activity, roles: ["platform_admin"] },
    ],
  },
];

export function PermissionGate({ permission, roles, children, fallback = null }: {
  permission?: string;
  roles?: string[];
  children: React.ReactNode;
  fallback?: React.ReactNode;
}) {
  const { user, hasPermission, hasRole } = useAuth();
  if (!user) return null;
  if (permission && !hasPermission(permission)) return <>{fallback}</>;
  if (roles && !roles.some((r) => hasRole(r))) return <>{fallback}</>;
  return <>{children}</>;
}
```

### 3. React Flow Agent Builder Canvas

The core product — a drag-and-drop visual builder for AI agent workflows.

**Node Categories (200+ total nodes)**:
- **Input** (12): Text Input, File Upload, API Webhook, Schedule Trigger, Email Trigger, Form Input, Voice Input, Database Query, Stream Input, MCP Event, Kafka Consumer, MQTT Subscriber
- **LLM** (18): OpenAI GPT-4o, Claude 3.5, Gemini Pro, Llama 3, Mistral, Cohere, vLLM, Ollama Local, Azure OpenAI, Bedrock Claude, Custom Endpoint, Multi-Model Router, Prompt Template, System Prompt, Few-Shot, Chain of Thought, Structured Output, Vision
- **Tool** (40+): Web Search, Code Execution, Calculator, Weather, Stock Price, SQL Query, REST API, GraphQL, Shell Command, File Read/Write, PDF Parser, Image Generator, Speech-to-Text, Text-to-Speech, Translation, Summarizer, Classifier, Sentiment, NER, OCR, Embedding, Vector Search, Knowledge Graph Query, Calendar, Email Send, Slack Post, Teams Message, Jira Create, GitHub Issue, Confluence Page, S3 Upload, GCS Upload, Redis Get/Set, Mongo Query, Elasticsearch, Custom MCP Tool, A2A Agent Call, Browser Automation, Screenshot, Notification
- **Logic** (16): If/Else, Switch/Case, Loop, Map, Filter, Reduce, Parallel, Sequential, Wait, Retry, Error Handler, Timeout, Rate Limiter, Circuit Breaker, Human Approval Gate, Merge
- **Output** (10): Text Response, JSON Response, File Download, Email Send, Webhook POST, Database Write, Stream Response, Notification, Dashboard Update, Multi-Channel
- **Human-in-Loop** (8): Approval Gate, Review Step, Feedback Collector, Escalation, Assignment, Annotation, Verification, Manual Override
- **MCP** (12): MCP Server, MCP Client, MCP Tool Wrapper, MCP Resource, MCP Prompt, MCP Sampling, MCP Notification, MCP Auth, MCP Batch, MCP Stream, MCP Discovery, MCP Registry
- **Security** (10): DLP Scanner, PII Redactor, Content Filter, Guardrail Check, Classification, Encryption, Decryption, Access Control, Audit Logger, Compliance Check
- **Data** (14): RAG Retrieve, Vector Upsert, Document Loader, Text Splitter, Embedding Generator, Knowledge Base, Cache Get, Cache Set, Transform, Validate Schema, Enrich, Deduplicate, Aggregate, Export

```typescript
// components/builder/nodes/base-node.tsx
"use client";
import { Handle, Position, NodeProps } from "reactflow";
import { memo } from "react";

export interface NodeData {
  label: string;
  type: string;
  category: string;
  icon: React.ComponentType;
  config: Record<string, unknown>;
  status?: "idle" | "running" | "success" | "error";
  executionTime?: number;
}

export const BaseNode = memo(({ data, selected }: NodeProps<NodeData>) => {
  const Icon = data.icon;
  const statusColor = {
    idle: "border-muted",
    running: "border-blue-500 animate-pulse",
    success: "border-green-500",
    error: "border-red-500",
  }[data.status ?? "idle"];

  return (
    <div className={`px-4 py-3 rounded-lg border-2 bg-card shadow-sm min-w-[200px]
      ${statusColor} ${selected ? "ring-2 ring-primary" : ""}`}>
      <Handle type="target" position={Position.Top} className="w-3 h-3" />
      <div className="flex items-center gap-2">
        <div className="p-1.5 rounded-md bg-muted"><Icon className="w-4 h-4" /></div>
        <div>
          <p className="text-sm font-medium">{data.label}</p>
          <p className="text-xs text-muted-foreground">{data.category}</p>
        </div>
      </div>
      {data.executionTime && (
        <p className="text-xs text-muted-foreground mt-1">{data.executionTime}ms</p>
      )}
      <Handle type="source" position={Position.Bottom} className="w-3 h-3" />
    </div>
  );
});
BaseNode.displayName = "BaseNode";
```

```typescript
// stores/canvas-store.ts
import { create } from "zustand";
import { Node, Edge, applyNodeChanges, applyEdgeChanges, NodeChange, EdgeChange } from "reactflow";

interface CanvasState {
  nodes: Node[];
  edges: Edge[];
  selectedNodeId: string | null;
  undoStack: { nodes: Node[]; edges: Edge[] }[];
  redoStack: { nodes: Node[]; edges: Edge[] }[];
  onNodesChange: (changes: NodeChange[]) => void;
  onEdgesChange: (changes: EdgeChange[]) => void;
  addNode: (node: Node) => void;
  removeNode: (id: string) => void;
  selectNode: (id: string | null) => void;
  undo: () => void;
  redo: () => void;
  exportJSON: () => string;
  importJSON: (json: string) => void;
  clear: () => void;
}

export const useCanvasStore = create<CanvasState>((set, get) => ({
  nodes: [],
  edges: [],
  selectedNodeId: null,
  undoStack: [],
  redoStack: [],
  onNodesChange: (changes) => {
    set((state) => ({ nodes: applyNodeChanges(changes, state.nodes) }));
  },
  onEdgesChange: (changes) => {
    set((state) => ({ edges: applyEdgeChanges(changes, state.edges) }));
  },
  addNode: (node) => {
    const { nodes, edges } = get();
    set({
      undoStack: [...get().undoStack, { nodes, edges }],
      redoStack: [],
      nodes: [...nodes, node],
    });
  },
  removeNode: (id) => {
    const { nodes, edges } = get();
    set({
      undoStack: [...get().undoStack, { nodes, edges }],
      redoStack: [],
      nodes: nodes.filter((n) => n.id !== id),
      edges: edges.filter((e) => e.source !== id && e.target !== id),
    });
  },
  selectNode: (id) => set({ selectedNodeId: id }),
  undo: () => {
    const { undoStack, nodes, edges } = get();
    if (undoStack.length === 0) return;
    const prev = undoStack[undoStack.length - 1];
    set({
      undoStack: undoStack.slice(0, -1),
      redoStack: [...get().redoStack, { nodes, edges }],
      nodes: prev.nodes,
      edges: prev.edges,
    });
  },
  redo: () => {
    const { redoStack, nodes, edges } = get();
    if (redoStack.length === 0) return;
    const next = redoStack[redoStack.length - 1];
    set({
      redoStack: redoStack.slice(0, -1),
      undoStack: [...get().undoStack, { nodes, edges }],
      nodes: next.nodes,
      edges: next.edges,
    });
  },
  exportJSON: () => {
    const { nodes, edges } = get();
    return JSON.stringify({ nodes, edges }, null, 2);
  },
  importJSON: (json) => {
    const data = JSON.parse(json);
    set({ nodes: data.nodes ?? [], edges: data.edges ?? [] });
  },
  clear: () => {
    const { nodes, edges } = get();
    set({
      undoStack: [...get().undoStack, { nodes, edges }],
      redoStack: [],
      nodes: [],
      edges: [],
    });
  },
}));
```

**Canvas features**:
- Minimap (bottom-right corner)
- Zoom controls (+/−/fit)
- Keyboard shortcuts: Ctrl+Z undo, Ctrl+Y redo, Delete remove, Ctrl+C/V copy-paste nodes
- Connection validation: type-safe edges (LLM output → Tool input OK; Tool output → Input NOT OK)
- Version timeline slider: scrub through agent version history
- Export buttons: JSON, Python (LangGraph code), YAML
- Live preview: sandboxed iframe showing agent execution simulation
- Collaborative editing: presence avatars showing other users editing same agent

### 4. Natural Language Suggestion Bar

Top bar on the builder page — users type natural language and get agent graph suggestions.

- Autocomplete dropdown with recent prompts and popular templates
- Streaming response display (typing indicator)
- "Apply suggestion" button that generates nodes/edges on canvas
- Feedback thumbs up/down on suggestions
- Integrates with Agent-03 (NL Wizard) backend

### 5. Dashboard & Analytics (`/dashboard`)

Landing page after login — shows platform health and activity.

```typescript
// components/dashboard/stat-card.tsx
interface StatCardProps {
  title: string;
  value: string | number;
  change?: { value: number; direction: "up" | "down" };
  icon: React.ComponentType;
  href?: string;
}

export function StatCard({ title, value, change, icon: Icon, href }: StatCardProps) {
  return (
    <Card className="p-6">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm text-muted-foreground">{title}</p>
          <p className="text-2xl font-bold mt-1">{value}</p>
          {change && (
            <p className={`text-xs mt-1 ${change.direction === "up" ? "text-green-600" : "text-red-600"}`}>
              {change.direction === "up" ? "↑" : "↓"} {change.value}% from last period
            </p>
          )}
        </div>
        <div className="p-3 rounded-full bg-primary/10"><Icon className="w-6 h-6 text-primary" /></div>
      </div>
    </Card>
  );
}
```

**Dashboard sections**:
- Stat cards: Total Agents, Active Executions, Success Rate, Total Cost (24h), Avg Latency
- Execution feed: real-time list of recent agent runs with status badges
- Cost breakdown chart: Recharts bar chart by model/agent/team
- Agent health grid: status indicators (green/yellow/red) per deployed agent
- Quick actions: "Create Agent", "View Logs", "Manage Users"

### 6. Secrets Configuration UI (`/admin/secrets`)

Admin page for managing Vault-backed secrets. Only accessible to users with `secrets.manage` permission.

```typescript
// components/secrets/secret-card.tsx
"use client";
import { useState } from "react";
import { Eye, EyeOff, RotateCcw, Trash2, Clock } from "lucide-react";
import { useAuth } from "@/providers/auth-provider";

interface SecretCardProps {
  name: string;
  path: string;
  type: "api_key" | "oauth_token" | "certificate" | "database" | "custom";
  lastRotated: string;
  nextRotation?: string;
  status: "active" | "expiring_soon" | "expired" | "revoked";
}

export function SecretCard({ name, path, type, lastRotated, nextRotation, status }: SecretCardProps) {
  const [revealed, setRevealed] = useState(false);
  const [value, setValue] = useState<string | null>(null);
  const { hasPermission } = useAuth();

  async function revealSecret() {
    if (!hasPermission("secrets.read_value")) return;
    const res = await fetch(`/api/v1/secrets/${encodeURIComponent(path)}/reveal`, {
      method: "POST",
      credentials: "include",
    });
    if (res.ok) {
      const data = await res.json();
      setValue(data.value);
      setRevealed(true);
      setTimeout(() => { setRevealed(false); setValue(null); }, 30_000); // auto-hide after 30s
    }
  }

  const statusBadge = {
    active: "bg-green-100 text-green-700",
    expiring_soon: "bg-yellow-100 text-yellow-700",
    expired: "bg-red-100 text-red-700",
    revoked: "bg-gray-100 text-gray-500",
  }[status];

  return (
    <div className="flex items-center justify-between p-4 border rounded-lg">
      <div className="flex-1">
        <div className="flex items-center gap-2">
          <p className="font-medium">{name}</p>
          <span className={`text-xs px-2 py-0.5 rounded-full ${statusBadge}`}>{status}</span>
        </div>
        <p className="text-xs text-muted-foreground mt-1 font-mono">{path}</p>
        <div className="flex items-center gap-4 mt-2 text-xs text-muted-foreground">
          <span className="flex items-center gap-1"><Clock className="w-3 h-3" /> Rotated: {lastRotated}</span>
          {nextRotation && <span>Next: {nextRotation}</span>}
        </div>
      </div>
      <div className="flex items-center gap-2">
        {revealed ? (
          <code className="text-xs bg-muted px-2 py-1 rounded max-w-[200px] truncate">{value}</code>
        ) : (
          <code className="text-xs bg-muted px-2 py-1 rounded">••••••••••••</code>
        )}
        <Button variant="ghost" size="icon" onClick={revealed ? () => setRevealed(false) : revealSecret}
          disabled={!hasPermission("secrets.read_value")}>
          {revealed ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
        </Button>
        <Button variant="ghost" size="icon" disabled={!hasPermission("secrets.rotate")}>
          <RotateCcw className="w-4 h-4" />
        </Button>
      </div>
    </div>
  );
}
```

**Secrets pages**:
- Vault connection status banner (connected/disconnected/degraded)
- Secret list with search, filter by type/status
- Create secret wizard: step 1 (type), step 2 (name + value), step 3 (rotation policy), step 4 (confirm)
- Provider credential setup: guided forms for OpenAI, Anthropic, Azure, AWS, GCP credentials
- Rotation schedule calendar view
- Audit trail per secret (who accessed, when)

### 7. User & Team Management (`/admin/users`, `/admin/teams`)

Full CRUD admin interface for managing platform users.

- User list table: avatar, name, email, roles, status (active/invited/suspended), last login
- Search by name/email, filter by role/status, bulk actions (suspend, delete, change role)
- User detail page: profile info, assigned roles, permissions matrix, activity log, active sessions (with "revoke session" button), SCIM sync status
- Invite user flow: email input → role selection → workspace assignment → send invite
- SCIM sync status indicator: shows auto-provisioned users vs manual
- Team management: create team, assign members, team-level permissions
- Workspace assignment: drag-drop users into workspaces

### 8. Workspace Management

- Workspace switcher in top nav (dropdown with workspace list + "Create new")
- Workspace settings page: name, icon, description, member list, resource limits
- Per-workspace agent list
- Workspace-scoped dashboards (stats filtered to current workspace)

### 9. Admin Settings (platform_admin only)

- **Identity Providers** (`/admin/idp`): Add/configure SAML and OIDC providers (entity ID, SSO URL, certificate upload, attribute mapping)
- **DLP Policies** (`/admin/dlp-policies`): Visual policy editor (regex patterns, semantic rules, sensitivity levels)
- **Model Registry** (`/admin/models`): View registered models, usage stats, cost per token, enable/disable
- **Cost Budgets** (`/admin/billing`): Set per-workspace/per-team budgets, alerts, chargeback reports
- **Audit Log** (`/admin/audit`): Searchable, filterable audit log (who, what, when, where)
- **System Health** (`/admin/health`): Service status grid, Vault health, DB connections, queue depth, error rates

### 10. Theming & Accessibility

- Dark/light mode toggle (persisted in localStorage + respects `prefers-color-scheme`)
- shadcn/ui theme with CSS custom properties
- WCAG 2.1 AA: focus rings, aria labels, screen reader announcements, skip-to-content link
- Keyboard navigation: all flows completable without mouse
- Responsive: desktop-first, tablet breakpoints (1024px), minimum 768px viewport

### 11. State Management Architecture

- **TanStack Query v5**: all server state (agents, users, executions, models, secrets)
  - Configured with stale times, retry logic, optimistic updates
  - Query key factory pattern for consistent cache invalidation
- **Zustand**: client-only state (canvas nodes/edges, UI preferences, sidebar collapsed state)
- **WebSocket**: real-time updates via `/ws/events` (execution status, presence, notifications)
  - Auto-reconnect with exponential backoff
  - Event types: `execution.started`, `execution.completed`, `agent.updated`, `presence.update`
- **Optimistic updates**: CRUD operations update cache immediately, rollback on error

### 12. Real-Time & Collaboration

- WebSocket connection for live execution status updates
- Presence system: see who's viewing/editing the same agent
- Toast notifications for system events (deployment completed, approval needed, budget alert)
- Server-Sent Events fallback if WebSocket unavailable

---

## Output Structure

```
frontend/
├── package.json
├── next.config.ts
├── tailwind.config.ts
├── tsconfig.json
├── .env.example                          # NEXT_PUBLIC_API_URL, NEXT_PUBLIC_WS_URL, etc.
├── .eslintrc.cjs
├── playwright.config.ts
├── public/
│   ├── logo.svg
│   ├── favicon.ico
│   └── locales/                          # i18n JSON files
├── app/
│   ├── layout.tsx                        # Root layout with AuthProvider, ThemeProvider, QueryProvider
│   ├── page.tsx                          # Redirect to /dashboard
│   ├── login/
│   │   ├── page.tsx                      # Login page (email/password + SSO buttons)
│   │   ├── mfa/
│   │   │   └── page.tsx                  # MFA challenge page
│   │   ├── callback/
│   │   │   └── page.tsx                  # SSO callback handler
│   │   └── reset-password/
│   │       └── page.tsx
│   ├── (authenticated)/                  # Route group — ProtectedRoute wrapper
│   │   ├── layout.tsx                    # Sidebar + TopNav layout
│   │   ├── dashboard/
│   │   │   └── page.tsx                  # Dashboard with stat cards + charts
│   │   ├── agents/
│   │   │   ├── page.tsx                  # Agent list (grid + table views)
│   │   │   └── [id]/
│   │   │       ├── page.tsx              # Agent detail (overview tab)
│   │   │       ├── executions/
│   │   │       │   └── page.tsx          # Agent execution history
│   │   │       ├── versions/
│   │   │       │   └── page.tsx          # Version timeline
│   │   │       └── settings/
│   │   │           └── page.tsx          # Agent config
│   │   ├── builder/
│   │   │   ├── page.tsx                  # New agent builder (canvas)
│   │   │   └── [id]/
│   │   │       └── page.tsx              # Edit existing agent in builder
│   │   ├── executions/
│   │   │   ├── page.tsx                  # All executions list
│   │   │   └── [id]/
│   │   │       └── page.tsx              # Execution detail (trace, logs, cost)
│   │   ├── templates/
│   │   │   ├── page.tsx                  # Template marketplace browser
│   │   │   └── [id]/
│   │   │       └── page.tsx              # Template detail + "Use" button
│   │   ├── connectors/
│   │   │   ├── page.tsx                  # Connector list + status
│   │   │   └── [id]/
│   │   │       └── page.tsx              # Connector config
│   │   ├── documents/
│   │   │   ├── page.tsx                  # Document list (RAG)
│   │   │   └── upload/
│   │   │       └── page.tsx              # Upload + processing status
│   │   ├── security/
│   │   │   ├── page.tsx                  # Security overview
│   │   │   ├── dlp/
│   │   │   │   └── page.tsx              # DLP scanner dashboard
│   │   │   ├── redteam/
│   │   │   │   └── page.tsx              # Red team campaigns
│   │   │   ├── guardrails/
│   │   │   │   └── page.tsx              # Guardrail policies
│   │   │   └── audit/
│   │   │       └── page.tsx              # Audit log viewer
│   │   └── admin/
│   │       ├── page.tsx                  # Admin overview (platform_admin only)
│   │       ├── users/
│   │       │   ├── page.tsx              # User list
│   │       │   ├── [id]/
│   │       │   │   └── page.tsx          # User detail
│   │       │   └── invite/
│   │       │       └── page.tsx          # Invite user form
│   │       ├── teams/
│   │       │   ├── page.tsx              # Team list
│   │       │   └── [id]/
│   │       │       └── page.tsx          # Team detail
│   │       ├── workspaces/
│   │       │   ├── page.tsx              # Workspace list
│   │       │   └── [id]/
│   │       │       └── page.tsx          # Workspace settings
│   │       ├── idp/
│   │       │   ├── page.tsx              # Identity provider list
│   │       │   └── new/
│   │       │       └── page.tsx          # Add IdP wizard
│   │       ├── secrets/
│   │       │   ├── page.tsx              # Secrets list
│   │       │   └── new/
│   │       │       └── page.tsx          # Create secret wizard
│   │       ├── models/
│   │       │   └── page.tsx              # Model registry
│   │       ├── billing/
│   │       │   └── page.tsx              # Cost & billing dashboard
│   │       └── health/
│   │           └── page.tsx              # System health dashboard
├── components/
│   ├── ui/                               # shadcn/ui components (button, card, dialog, etc.)
│   ├── auth/
│   │   ├── login-form.tsx
│   │   ├── sso-buttons.tsx
│   │   ├── mfa-challenge.tsx
│   │   ├── protected-route.tsx
│   │   └── session-timeout-modal.tsx
│   ├── layout/
│   │   ├── sidebar.tsx                   # RBAC-gated sidebar navigation
│   │   ├── top-nav.tsx                   # Workspace switcher + user menu
│   │   ├── breadcrumbs.tsx
│   │   └── theme-toggle.tsx
│   ├── builder/
│   │   ├── canvas.tsx                    # React Flow wrapper
│   │   ├── node-palette.tsx              # Draggable node list with search
│   │   ├── properties-panel.tsx          # Dynamic form for selected node
│   │   ├── toolbar.tsx                   # Save, export, undo/redo, zoom
│   │   ├── version-timeline.tsx          # Version scrubber slider
│   │   ├── nl-suggestion-bar.tsx         # Natural language input bar
│   │   ├── minimap.tsx
│   │   ├── connection-validator.ts       # Type-safe edge validation
│   │   ├── export-dialog.tsx             # JSON/Python/YAML export
│   │   ├── live-preview.tsx              # Sandboxed iframe preview
│   │   ├── presence-avatars.tsx          # Collaborative editing indicators
│   │   └── nodes/
│   │       ├── base-node.tsx
│   │       ├── llm-node.tsx
│   │       ├── tool-node.tsx
│   │       ├── logic-node.tsx
│   │       ├── input-node.tsx
│   │       ├── output-node.tsx
│   │       ├── human-node.tsx
│   │       ├── mcp-node.tsx
│   │       ├── security-node.tsx
│   │       ├── data-node.tsx
│   │       └── node-registry.ts          # Maps node type → component + config schema
│   ├── dashboard/
│   │   ├── stat-card.tsx
│   │   ├── execution-feed.tsx
│   │   ├── cost-chart.tsx
│   │   ├── agent-health-grid.tsx
│   │   └── quick-actions.tsx
│   ├── secrets/
│   │   ├── secret-card.tsx
│   │   ├── secret-list.tsx
│   │   ├── create-secret-wizard.tsx
│   │   ├── provider-setup.tsx
│   │   └── rotation-calendar.tsx
│   ├── users/
│   │   ├── user-table.tsx
│   │   ├── user-detail.tsx
│   │   ├── invite-form.tsx
│   │   ├── role-selector.tsx
│   │   └── scim-status-badge.tsx
│   ├── common/
│   │   ├── data-table.tsx                # Reusable TanStack Table wrapper
│   │   ├── search-input.tsx
│   │   ├── pagination.tsx
│   │   ├── empty-state.tsx
│   │   ├── error-boundary.tsx
│   │   ├── loading-skeleton.tsx
│   │   ├── confirm-dialog.tsx
│   │   └── toast-provider.tsx
│   └── charts/
│       ├── bar-chart.tsx                 # Recharts wrapper
│       ├── line-chart.tsx
│       ├── pie-chart.tsx
│       └── area-chart.tsx
├── hooks/
│   ├── use-agents.ts                     # TanStack Query hooks for agents CRUD
│   ├── use-executions.ts
│   ├── use-users.ts
│   ├── use-secrets.ts
│   ├── use-models.ts
│   ├── use-connectors.ts
│   ├── use-templates.ts
│   ├── use-websocket.ts                  # WebSocket connection hook
│   ├── use-presence.ts                   # Collaborative presence hook
│   ├── use-debounce.ts
│   ├── use-media-query.ts
│   └── use-keyboard-shortcut.ts
├── lib/
│   ├── api-client.ts                     # Fetch wrapper with auth headers + error handling
│   ├── query-client.ts                   # TanStack QueryClient config
│   ├── query-keys.ts                     # Query key factory
│   ├── websocket-client.ts               # WebSocket manager with reconnect
│   ├── utils.ts                          # cn(), formatDate(), etc.
│   └── constants.ts                      # Route paths, permissions, node categories
├── providers/
│   ├── auth-provider.tsx                 # AuthContext + SSO + session management
│   ├── theme-provider.tsx                # Dark/light mode
│   ├── query-provider.tsx                # TanStack QueryClientProvider
│   ├── websocket-provider.tsx            # WebSocket context
│   └── toast-provider.tsx                # Sonner toast notifications
├── stores/
│   ├── canvas-store.ts                   # Zustand: React Flow nodes/edges + undo/redo
│   ├── ui-store.ts                       # Zustand: sidebar state, view preferences
│   └── workspace-store.ts               # Zustand: current workspace
├── types/
│   ├── agent.ts                          # Agent, AgentVersion, AgentNode, AgentEdge
│   ├── execution.ts                      # Execution, ExecutionStep, ExecutionTrace
│   ├── user.ts                           # User, Role, Permission, Team
│   ├── secret.ts                         # Secret, SecretMetadata, RotationPolicy
│   ├── model.ts                          # Model, ModelProvider, ModelConfig
│   ├── connector.ts                      # Connector, ConnectorInstance, ConnectorCredential
│   ├── template.ts                       # Template, TemplateCategory
│   ├── common.ts                         # PaginatedResponse, ApiError, SortOrder
│   └── node-types.ts                     # Node type definitions for React Flow
├── tests/
│   ├── e2e/
│   │   ├── login.spec.ts                 # SSO login + MFA E2E
│   │   ├── builder.spec.ts               # Canvas drag-drop + save
│   │   ├── dashboard.spec.ts             # Dashboard loads with data
│   │   ├── admin-users.spec.ts           # User CRUD
│   │   ├── secrets.spec.ts               # Secrets management
│   │   └── rbac.spec.ts                  # Permission gates
│   └── unit/
│       ├── auth-provider.test.tsx
│       ├── canvas-store.test.ts
│       ├── permission-gate.test.tsx
│       └── api-client.test.ts
└── Dockerfile                            # Multi-stage: build + nginx serve
```

---

## Backend API Endpoints Consumed

All API calls go through `lib/api-client.ts` which adds auth headers and handles token refresh.

```
# Authentication
POST   /api/v1/auth/login                    # Email/password login
POST   /api/v1/auth/logout                   # Logout (clear session)
GET    /api/v1/auth/me                       # Get current user
POST   /api/v1/auth/refresh                  # Refresh access token
GET    /api/v1/auth/sso/redirect             # SSO redirect (SAML/OIDC)
POST   /api/v1/auth/sso/callback             # SSO callback handler
POST   /api/v1/auth/mfa/verify               # Verify MFA code
POST   /api/v1/auth/mfa/setup                # Setup MFA (get QR code)
POST   /api/v1/auth/password/reset           # Request password reset
POST   /api/v1/auth/password/change          # Change password

# Agents
GET    /api/v1/agents                        # List agents (paginated)
POST   /api/v1/agents                        # Create agent
GET    /api/v1/agents/{id}                   # Get agent detail
PUT    /api/v1/agents/{id}                   # Update agent
DELETE /api/v1/agents/{id}                   # Delete agent
POST   /api/v1/agents/{id}/deploy            # Deploy agent
POST   /api/v1/agents/{id}/execute           # Execute agent
GET    /api/v1/agents/{id}/versions          # List versions
POST   /api/v1/agents/{id}/versions          # Create version
GET    /api/v1/agents/{id}/graph             # Get agent graph (nodes/edges)
PUT    /api/v1/agents/{id}/graph             # Save agent graph

# Executions
GET    /api/v1/executions                    # List executions
GET    /api/v1/executions/{id}               # Execution detail (trace)
GET    /api/v1/executions/{id}/logs          # Execution logs
POST   /api/v1/executions/{id}/cancel        # Cancel running execution
WS     /ws/executions/{id}                   # Live execution stream

# Users & Teams (Admin)
GET    /api/v1/users                         # List users
POST   /api/v1/users                         # Create user
GET    /api/v1/users/{id}                    # User detail
PUT    /api/v1/users/{id}                    # Update user
DELETE /api/v1/users/{id}                    # Deactivate user
POST   /api/v1/users/{id}/roles              # Assign role
DELETE /api/v1/users/{id}/roles/{role}       # Remove role
GET    /api/v1/users/{id}/sessions           # List active sessions
DELETE /api/v1/users/{id}/sessions/{sid}     # Revoke session
POST   /api/v1/users/invite                  # Send invite email
GET    /api/v1/teams                         # List teams
POST   /api/v1/teams                         # Create team
PUT    /api/v1/teams/{id}                    # Update team
POST   /api/v1/teams/{id}/members            # Add member
DELETE /api/v1/teams/{id}/members/{uid}      # Remove member

# Workspaces
GET    /api/v1/workspaces                    # List workspaces
POST   /api/v1/workspaces                    # Create workspace
GET    /api/v1/workspaces/{id}               # Workspace detail
PUT    /api/v1/workspaces/{id}               # Update workspace

# Secrets
GET    /api/v1/secrets                       # List secrets (metadata only)
POST   /api/v1/secrets                       # Create secret
GET    /api/v1/secrets/{path}                # Secret metadata
POST   /api/v1/secrets/{path}/reveal         # Reveal value (audited)
PUT    /api/v1/secrets/{path}                # Update secret
DELETE /api/v1/secrets/{path}                # Delete secret
POST   /api/v1/secrets/{path}/rotate         # Trigger rotation
GET    /api/v1/secrets/providers             # List provider templates

# Models
GET    /api/v1/models                        # List models
POST   /api/v1/models                        # Register model
PUT    /api/v1/models/{id}                   # Update model config
GET    /api/v1/models/{id}/usage             # Model usage stats

# Templates
GET    /api/v1/templates                     # List templates
GET    /api/v1/templates/{id}                # Template detail
POST   /api/v1/templates/{id}/use            # Create agent from template

# Connectors
GET    /api/v1/connectors                    # List connectors
GET    /api/v1/connectors/{id}               # Connector detail
POST   /api/v1/connectors/{id}/configure     # Configure connector
GET    /api/v1/connectors/{id}/health        # Connector health

# NL Builder
POST   /api/v1/nl-builder/describe           # Submit NL description
POST   /api/v1/nl-builder/plan               # Generate plan from description
POST   /api/v1/nl-builder/build              # Generate graph from plan

# Documents (RAG)
GET    /api/v1/documents                     # List documents
POST   /api/v1/documents/upload              # Upload document
GET    /api/v1/documents/{id}/status         # Processing status

# Security
GET    /api/v1/dlp/scan                      # Run DLP scan
GET    /api/v1/guardrails                    # List guardrail policies
GET    /api/v1/audit-log                     # Query audit logs
GET    /api/v1/red-team/campaigns            # List red team campaigns

# Cost
GET    /api/v1/cost/summary                  # Cost summary
GET    /api/v1/cost/breakdown                # Detailed cost breakdown
GET    /api/v1/cost/budgets                  # Budget status

# System (platform_admin)
GET    /api/v1/system/health                 # System health check
GET    /api/v1/system/idp                    # List identity providers
POST   /api/v1/system/idp                    # Add identity provider
GET    /api/v1/system/metrics                # Platform metrics

# WebSocket
WS     /ws/events                            # Real-time event stream (execution, presence, notifications)
```

---

## Verify Commands

```bash
# Frontend builds without errors
cd ~/Scripts/Archon/frontend && npm run build

# Lint passes
cd ~/Scripts/Archon/frontend && npm run lint

# TypeScript compiles clean
cd ~/Scripts/Archon/frontend && npx tsc --noEmit

# Unit tests pass
cd ~/Scripts/Archon/frontend && npm test

# E2E tests pass
cd ~/Scripts/Archon/frontend && npx playwright test

# No hardcoded secrets
cd ~/Scripts/Archon && ! grep -rn 'sk-[a-zA-Z0-9]' --include='*.ts' --include='*.tsx' frontend/ || echo 'FAIL'

# No hardcoded API URLs (should use env vars)
cd ~/Scripts/Archon && ! grep -rn 'localhost:8000' --include='*.ts' --include='*.tsx' frontend/app/ frontend/components/ || echo 'FAIL'

# Required files exist
test -f ~/Scripts/Archon/frontend/package.json && \
test -f ~/Scripts/Archon/frontend/next.config.ts && \
test -f ~/Scripts/Archon/frontend/tailwind.config.ts && \
test -f ~/Scripts/Archon/frontend/playwright.config.ts && \
test -f ~/Scripts/Archon/frontend/Dockerfile && \
echo 'OK'

# Node types registered (should have 200+)
cd ~/Scripts/Archon && grep -c "registerNode\|nodeTypes\[" frontend/components/builder/nodes/node-registry.ts

# Auth provider exists and exports useAuth
cd ~/Scripts/Archon && grep -q "export function useAuth" frontend/providers/auth-provider.tsx && echo 'OK'

# RBAC PermissionGate component exists
cd ~/Scripts/Archon && grep -q "export function PermissionGate" frontend/components/layout/sidebar.tsx && echo 'OK'

# Lighthouse CI (if available)
cd ~/Scripts/Archon/frontend && npx lhci autorun --preset=desktop 2>/dev/null || echo 'Lighthouse CI not configured'

# Docker build succeeds
cd ~/Scripts/Archon/frontend && docker build -t archon-frontend-test . 2>&1 | tail -1

# File count check (expect 80+ component files)
test $(find ~/Scripts/Archon/frontend/components -name '*.tsx' 2>/dev/null | wc -l | tr -d ' ') -ge 40 && echo 'OK' || echo 'WARN: fewer than expected components'
```

---

## Learnings Protocol

After completing your work:
1. Document any unexpected issues in `~/Scripts/Archon/.sdd/learnings/agent-02-learnings.md`
2. Include: what failed, why, how you fixed it, and advice for future agents
3. Flag any backend API gaps discovered during frontend development
4. Note any shadcn/ui component limitations encountered

---

## Acceptance Criteria

- [ ] SSO login page renders with email/password form + SAML/OIDC SSO buttons
- [ ] SSO redirect flow completes end-to-end (redirect → IdP → callback → dashboard)
- [ ] MFA challenge page renders and validates TOTP codes
- [ ] Session timeout warning modal appears 5 minutes before expiry
- [ ] Sidebar navigation shows/hides items based on user's RBAC role
- [ ] PermissionGate component correctly blocks unauthorized access
- [ ] React Flow canvas renders with node palette showing 200+ node types
- [ ] Drag-and-drop from palette creates nodes on canvas
- [ ] Connection validation rejects invalid edge types
- [ ] Undo/redo works for all canvas operations (Ctrl+Z/Y)
- [ ] Export dialog generates valid JSON, Python, and YAML
- [ ] Version timeline slider navigates agent version history
- [ ] NL suggestion bar sends query and displays streaming response
- [ ] "Apply suggestion" generates nodes/edges on canvas
- [ ] Dashboard loads with stat cards, execution feed, and cost charts
- [ ] Real-time execution status updates via WebSocket
- [ ] Secrets page lists all secrets with masked values
- [ ] Secret reveal requires `secrets.read_value` permission and auto-hides after 30s
- [ ] Create secret wizard completes 4-step flow
- [ ] User management: list, search, filter, invite, suspend, delete
- [ ] User detail page shows profile, roles, sessions, activity log
- [ ] Workspace switcher in top nav works
- [ ] Admin pages accessible ONLY to platform_admin/tenant_admin roles
- [ ] Dark/light mode toggle persists across sessions
- [ ] All keyboard shortcuts functional (Ctrl+Z, Delete, Ctrl+C/V, etc.)
- [ ] Lighthouse performance score > 90
- [ ] WCAG 2.1 AA: focus rings, aria labels, keyboard-navigable
- [ ] All Playwright E2E tests pass (login, builder, dashboard, admin, RBAC)
- [ ] Zero hardcoded credentials or API URLs in source
- [ ] Docker build produces valid container image
- [ ] Frontend starts and renders without console errors
