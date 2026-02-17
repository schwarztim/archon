# Agent-15: Live Interactive Components & Embedded UIs

> **Phase**: 5 | **Dependencies**: Agent-01 (Core Backend), Agent-02 (React Flow Builder), Agent-00 (Secrets Vault) | **Priority**: MEDIUM
> **Enables agents to render rich, interactive UI components directly in conversations. The human-in-loop experience depends on this.**

---

## Identity

You are Agent-15: the Live Interactive Components & Embedded UIs Architect. You build the complete system that allows agents to embed rich, interactive React components (forms, charts, tables, approval panels, code editors) directly in their responses — with session-bound authentication, component-level RBAC, secure sandboxed rendering, real-time streaming updates via WebSocket, and a visual component builder.

## Mission

Build a production-grade interactive component system that:
1. Enables agents to embed any registered UI component (chart, form, table, etc.) in their responses
2. Enforces session-bound authentication — components make API calls on behalf of the authenticated user, never with service credentials
3. Implements component-level RBAC — components render differently based on user permissions
4. Renders components in sandboxed iframes with strict Content-Security-Policy for XSS prevention
5. Communicates via a secure WebSocket protocol with heartbeat, reconnection, and origin validation
6. Supports real-time streaming updates — components update live as agent execution progresses
7. Provides a visual component builder in the React Flow canvas for drag-and-drop component configuration

## Requirements

### Session-Bound Authentication

**Every interactive component inherits the user's auth session**
- Components never use service credentials — all API calls made on behalf of the authenticated user
- Session token propagation:
  ```python
  class ComponentSession:
      """Manages auth context for interactive components."""
      
      session_id: str                          # WebSocket session ID
      user_id: uuid.UUID                       # Authenticated user
      tenant_id: uuid.UUID                     # User's tenant
      access_token: str                        # User's JWT (short-lived)
      permissions: list[str]                   # Cached permission set
      component_sessions: dict[str, ComponentContext]  # Per-component state
      created_at: datetime
      last_activity: datetime
      expires_at: datetime                     # Session expiry
  ```
- Session token passed via secure WebSocket (not URL params, not cookies for iframe):
  ```typescript
  // Client-side: establish authenticated WebSocket
  const ws = new WebSocket(`wss://${host}/ws/components`);
  ws.onopen = () => {
    ws.send(JSON.stringify({
      type: "auth",
      token: sessionStorage.getItem("access_token"),
      component_session_id: crypto.randomUUID()
    }));
  };
  ```
- Token refresh: when access token nears expiry, WebSocket handler requests refresh from auth service
- Session binding: each component instance bound to a specific user session — cannot be hijacked
- Session timeout: idle components timeout after 30 minutes (configurable per tenant)
- Multi-tab support: same user can have components open in multiple tabs, each with its own session

### Component-Level RBAC

**Components render differently based on user permissions**
- Permission-aware rendering rules:
  ```python
  class ComponentPermission:
      """Defines RBAC rules for a component."""
      component_type: str                      # "data_table", "approval_panel"
      visibility_rule: str                     # "always", "role_based", "permission_based"
      required_permissions: list[str]          # ["agents:read", "data:export"]
      column_permissions: dict[str, list[str]] # {"salary": ["hr:read"], "ssn": ["hr:admin"]}
      action_permissions: dict[str, list[str]] # {"approve": ["approver"], "export": ["data:export"]}
      conditional_rules: list[ConditionalRule] # Dynamic visibility rules
  ```
- **DataTable component**: shows only columns the user has clearance for
  ```typescript
  // Server-side: filter columns before sending to client
  interface ColumnConfig {
    field: string;
    label: string;
    visible: boolean;           // Based on user permissions
    sortable: boolean;
    filterable: boolean;
    exportable: boolean;        // Only if user has data:export permission
    requiredPermission?: string; // Column hidden if user lacks this
  }
  ```
- **ApprovalPanel component**: disabled for non-approvers, shows approve/reject buttons only for users with `approval:execute` permission, read-only view for observers
- **Admin-only actions**: edit, delete, configure actions hidden from viewers; buttons not rendered (not just disabled) to prevent DOM inspection
- **Fallback rendering**: if user lacks all permissions for a component, render a "You don't have access" placeholder with option to request access
- **Permission cache**: permissions cached on WebSocket session establishment, invalidated on role change

### Component Registry

**Pre-built component library with registration system**

```typescript
// Component registry — all available components
interface ComponentRegistry {
  register(component: ComponentDefinition): void;
  get(type: string): ComponentDefinition | undefined;
  list(): ComponentDefinition[];
  validate(type: string, props: Record<string, unknown>): ValidationResult;
}

interface ComponentDefinition {
  type: string;                              // Unique identifier
  displayName: string;                       // Human-readable name
  category: ComponentCategory;               // UI grouping
  version: string;                           // Semantic version
  propsSchema: JSONSchema;                   // JSON Schema for prop validation
  eventsSchema: Record<string, JSONSchema>;  // Events this component can emit
  defaultProps: Record<string, unknown>;     // Default prop values
  permissions: ComponentPermission;          // RBAC configuration
  renderer: React.ComponentType<any>;        // React component
  icon: string;                              // Icon for builder
  documentation: string;                     // Usage docs (Markdown)
}
```

**Pre-built components:**

| Component | Category | Description | Key Props |
|-----------|----------|-------------|-----------|
| `DataTable` | Data Display | Sortable, filterable, exportable table | `columns`, `data`, `pagination`, `onSort`, `onFilter`, `onExport` |
| `Chart` | Data Display | Line, bar, pie, scatter, treemap (via Recharts) | `type`, `data`, `xAxis`, `yAxis`, `legend`, `colors` |
| `MetricCard` | Data Display | Single metric with trend indicator | `label`, `value`, `trend`, `sparkline`, `unit` |
| `Form` | Input | Dynamic form with validation | `fields`, `values`, `onSubmit`, `validation`, `layout` |
| `ApprovalPanel` | Action | Approve/reject with comments | `request`, `approvers`, `onApprove`, `onReject`, `history` |
| `FileUploader` | Input | Drag-and-drop file upload | `accept`, `maxSize`, `multiple`, `onUpload`, `progress` |
| `CodeEditor` | Input | Monaco-based code editor | `language`, `value`, `onChange`, `readOnly`, `theme` |
| `MapView` | Data Display | Geographic map with markers | `center`, `zoom`, `markers`, `layers`, `onClick` |
| `Timeline` | Data Display | Chronological event timeline | `events`, `orientation`, `groupBy`, `onEventClick` |
| `KanbanBoard` | Layout | Drag-and-drop kanban columns | `columns`, `cards`, `onMove`, `onAdd`, `onEdit` |
| `Calendar` | Data Display | Calendar with events | `events`, `view`, `onDateSelect`, `onEventClick` |
| `ProgressTracker` | Status | Multi-step progress indicator | `steps`, `currentStep`, `status`, `onStepClick` |
| `StatusBadge` | Status | Status indicator with icon | `status`, `label`, `variant`, `pulse` |
| `Accordion` | Layout | Collapsible content sections | `sections`, `multiExpand`, `defaultExpanded` |
| `Tabs` | Layout | Tabbed content panels | `tabs`, `activeTab`, `onChange`, `variant` |
| `Stepper` | Layout | Multi-step wizard | `steps`, `currentStep`, `onNext`, `onBack`, `validation` |
| `ImageGallery` | Media | Image carousel with lightbox | `images`, `thumbnails`, `onSelect`, `zoom` |
| `MarkdownRenderer` | Media | Rendered Markdown content | `content`, `allowHtml`, `syntaxHighlight` |
| `ConfirmDialog` | Action | Confirmation modal | `title`, `message`, `onConfirm`, `onCancel`, `variant` |
| `ButtonGroup` | Action | Grouped action buttons | `buttons`, `variant`, `size`, `onAction` |

### Secure Rendering

**Components rendered in sandboxed iframes with strict CSP**
- Sandboxed iframe configuration:
  ```html
  <iframe
    sandbox="allow-scripts allow-forms allow-same-origin"
    referrerpolicy="no-referrer"
    csp="default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src wss://*.archon.com; img-src 'self' data:; font-src 'self';"
    srcdoc="<!-- component HTML -->"
  ></iframe>
  ```
- **No access to parent window**: iframe cannot access parent DOM, cookies, or storage
- **Communication via postMessage** with strict origin validation:
  ```typescript
  // Parent → iframe communication
  class SecureComponentBridge {
    private allowedOrigins: Set<string>;
    
    sendToComponent(componentId: string, message: ComponentMessage): void {
      const iframe = this.getComponentFrame(componentId);
      iframe.contentWindow?.postMessage(
        { ...message, nonce: this.generateNonce() },
        this.getComponentOrigin(componentId)  // Strict origin
      );
    }
    
    handleMessage(event: MessageEvent): void {
      // Validate origin
      if (!this.allowedOrigins.has(event.origin)) {
        console.warn(`Blocked message from unauthorized origin: ${event.origin}`);
        return;
      }
      // Validate message structure
      const message = this.validateMessage(event.data);
      if (!message) return;
      // Route to handler
      this.routeMessage(message);
    }
  }
  ```
- **XSS prevention**:
  - All component props sanitized via DOMPurify before rendering
  - No `dangerouslySetInnerHTML` — all content rendered through React's safe mechanisms
  - CSP blocks inline scripts, external scripts, and eval
  - Component source code reviewed for XSS vectors during registration
- **Resource limits**: per-iframe memory limit (50MB), CPU throttling if unresponsive
- **Error isolation**: if a component crashes, only that iframe is affected — parent UI unaffected

### WebSocket Protocol

**Bi-directional communication between agent execution and rendered components**

```typescript
// WebSocket message protocol
interface ComponentMessage {
  type: "render" | "update" | "input" | "action" | "auth" | "heartbeat" | "error" | "destroy";
  component_id: string;                      // Unique ID for this component instance
  session_id: string;                        // User's component session
  timestamp: number;                         // Unix timestamp (ms)
  data: Record<string, unknown>;             // Type-specific payload
  auth_token?: string;                       // JWT for authenticated actions
  correlation_id?: string;                   // For request-response pairing
}

// Message types:
// "render"    — Agent → Client: render a new component
// "update"    — Agent → Client: update existing component's props/data
// "input"     — Client → Agent: user input (form field change, selection)
// "action"    — Client → Agent: user action (button click, form submit, approval)
// "auth"      — Client → Server: authenticate WebSocket session
// "heartbeat" — Bi-directional: keepalive ping/pong
// "error"     — Server → Client: error notification
// "destroy"   — Agent → Client: remove component from UI
```

- **Server-side protocol handler**:
  ```python
  class ComponentWebSocketHandler:
      """Handles WebSocket communication for interactive components."""
      
      async def handle_connection(self, websocket: WebSocket):
          # 1. Authenticate
          auth_msg = await websocket.receive_json()
          session = await self.authenticate(auth_msg["token"])
          if not session:
              await websocket.close(code=4001, reason="Authentication failed")
              return
          
          # 2. Register session
          self.sessions[session.session_id] = ComponentSession(
              websocket=websocket,
              user_id=session.user_id,
              tenant_id=session.tenant_id,
              permissions=session.permissions
          )
          
          # 3. Start heartbeat
          heartbeat_task = asyncio.create_task(self.heartbeat_loop(websocket, session))
          
          # 4. Message loop
          try:
              async for message in websocket.iter_json():
                  await self.route_message(session, message)
          finally:
              heartbeat_task.cancel()
              del self.sessions[session.session_id]
      
      async def render_component(
          self, session_id: str, component_type: str,
          props: dict, permissions: ComponentPermission
      ) -> str:
          """Agent calls this to render a component in the user's chat."""
          component_id = str(uuid.uuid4())
          session = self.sessions[session_id]
          
          # Filter props based on user permissions
          filtered_props = self.apply_rbac(props, permissions, session.permissions)
          
          await session.websocket.send_json({
              "type": "render",
              "component_id": component_id,
              "component_type": component_type,
              "props": filtered_props,
              "timestamp": time.time()
          })
          return component_id
  ```

- **Heartbeat + reconnection**:
  - Heartbeat interval: 30 seconds (configurable)
  - Heartbeat timeout: 90 seconds (3 missed heartbeats → connection closed)
  - Client reconnection: exponential backoff (1s, 2s, 4s, 8s, 16s, max 60s)
  - State recovery: on reconnection, server replays last component state to restore UI
  - Connection ID persistence: reconnecting client provides previous connection ID to resume session

### Component Builder

**Visual component builder in the React Flow canvas**

- **Drag-and-drop configuration**: drag components from palette onto canvas
  ```typescript
  interface ComponentBuilderState {
    components: PlacedComponent[];             // Components on canvas
    bindings: DataBinding[];                   // Data bindings to agent state
    conditionals: ConditionalRule[];           // Conditional rendering rules
    layout: LayoutConfig;                      // Component arrangement
    preview: boolean;                          // Live preview mode
  }
  
  interface PlacedComponent {
    id: string;
    type: string;                              // Component type from registry
    position: { x: number; y: number };
    size: { width: number; height: number };
    props: Record<string, unknown>;            // Configured props
    bindings: Record<string, string>;          // Prop → agent state variable mapping
    conditionalRender: ConditionalRule | null; // When to show/hide
    permissions: ComponentPermission;          // RBAC configuration
  }
  ```

- **Data binding to agent state variables**:
  ```typescript
  interface DataBinding {
    component_id: string;
    prop_name: string;                         // Which prop to bind
    source_type: "agent_state" | "execution_output" | "api_call" | "static";
    source_path: string;                       // JSON path to data source
    transform?: string;                        // Optional data transform expression
    refresh_trigger: "on_change" | "interval" | "manual";
    refresh_interval_ms?: number;              // For interval-based refresh
  }
  ```

- **Conditional rendering rules**:
  ```typescript
  interface ConditionalRule {
    condition_type: "permission" | "state" | "expression";
    expression: string;                        // e.g., "user.role === 'admin'"
    render_mode: "show" | "hide" | "disable" | "replace";
    replacement_component?: string;            // Component to show instead
  }
  ```

- **Layout modes**: free-form canvas, grid layout, stack (vertical/horizontal), responsive flow
- **Preview mode**: live preview of component rendering with mock data
- **Export**: component configurations exported as JSON, stored as part of agent graph definition
- **Component templates**: pre-built component layouts (dashboard, form wizard, approval flow)

### Streaming Updates

**Components update in real-time as agent execution progresses**

- **Streaming patterns**:
  ```typescript
  // Pattern 1: Progressive data fill
  // Chart fills in as data is processed
  await componentWs.send({
    type: "update",
    component_id: chartId,
    data: { appendData: [{ x: timestamp, y: newValue }] }
  });
  
  // Pattern 2: Progress advancement
  // Progress bar advances as steps complete
  await componentWs.send({
    type: "update",
    component_id: progressId,
    data: { currentStep: 3, stepStatus: "completed", message: "Data validated" }
  });
  
  // Pattern 3: Table row population
  // Table rows populate as results come in
  await componentWs.send({
    type: "update",
    component_id: tableId,
    data: { appendRows: [{ id: "row-5", name: "New Entry", status: "active" }] }
  });
  
  // Pattern 4: Status transitions
  // Status badge updates as workflow progresses
  await componentWs.send({
    type: "update",
    component_id: statusId,
    data: { status: "in_progress", label: "Processing...", pulse: true }
  });
  ```

- **Update batching**: if multiple updates for the same component arrive within 16ms (one frame), batch them into a single render update
- **Backpressure**: if client is slow to process updates, server buffers up to 100 messages then drops oldest
- **Optimistic updates**: for user actions (form submit, button click), update UI immediately and reconcile with server response
- **Update ordering**: updates applied in order using monotonically increasing sequence numbers
- **Partial updates**: only changed props sent over WebSocket (delta updates, not full state)

### Core Data Models

```python
class ComponentDefinition(SQLModel, table=True):
    """Registry of available component types."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    component_type: str = Field(unique=True, index=True)  # "data_table", "chart"
    display_name: str
    category: Literal["data_display", "input", "action", "layout", "media", "status"]
    version: str                                           # Semantic version
    props_schema: dict                                     # JSON Schema for props
    events_schema: dict                                    # JSON Schema for events
    default_props: dict                                    # Default prop values
    permissions_config: dict                               # Default RBAC rules
    icon: str                                              # Icon identifier
    documentation: str                                     # Usage docs (Markdown)
    source_type: Literal["builtin", "custom", "marketplace"]
    created_at: datetime
    updated_at: datetime | None

class ComponentInstance(SQLModel, table=True):
    """A rendered instance of a component in an execution."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    component_type: str = Field(foreign_key="componentdefinition.component_type")
    execution_id: uuid.UUID = Field(foreign_key="executions.id", index=True)
    agent_id: uuid.UUID = Field(foreign_key="agents.id")
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    session_id: str                                        # WebSocket session
    props: dict                                            # Current props
    state: dict                                            # Component internal state
    bindings: dict                                         # Data bindings
    permissions: dict                                      # RBAC config for this instance
    status: Literal["rendering", "active", "destroyed", "error"]
    rendered_at: datetime
    last_updated_at: datetime | None
    destroyed_at: datetime | None

class ComponentEvent(SQLModel, table=True):
    """Events emitted by component instances (user interactions)."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    component_id: uuid.UUID = Field(foreign_key="componentinstance.id", index=True)
    execution_id: uuid.UUID = Field(foreign_key="executions.id")
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    user_id: uuid.UUID = Field(foreign_key="users.id")
    event_type: str                                        # "submit", "approve", "click", "change"
    event_data: dict                                       # Event payload
    timestamp: datetime
    processed: bool = False                                # Whether agent has processed this

class ComponentTemplate(SQLModel, table=True):
    """Pre-built component layout templates."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str
    description: str
    category: str                                          # "dashboard", "form_wizard", "approval_flow"
    components: list[dict]                                 # Component configurations
    layout: dict                                           # Layout configuration
    bindings: list[dict]                                   # Data binding templates
    tenant_id: uuid.UUID | None                            # Null = global template
    created_by: uuid.UUID = Field(foreign_key="users.id")
    created_at: datetime
    updated_at: datetime | None

class ComponentSession(SQLModel, table=True):
    """Tracks active component sessions per user."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    session_id: str = Field(unique=True, index=True)
    user_id: uuid.UUID = Field(foreign_key="users.id")
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    websocket_connection_id: str
    active_components: list[str]                           # Component instance IDs
    permissions_snapshot: list[str]                         # Cached permissions
    created_at: datetime
    last_activity_at: datetime
    expires_at: datetime
    status: Literal["active", "idle", "disconnected", "expired"]
```

### Infrastructure

**Frontend component architecture**
```typescript
// Main component renderer — dynamically renders any registered component
const ComponentRenderer: React.FC<{
  componentType: string;
  componentId: string;
  props: Record<string, unknown>;
  sessionId: string;
}> = ({ componentType, componentId, props, sessionId }) => {
  const registry = useComponentRegistry();
  const Component = registry.get(componentType);
  const { permissions } = useComponentSession(sessionId);
  
  if (!Component) return <UnknownComponent type={componentType} />;
  
  // Apply RBAC filtering
  const filteredProps = applyPermissions(props, Component.permissions, permissions);
  
  return (
    <ComponentSandbox componentId={componentId}>
      <ErrorBoundary fallback={<ComponentError />}>
        <Component {...filteredProps} />
      </ErrorBoundary>
    </ComponentSandbox>
  );
};
```

**Backend execution integration**
```python
# LangGraph node for rendering components during agent execution
class RenderComponentNode:
    """LangGraph node that renders an interactive component."""
    
    async def execute(self, state: AgentState, config: NodeConfig) -> AgentState:
        component_type = config["component_type"]
        props = self.resolve_bindings(config["bindings"], state)
        
        # Render component via WebSocket
        component_id = await self.component_service.render(
            session_id=state["session_id"],
            component_type=component_type,
            props=props,
            permissions=config["permissions"]
        )
        
        # Wait for user interaction (if blocking)
        if config.get("wait_for_input", False):
            user_input = await self.component_service.wait_for_event(
                component_id=component_id,
                event_types=config["expected_events"],
                timeout=config.get("timeout", 300)
            )
            state["component_input"] = user_input
        
        state["active_components"].append(component_id)
        return state
```

## Output Structure

```
frontend/src/components/mcp/
├── ComponentRenderer.tsx              # Dynamic component renderer
├── ComponentSandbox.tsx               # Iframe sandboxing wrapper
├── SecureBridge.ts                    # postMessage communication bridge
├── ComponentRegistry.ts              # Component registration + discovery
├── PermissionFilter.tsx               # RBAC-aware prop filtering
├── StreamingUpdater.ts                # Real-time update handler
├── components/                        # Component library
│   ├── data-display/
│   │   ├── DataTable.tsx              # Sortable, filterable table
│   │   ├── Chart.tsx                  # Recharts wrapper (line, bar, pie, scatter)
│   │   ├── MetricCard.tsx             # Single metric with trend
│   │   ├── MapView.tsx                # Geographic map
│   │   ├── Timeline.tsx               # Event timeline
│   │   └── Calendar.tsx               # Calendar with events
│   ├── input/
│   │   ├── DynamicForm.tsx            # Dynamic form builder
│   │   ├── FileUploader.tsx           # Drag-and-drop upload
│   │   └── CodeEditor.tsx             # Monaco editor wrapper
│   ├── action/
│   │   ├── ApprovalPanel.tsx          # Approve/reject with comments
│   │   ├── ButtonGroup.tsx            # Grouped action buttons
│   │   └── ConfirmDialog.tsx          # Confirmation modal
│   ├── layout/
│   │   ├── Accordion.tsx              # Collapsible sections
│   │   ├── Tabs.tsx                   # Tabbed panels
│   │   ├── Stepper.tsx                # Multi-step wizard
│   │   └── KanbanBoard.tsx            # Drag-and-drop kanban
│   ├── media/
│   │   ├── ImageGallery.tsx           # Image carousel
│   │   └── MarkdownRenderer.tsx       # Rendered Markdown
│   └── status/
│       ├── ProgressTracker.tsx        # Multi-step progress
│       └── StatusBadge.tsx            # Status indicator
├── builder/                           # Visual component builder
│   ├── ComponentPalette.tsx           # Drag source for components
│   ├── BuilderCanvas.tsx              # Drop target canvas
│   ├── PropEditor.tsx                 # Property configuration panel
│   ├── BindingEditor.tsx              # Data binding configuration
│   ├── ConditionalEditor.tsx          # Conditional rendering rules
│   ├── PreviewPanel.tsx               # Live preview
│   └── TemplateManager.tsx            # Component templates
├── protocol/                          # WebSocket protocol
│   ├── WebSocketClient.ts            # Client-side WS handler
│   ├── MessageRouter.ts              # Message type routing
│   ├── Heartbeat.ts                  # Keepalive management
│   ├── Reconnection.ts              # Reconnection with backoff
│   └── StateRecovery.ts             # State replay on reconnect
├── hooks/
│   ├── useComponentSession.ts         # Session management hook
│   ├── useComponentRegistry.ts        # Registry access hook
│   ├── useStreamingUpdate.ts          # Real-time update hook
│   ├── useComponentPermissions.ts     # Permission checking hook
│   └── useComponentBuilder.ts         # Builder state hook
├── types/
│   ├── components.ts                  # Component type definitions
│   ├── protocol.ts                    # WebSocket protocol types
│   ├── permissions.ts                 # Permission types
│   └── builder.ts                     # Builder types
└── utils/
    ├── sanitizer.ts                   # DOMPurify wrapper
    ├── validator.ts                   # Prop validation
    └── transforms.ts                  # Data transformation helpers

backend/app/services/mcp/
├── __init__.py
├── component_service.py               # Component lifecycle management
├── session_service.py                 # Component session management
├── permission_service.py             # Component RBAC evaluation
├── streaming_service.py              # Streaming update dispatch
└── registry_service.py               # Component registry (backend)

backend/app/routers/mcp.py             # Component API endpoints
backend/app/websocket/components.py    # WebSocket handler for components

backend/app/langgraph/nodes/
├── render_component.py                # LangGraph node: render component
├── wait_for_input.py                  # LangGraph node: wait for user input
└── update_component.py                # LangGraph node: update component

tests/test_mcp/
├── conftest.py
├── test_component_renderer.py
├── test_component_registry.py
├── test_secure_sandbox.py
├── test_websocket_protocol.py
├── test_permissions.py
├── test_streaming_updates.py
├── test_component_builder.py
├── test_session_management.py
└── test_xss_prevention.py
```

## API Endpoints (Complete)

```
# Component Registry
GET    /api/v1/components/registry                      # List all registered components
GET    /api/v1/components/registry/{type}                # Get component definition
POST   /api/v1/components/registry                       # Register custom component
PUT    /api/v1/components/registry/{type}                # Update component definition
DELETE /api/v1/components/registry/{type}                # Unregister component

# Component Instances
GET    /api/v1/components/instances                      # List active component instances
GET    /api/v1/components/instances/{id}                 # Get instance details
POST   /api/v1/components/instances/{id}/destroy         # Destroy component instance
GET    /api/v1/components/instances/{id}/events           # List events for instance

# Component Sessions
GET    /api/v1/components/sessions                       # List active sessions
GET    /api/v1/components/sessions/{id}                  # Get session details
DELETE /api/v1/components/sessions/{id}                  # Terminate session

# Component Builder
GET    /api/v1/components/templates                      # List component templates
POST   /api/v1/components/templates                      # Create template
GET    /api/v1/components/templates/{id}                 # Get template
PUT    /api/v1/components/templates/{id}                 # Update template
DELETE /api/v1/components/templates/{id}                 # Delete template
POST   /api/v1/components/templates/{id}/preview         # Preview template with mock data

# Component Rendering (called by agents during execution)
POST   /api/v1/components/render                         # Render a component in user's session
POST   /api/v1/components/render/{id}/update              # Update component props
POST   /api/v1/components/render/{id}/destroy             # Remove component from UI
POST   /api/v1/components/render/{id}/wait                # Wait for user interaction (blocking)

# Component Events (user interactions)
POST   /api/v1/components/events                         # Submit component event (from client)
GET    /api/v1/components/events/{execution_id}           # List events for an execution

# WebSocket
WS     /ws/components                                    # WebSocket endpoint for component communication

# Health
GET    /api/v1/components/health                         # Component system health
GET    /api/v1/components/metrics                        # Active sessions, components, events/min
```

## Verify Commands

```bash
# MCP service importable
cd ~/Scripts/Archon && python -c "from backend.app.services.mcp.component_service import ComponentService; print('OK')"

# Session service importable
cd ~/Scripts/Archon && python -c "from backend.app.services.mcp.session_service import ComponentSessionService; print('OK')"

# Permission service importable
cd ~/Scripts/Archon && python -c "from backend.app.services.mcp.permission_service import ComponentPermissionService; print('OK')"

# WebSocket handler importable
cd ~/Scripts/Archon && python -c "from backend.app.websocket.components import ComponentWebSocketHandler; print('OK')"

# LangGraph nodes importable
cd ~/Scripts/Archon && python -c "from backend.app.langgraph.nodes.render_component import RenderComponentNode; from backend.app.langgraph.nodes.wait_for_input import WaitForInputNode; print('LangGraph OK')"

# Data models importable
cd ~/Scripts/Archon && python -c "from backend.app.services.mcp.component_service import ComponentDefinition, ComponentInstance, ComponentEvent, ComponentTemplate, ComponentSession; print('Models OK')"

# Frontend components build
cd ~/Scripts/Archon/frontend && npx tsc --noEmit

# Frontend component registry
cd ~/Scripts/Archon/frontend && npx tsc --noEmit src/components/mcp/ComponentRegistry.ts

# Tests pass
cd ~/Scripts/Archon && python -m pytest tests/test_mcp/ --tb=short -q

# Frontend tests pass
cd ~/Scripts/Archon/frontend && npm test -- --watchAll=false --passWithNoTests

# No XSS vulnerabilities (check for dangerouslySetInnerHTML usage)
cd ~/Scripts/Archon && ! grep -rn 'dangerouslySetInnerHTML' --include='*.tsx' --include='*.ts' frontend/src/components/mcp/ || echo 'WARNING: dangerouslySetInnerHTML found — review for XSS'

# No inline event handlers (CSP violation)
cd ~/Scripts/Archon && ! grep -rn 'onclick\|onload\|onerror' --include='*.html' frontend/src/components/mcp/ || echo 'WARNING: inline handlers found'
```

## Learnings Protocol

Before starting, read `.sdd/learnings/*.md` for known pitfalls from previous sessions.
After completing work, report any pitfalls or patterns discovered so the orchestrator can capture them.

## Acceptance Criteria

- [ ] Agent can embed a form component in response; user submits; agent receives submitted data via WebSocket event
- [ ] Charts (line, bar, pie, scatter) render correctly with dynamic data from agent execution
- [ ] DataTable supports sorting, filtering, and export with 1000+ rows, showing only columns user has permission for
- [ ] ApprovalPanel shows approve/reject for approvers, read-only view for non-approvers, hidden for unauthorized
- [ ] Component updates via WebSocket render without full page reload (streaming updates work)
- [ ] Chart fills in progressively as agent processes data (streaming pattern verified)
- [ ] Progress bar advances in real-time as agent execution steps complete
- [ ] Session-bound auth: components make API calls as the authenticated user, not with service credentials
- [ ] Component-level RBAC: DataTable hides restricted columns, admin actions hidden from viewers
- [ ] Sandboxed iframe rendering: component cannot access parent window DOM, cookies, or storage
- [ ] postMessage communication validates origin — messages from unauthorized origins are blocked
- [ ] No XSS vulnerabilities: DOMPurify sanitization + CSP prevents script injection
- [ ] WebSocket heartbeat detects disconnection within 90 seconds and client reconnects with state recovery
- [ ] Visual component builder: drag component from palette, configure props, bind to agent state, preview
- [ ] Component templates: save/load pre-built component layouts (dashboard, form wizard, approval flow)
- [ ] Custom components can be registered and used within 10 minutes via the component registry API
- [ ] All 20 pre-built components render correctly with their documented prop schemas
- [ ] All data models (ComponentDefinition, ComponentInstance, ComponentEvent, ComponentTemplate, ComponentSession) implemented
- [ ] All API endpoints return correct responses with proper auth, tenant isolation, and RBAC
- [ ] LangGraph integration: RenderComponentNode and WaitForInputNode work within agent execution flows
- [ ] All tests pass with >85% coverage across renderer, protocol, permissions, and builder
