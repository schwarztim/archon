import { useState, useCallback, useMemo } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  addEdge,
  useNodesState,
  useEdgesState,
  type Connection,
  type NodeTypes,
  type Node,
  type Edge,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  Bot, Split, GitFork, Repeat, Workflow, Combine, Clock,
  Plus, Trash2, Undo2, Redo2, ArrowRight, X, CheckCircle2,
  AlertCircle,
} from "lucide-react";

import { AgentCallNode } from "./nodes/AgentCallNode";
import { ConditionNode } from "./nodes/ConditionNode";
import { ParallelNode } from "./nodes/ParallelNode";
import { LoopNode } from "./nodes/LoopNode";
import { SubWorkflowNode } from "./nodes/SubWorkflowNode";
import { MergeNode } from "./nodes/MergeNode";
import { DelayNode } from "./nodes/DelayNode";

// ─── Node type registry ──────────────────────────────────────────────

const WORKFLOW_NODE_TYPES = [
  { type: "agentCall", label: "Agent Call", icon: Bot, color: "bg-blue-500" },
  { type: "condition", label: "Condition", icon: Split, color: "bg-amber-500" },
  { type: "parallel", label: "Parallel", icon: GitFork, color: "bg-cyan-500" },
  { type: "loop", label: "Loop", icon: Repeat, color: "bg-green-500" },
  { type: "subWorkflow", label: "Sub-Workflow", icon: Workflow, color: "bg-purple-500" },
  { type: "merge", label: "Merge", icon: Combine, color: "bg-indigo-500" },
  { type: "delay", label: "Delay", icon: Clock, color: "bg-orange-500" },
] as const;

type WfNodeType = (typeof WORKFLOW_NODE_TYPES)[number]["type"];

const workflowNodeTypes: NodeTypes = {
  agentCall: AgentCallNode,
  condition: ConditionNode,
  parallel: ParallelNode,
  loop: LoopNode,
  subWorkflow: SubWorkflowNode,
  merge: MergeNode,
  delay: DelayNode,
};

interface WfNodeData extends Record<string, unknown> {
  nodeType: WfNodeType;
  label: string;
  // AgentCall fields
  agent_id: string;
  inputMapping: { source: string; target: string }[];
  timeout: number;
  retryPolicy: "none" | "1" | "3";
  onFailure: "stop" | "skip" | "continue";
  // Condition fields
  condField: string;
  condOperator: string;
  condValue: string;
  condLogic: "AND" | "OR";
  // Parallel fields
  branches: number;
  executionMode: "all" | "any" | "n_of_m";
  requiredCount: number;
  // Loop fields
  loopType: "forEach" | "while" | "fixedCount";
  maxIterations: number;
  loopCondition: string;
  // SubWorkflow fields
  workflowId: string;
  async: boolean;
  // Merge fields
  strategy: "all" | "any" | "n";
  // Delay fields
  delayType: "duration" | "datetime";
  durationMs: number;
  targetDatetime: string;
}

function defaultWfNodeData(nodeType: WfNodeType): WfNodeData {
  return {
    nodeType,
    label: WORKFLOW_NODE_TYPES.find((t) => t.type === nodeType)?.label ?? nodeType,
    agent_id: "",
    inputMapping: [],
    timeout: 30,
    retryPolicy: "none",
    onFailure: "stop",
    condField: "",
    condOperator: "equals",
    condValue: "",
    condLogic: "AND",
    branches: 2,
    executionMode: "all",
    requiredCount: 1,
    loopType: "forEach",
    maxIterations: 10,
    loopCondition: "",
    workflowId: "",
    async: false,
    strategy: "all",
    delayType: "duration",
    durationMs: 5000,
    targetDatetime: "",
  };
}

// ─── Agent type for dropdowns ────────────────────────────────────────

interface AgentOption {
  id: string;
  name: string;
}

// ─── Undo/Redo history ──────────────────────────────────────────────

interface HistoryState {
  nodes: Node[];
  edges: Edge[];
}

// ─── Validation ─────────────────────────────────────────────────────

interface ValidationIssue {
  nodeId: string;
  message: string;
  severity: "error" | "warning";
}

function validateGraph(nodes: Node[], edges: Edge[]): ValidationIssue[] {
  const issues: ValidationIssue[] = [];
  for (const node of nodes) {
    const d = node.data as unknown as WfNodeData;
    if (d.nodeType === "agentCall" && !d.agent_id) {
      issues.push({ nodeId: node.id, message: "Agent not selected", severity: "warning" });
    }
    // Check for orphan nodes (no connections)
    const hasInput = edges.some((e) => e.target === node.id);
    const hasOutput = edges.some((e) => e.source === node.id);
    if (!hasInput && !hasOutput && nodes.length > 1) {
      issues.push({ nodeId: node.id, message: "Disconnected node", severity: "warning" });
    }
  }
  return issues;
}

// ─── Component ───────────────────────────────────────────────────────

interface WorkflowCanvasProps {
  initialNodes?: Node[];
  initialEdges?: Edge[];
  agents: AgentOption[];
  onNodesChange?: (nodes: Node[]) => void;
  onEdgesChange?: (edges: Edge[]) => void;
  height?: string;
  readOnly?: boolean;
}

export function WorkflowCanvas({
  initialNodes = [],
  initialEdges = [],
  agents,
  onNodesChange: onNodesChangeExternal,
  onEdgesChange: onEdgesChangeExternal,
  height = "400px",
  readOnly = false,
}: WorkflowCanvasProps) {
  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);

  // Undo/Redo
  const [history, setHistory] = useState<HistoryState[]>([]);
  const [historyIndex, setHistoryIndex] = useState(-1);

  const memoNodeTypes = useMemo(() => workflowNodeTypes, []);
  const validationIssues = useMemo(() => validateGraph(nodes, edges), [nodes, edges]);

  const saveHistory = useCallback(() => {
    const state: HistoryState = {
      nodes: JSON.parse(JSON.stringify(nodes)),
      edges: JSON.parse(JSON.stringify(edges)),
    };
    setHistory((h) => [...h.slice(0, historyIndex + 1), state]);
    setHistoryIndex((i) => i + 1);
  }, [nodes, edges, historyIndex]);

  const undo = useCallback(() => {
    if (historyIndex < 0) return;
    const prev = history[historyIndex];
    if (prev) {
      setNodes(prev.nodes);
      setEdges(prev.edges);
      setHistoryIndex((i) => i - 1);
    }
  }, [history, historyIndex, setNodes, setEdges]);

  const redo = useCallback(() => {
    if (historyIndex >= history.length - 1) return;
    const next = history[historyIndex + 1];
    if (next) {
      setNodes(next.nodes);
      setEdges(next.edges);
      setHistoryIndex((i) => i + 1);
    }
  }, [history, historyIndex, setNodes, setEdges]);

  const onConnect = useCallback(
    (connection: Connection) => {
      saveHistory();
      setEdges((eds) => addEdge(connection, eds));
    },
    [setEdges, saveHistory],
  );

  function addGraphNode(type: WfNodeType) {
    saveHistory();
    const id = crypto.randomUUID();
    const newNode: Node = {
      id,
      type,
      position: { x: 100 + nodes.length * 200, y: 100 + (nodes.length % 3) * 80 },
      data: defaultWfNodeData(type) as unknown as Record<string, unknown>,
    };
    setNodes((nds) => [...nds, newNode]);
    setSelectedNodeId(id);
  }

  function updateSelectedNodeData(patch: Partial<WfNodeData>) {
    if (!selectedNodeId) return;
    setNodes((nds) =>
      nds.map((n) =>
        n.id === selectedNodeId
          ? { ...n, data: { ...n.data, ...patch } as unknown as Record<string, unknown> }
          : n,
      ),
    );
  }

  function removeSelectedNode() {
    if (!selectedNodeId) return;
    saveHistory();
    setNodes((nds) => nds.filter((n) => n.id !== selectedNodeId));
    setEdges((eds) => eds.filter((e) => e.source !== selectedNodeId && e.target !== selectedNodeId));
    setSelectedNodeId(null);
  }

  // Notify parent of changes
  useMemo(() => {
    onNodesChangeExternal?.(nodes);
  }, [nodes]);
  useMemo(() => {
    onEdgesChangeExternal?.(edges);
  }, [edges]);

  const selectedNode = nodes.find((n) => n.id === selectedNodeId);
  const selectedNodeData = selectedNode?.data as unknown as WfNodeData | undefined;
  const nodeIssues = selectedNodeId ? validationIssues.filter((i) => i.nodeId === selectedNodeId) : [];

  return (
    <div>
      {/* Toolbar */}
      {!readOnly && (
        <div className="mb-2 flex items-center justify-between">
          {/* Node palette */}
          <div className="flex flex-wrap gap-1">
            {WORKFLOW_NODE_TYPES.map((nt) => {
              const Icon = nt.icon;
              return (
                <button
                  key={nt.type}
                  type="button"
                  onClick={() => addGraphNode(nt.type)}
                  className="flex items-center gap-1.5 rounded border border-[#2a2d37] px-2 py-1 text-xs text-gray-400 hover:bg-white/5 hover:text-white"
                >
                  <Icon size={12} />
                  {nt.label}
                </button>
              );
            })}
          </div>
          {/* Undo/Redo + Validation */}
          <div className="flex items-center gap-2">
            {validationIssues.length > 0 && (
              <span className="flex items-center gap-1 text-[10px] text-amber-400">
                <AlertCircle size={10} />
                {validationIssues.length} issue{validationIssues.length !== 1 ? "s" : ""}
              </span>
            )}
            {validationIssues.length === 0 && nodes.length > 0 && (
              <span className="flex items-center gap-1 text-[10px] text-green-400">
                <CheckCircle2 size={10} />
                Valid
              </span>
            )}
            <button
              type="button"
              onClick={undo}
              disabled={historyIndex < 0}
              className="rounded p-1 text-gray-500 hover:bg-white/5 hover:text-white disabled:opacity-30"
              title="Undo"
            >
              <Undo2 size={14} />
            </button>
            <button
              type="button"
              onClick={redo}
              disabled={historyIndex >= history.length - 1}
              className="rounded p-1 text-gray-500 hover:bg-white/5 hover:text-white disabled:opacity-30"
              title="Redo"
            >
              <Redo2 size={14} />
            </button>
          </div>
        </div>
      )}

      {/* Canvas */}
      <div className="rounded-lg border border-[#2a2d37] bg-[#0d0f17] overflow-hidden" style={{ height }}>
        {nodes.length === 0 && !readOnly ? (
          <div className="flex h-full flex-col items-center justify-center">
            <Workflow size={32} className="mb-2 text-gray-700" />
            <p className="text-xs text-gray-600">
              Add nodes from the palette to build your workflow graph
            </p>
          </div>
        ) : (
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={readOnly ? undefined : onConnect}
            onNodeClick={(_e, node) => setSelectedNodeId(node.id)}
            onPaneClick={() => setSelectedNodeId(null)}
            nodeTypes={memoNodeTypes}
            fitView
            snapToGrid
            snapGrid={[16, 16]}
            deleteKeyCode={readOnly ? [] : ["Backspace", "Delete"]}
            nodesDraggable={!readOnly}
            nodesConnectable={!readOnly}
            className="bg-[#0d0f17]"
          >
            <Background gap={16} size={1} />
            <Controls className="!bg-[#1a1d27] !border-[#2a2d37] !shadow-md [&>button]:!bg-[#1a1d27] [&>button]:!border-[#2a2d37] [&>button]:!text-gray-400 [&>button:hover]:!bg-white/5" />
            <MiniMap
              className="!bg-[#1a1d27] !border-[#2a2d37]"
              nodeColor="#6b7280"
              maskColor="rgba(0, 0, 0, 0.6)"
            />
          </ReactFlow>
        )}
      </div>

      {/* Selected Node Config Panel */}
      {selectedNodeData && !readOnly && (
        <div className="mt-2 rounded-lg border border-[#2a2d37] bg-[#1a1d27] p-3">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-xs font-medium text-purple-400">
              Configure: {selectedNodeData.label}
            </span>
            <button
              type="button"
              onClick={removeSelectedNode}
              className="text-gray-500 hover:text-red-400"
              aria-label="Remove node"
            >
              <Trash2 size={12} />
            </button>
          </div>

          {/* Validation warnings */}
          {nodeIssues.length > 0 && (
            <div className="mb-2 space-y-1">
              {nodeIssues.map((issue, i) => (
                <p key={i} className="flex items-center gap-1 text-[10px] text-amber-400">
                  <AlertCircle size={10} /> {issue.message}
                </p>
              ))}
            </div>
          )}

          {/* Label */}
          <div className="mb-2">
            <label className="mb-0.5 block text-[10px] text-gray-500">Label</label>
            <input
              type="text"
              value={selectedNodeData.label}
              onChange={(e) => updateSelectedNodeData({ label: e.target.value })}
              className="w-full rounded border border-[#2a2d37] bg-[#12141e] px-2 py-1.5 text-xs text-white focus:border-purple-500 focus:outline-none"
            />
          </div>

          {/* Node-type-specific config */}
          <NodeConfigForm
            data={selectedNodeData}
            agents={agents}
            onChange={updateSelectedNodeData}
          />
        </div>
      )}
    </div>
  );
}

// ─── Node Config Form ────────────────────────────────────────────────

function NodeConfigForm({
  data,
  agents,
  onChange,
}: {
  data: WfNodeData;
  agents: AgentOption[];
  onChange: (patch: Partial<WfNodeData>) => void;
}) {
  return (
    <div className="space-y-2">
      {/* Agent selector — AgentCall and SubWorkflow */}
      {data.nodeType === "agentCall" && (
        <>
          <div>
            <label className="mb-0.5 block text-[10px] text-gray-500">Agent</label>
            <select
              value={data.agent_id}
              onChange={(e) => onChange({ agent_id: e.target.value })}
              className="w-full rounded border border-[#2a2d37] bg-[#12141e] px-2 py-1.5 text-xs text-white focus:border-purple-500 focus:outline-none"
            >
              <option value="">Select agent...</option>
              {agents.map((a) => (
                <option key={a.id} value={a.id}>{a.name}</option>
              ))}
            </select>
          </div>
          <InputMappingEditor
            mappings={data.inputMapping}
            onChange={(inputMapping) => onChange({ inputMapping })}
          />
          <div className="grid grid-cols-3 gap-2">
            <div>
              <label className="mb-0.5 block text-[10px] text-gray-500">Timeout (s)</label>
              <input
                type="number"
                min={0}
                value={data.timeout}
                onChange={(e) => onChange({ timeout: parseInt(e.target.value) || 0 })}
                className="w-full rounded border border-[#2a2d37] bg-[#12141e] px-2 py-1 text-xs text-white focus:border-purple-500 focus:outline-none"
              />
            </div>
            <div>
              <label className="mb-0.5 block text-[10px] text-gray-500">Retry</label>
              <select
                value={data.retryPolicy}
                onChange={(e) => onChange({ retryPolicy: e.target.value as WfNodeData["retryPolicy"] })}
                className="w-full rounded border border-[#2a2d37] bg-[#12141e] px-2 py-1 text-xs text-white focus:border-purple-500 focus:outline-none"
              >
                <option value="none">None</option>
                <option value="1">1 retry</option>
                <option value="3">3 retries</option>
              </select>
            </div>
            <div>
              <label className="mb-0.5 block text-[10px] text-gray-500">On Failure</label>
              <select
                value={data.onFailure}
                onChange={(e) => onChange({ onFailure: e.target.value as WfNodeData["onFailure"] })}
                className="w-full rounded border border-[#2a2d37] bg-[#12141e] px-2 py-1 text-xs text-white focus:border-purple-500 focus:outline-none"
              >
                <option value="stop">Stop</option>
                <option value="skip">Skip</option>
                <option value="continue">Continue</option>
              </select>
            </div>
          </div>
        </>
      )}

      {/* Condition config */}
      {data.nodeType === "condition" && (
        <div className="space-y-2">
          <div className="grid grid-cols-3 gap-2">
            <div>
              <label className="mb-0.5 block text-[10px] text-gray-500">Field</label>
              <input
                type="text"
                value={data.condField}
                onChange={(e) => onChange({ condField: e.target.value })}
                placeholder="status"
                className="w-full rounded border border-[#2a2d37] bg-[#12141e] px-2 py-1 text-xs text-white focus:border-purple-500 focus:outline-none"
              />
            </div>
            <div>
              <label className="mb-0.5 block text-[10px] text-gray-500">Operator</label>
              <select
                value={data.condOperator}
                onChange={(e) => onChange({ condOperator: e.target.value })}
                className="w-full rounded border border-[#2a2d37] bg-[#12141e] px-2 py-1 text-xs text-white focus:border-purple-500 focus:outline-none"
              >
                <option value="equals">equals</option>
                <option value="not_equals">not equals</option>
                <option value="contains">contains</option>
                <option value="gt">greater than</option>
                <option value="lt">less than</option>
              </select>
            </div>
            <div>
              <label className="mb-0.5 block text-[10px] text-gray-500">Value</label>
              <input
                type="text"
                value={data.condValue}
                onChange={(e) => onChange({ condValue: e.target.value })}
                placeholder="success"
                className="w-full rounded border border-[#2a2d37] bg-[#12141e] px-2 py-1 text-xs text-white focus:border-purple-500 focus:outline-none"
              />
            </div>
          </div>
          <div>
            <label className="mb-0.5 block text-[10px] text-gray-500">Grouping</label>
            <select
              value={data.condLogic}
              onChange={(e) => onChange({ condLogic: e.target.value as "AND" | "OR" })}
              className="w-32 rounded border border-[#2a2d37] bg-[#12141e] px-2 py-1 text-xs text-white focus:border-purple-500 focus:outline-none"
            >
              <option value="AND">AND</option>
              <option value="OR">OR</option>
            </select>
          </div>
        </div>
      )}

      {/* Parallel config */}
      {data.nodeType === "parallel" && (
        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="mb-0.5 block text-[10px] text-gray-500">Branches</label>
            <input
              type="number"
              min={2}
              max={10}
              value={data.branches}
              onChange={(e) => onChange({ branches: parseInt(e.target.value) || 2 })}
              className="w-full rounded border border-[#2a2d37] bg-[#12141e] px-2 py-1 text-xs text-white focus:border-purple-500 focus:outline-none"
            />
          </div>
          <div>
            <label className="mb-0.5 block text-[10px] text-gray-500">Execution Mode</label>
            <select
              value={data.executionMode}
              onChange={(e) => onChange({ executionMode: e.target.value as "all" | "any" | "n_of_m" })}
              className="w-full rounded border border-[#2a2d37] bg-[#12141e] px-2 py-1 text-xs text-white focus:border-purple-500 focus:outline-none"
            >
              <option value="all">Wait All</option>
              <option value="any">Wait Any</option>
              <option value="n_of_m">N of M</option>
            </select>
          </div>
          {data.executionMode === "n_of_m" && (
            <div>
              <label className="mb-0.5 block text-[10px] text-gray-500">Required count</label>
              <input
                type="number"
                min={1}
                max={data.branches}
                value={data.requiredCount}
                onChange={(e) => onChange({ requiredCount: parseInt(e.target.value) || 1 })}
                className="w-full rounded border border-[#2a2d37] bg-[#12141e] px-2 py-1 text-xs text-white focus:border-purple-500 focus:outline-none"
              />
            </div>
          )}
        </div>
      )}

      {/* Loop config */}
      {data.nodeType === "loop" && (
        <div className="space-y-2">
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="mb-0.5 block text-[10px] text-gray-500">Loop type</label>
              <select
                value={data.loopType}
                onChange={(e) => onChange({ loopType: e.target.value as "forEach" | "while" | "fixedCount" })}
                className="w-full rounded border border-[#2a2d37] bg-[#12141e] px-2 py-1 text-xs text-white focus:border-purple-500 focus:outline-none"
              >
                <option value="forEach">For Each</option>
                <option value="while">While</option>
                <option value="fixedCount">Fixed Count</option>
              </select>
            </div>
            <div>
              <label className="mb-0.5 block text-[10px] text-gray-500">Max iterations</label>
              <input
                type="number"
                min={1}
                value={data.maxIterations}
                onChange={(e) => onChange({ maxIterations: parseInt(e.target.value) || 1 })}
                className="w-full rounded border border-[#2a2d37] bg-[#12141e] px-2 py-1 text-xs text-white focus:border-purple-500 focus:outline-none"
              />
            </div>
          </div>
          {data.loopType === "while" && (
            <div>
              <label className="mb-0.5 block text-[10px] text-gray-500">Condition</label>
              <input
                type="text"
                value={data.loopCondition}
                onChange={(e) => onChange({ loopCondition: e.target.value })}
                placeholder="result.hasMore"
                className="w-full rounded border border-[#2a2d37] bg-[#12141e] px-2 py-1 text-xs text-white focus:border-purple-500 focus:outline-none"
              />
            </div>
          )}
        </div>
      )}

      {/* SubWorkflow config */}
      {data.nodeType === "subWorkflow" && (
        <div className="space-y-2">
          <div>
            <label className="mb-0.5 block text-[10px] text-gray-500">Workflow ID</label>
            <input
              type="text"
              value={data.workflowId}
              onChange={(e) => onChange({ workflowId: e.target.value })}
              placeholder="Enter workflow ID"
              className="w-full rounded border border-[#2a2d37] bg-[#12141e] px-2 py-1 text-xs text-white focus:border-purple-500 focus:outline-none"
            />
          </div>
          <InputMappingEditor
            mappings={data.inputMapping}
            onChange={(inputMapping) => onChange({ inputMapping })}
          />
          <label className="flex items-center gap-2 text-[10px] text-gray-500">
            <input
              type="checkbox"
              checked={data.async}
              onChange={(e) => onChange({ async: e.target.checked })}
              className="rounded"
            />
            Async execution
          </label>
        </div>
      )}

      {/* Merge config */}
      {data.nodeType === "merge" && (
        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="mb-0.5 block text-[10px] text-gray-500">Strategy</label>
            <select
              value={data.strategy}
              onChange={(e) => onChange({ strategy: e.target.value as "all" | "any" | "n" })}
              className="w-full rounded border border-[#2a2d37] bg-[#12141e] px-2 py-1 text-xs text-white focus:border-purple-500 focus:outline-none"
            >
              <option value="all">Wait All</option>
              <option value="any">Wait Any</option>
              <option value="n">Wait N</option>
            </select>
          </div>
          <div>
            <label className="mb-0.5 block text-[10px] text-gray-500">Timeout (s)</label>
            <input
              type="number"
              min={0}
              value={data.timeout}
              onChange={(e) => onChange({ timeout: parseInt(e.target.value) || 0 })}
              className="w-full rounded border border-[#2a2d37] bg-[#12141e] px-2 py-1 text-xs text-white focus:border-purple-500 focus:outline-none"
            />
          </div>
        </div>
      )}

      {/* Delay config */}
      {data.nodeType === "delay" && (
        <div className="space-y-2">
          <div>
            <label className="mb-0.5 block text-[10px] text-gray-500">Delay type</label>
            <select
              value={data.delayType}
              onChange={(e) => onChange({ delayType: e.target.value as "duration" | "datetime" })}
              className="w-full rounded border border-[#2a2d37] bg-[#12141e] px-2 py-1 text-xs text-white focus:border-purple-500 focus:outline-none"
            >
              <option value="duration">Duration</option>
              <option value="datetime">Specific datetime</option>
            </select>
          </div>
          {data.delayType === "duration" ? (
            <div>
              <label className="mb-0.5 block text-[10px] text-gray-500">Duration (seconds)</label>
              <input
                type="number"
                min={1}
                value={Math.round(data.durationMs / 1000)}
                onChange={(e) => onChange({ durationMs: (parseInt(e.target.value) || 1) * 1000 })}
                className="w-full rounded border border-[#2a2d37] bg-[#12141e] px-2 py-1 text-xs text-white focus:border-purple-500 focus:outline-none"
              />
            </div>
          ) : (
            <div>
              <label className="mb-0.5 block text-[10px] text-gray-500">Target datetime</label>
              <input
                type="datetime-local"
                value={data.targetDatetime}
                onChange={(e) => onChange({ targetDatetime: e.target.value })}
                className="w-full rounded border border-[#2a2d37] bg-[#12141e] px-2 py-1 text-xs text-white focus:border-purple-500 focus:outline-none"
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Input Mapping Editor ────────────────────────────────────────────

function InputMappingEditor({
  mappings,
  onChange,
}: {
  mappings: { source: string; target: string }[];
  onChange: (mappings: { source: string; target: string }[]) => void;
}) {
  return (
    <div>
      <label className="mb-0.5 block text-[10px] text-gray-500">Input Mapping</label>
      {mappings.map((m, i) => (
        <div key={i} className="mb-1 flex items-center gap-1">
          <input
            type="text"
            value={m.source}
            onChange={(e) => {
              const next = [...mappings];
              next[i] = { ...next[i]!, source: e.target.value };
              onChange(next);
            }}
            placeholder="source"
            className="w-full rounded border border-[#2a2d37] bg-[#12141e] px-2 py-1 text-[10px] text-white focus:border-purple-500 focus:outline-none"
          />
          <ArrowRight size={10} className="text-gray-600 shrink-0" />
          <input
            type="text"
            value={m.target}
            onChange={(e) => {
              const next = [...mappings];
              next[i] = { ...next[i]!, target: e.target.value };
              onChange(next);
            }}
            placeholder="target"
            className="w-full rounded border border-[#2a2d37] bg-[#12141e] px-2 py-1 text-[10px] text-white focus:border-purple-500 focus:outline-none"
          />
          <button
            type="button"
            onClick={() => onChange(mappings.filter((_, j) => j !== i))}
            className="text-gray-500 hover:text-red-400 shrink-0"
          >
            <X size={10} />
          </button>
        </div>
      ))}
      <button
        type="button"
        onClick={() => onChange([...mappings, { source: "", target: "" }])}
        className="flex items-center gap-1 text-[10px] text-gray-500 hover:text-purple-400"
      >
        <Plus size={10} /> Add mapping
      </button>
    </div>
  );
}

// Re-export defaults
export { WORKFLOW_NODE_TYPES, defaultWfNodeData };
export type { WfNodeType, WfNodeData, AgentOption };
