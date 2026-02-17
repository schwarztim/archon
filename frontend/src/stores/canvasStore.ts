import { create } from "zustand";
import {
  applyNodeChanges,
  applyEdgeChanges,
  addEdge,
  type Connection,
  type NodeChange,
  type EdgeChange,
} from "@xyflow/react";
import type { AppNode, AppEdge, CustomNodeData } from "@/types";

interface CanvasState {
  /** All nodes on the canvas */
  nodes: AppNode[];
  /** All edges on the canvas */
  edges: AppEdge[];
  /** Currently selected node id */
  selectedNodeId: string | null;
  /** Undo history stack */
  history: Array<{ nodes: AppNode[]; edges: AppEdge[] }>;
  /** Redo stack */
  future: Array<{ nodes: AppNode[]; edges: AppEdge[] }>;
  /** Whether the canvas has unsaved changes */
  isDirty: boolean;
  /** Whether to show validation errors on the canvas */
  showValidation: boolean;
  /** Last auto-save timestamp */
  lastAutoSave: number | null;

  // Actions
  onNodesChange: (changes: NodeChange<AppNode>[]) => void;
  onEdgesChange: (changes: EdgeChange[]) => void;
  onConnect: (connection: Connection) => void;
  addNode: (node: AppNode) => void;
  updateNodeData: (nodeId: string, data: Partial<CustomNodeData>) => void;
  deleteNode: (nodeId: string) => void;
  selectNode: (nodeId: string | null) => void;
  setNodes: (nodes: AppNode[]) => void;
  setEdges: (edges: AppEdge[]) => void;
  undo: () => void;
  redo: () => void;
  clearCanvas: () => void;
  markClean: () => void;
  setShowValidation: (show: boolean) => void;
  setLastAutoSave: (ts: number) => void;
  /** Load a graph definition (nodes + edges) from API response */
  loadGraph: (nodes: AppNode[], edges: AppEdge[]) => void;
  /** Serialize the current graph for saving */
  serializeGraph: () => { nodes: AppNode[]; edges: AppEdge[] };
}

function pushHistory(state: CanvasState): Partial<CanvasState> {
  return {
    history: [
      ...state.history.slice(-49),
      { nodes: state.nodes, edges: state.edges },
    ],
    future: [],
    isDirty: true,
  };
}

export const useCanvasStore = create<CanvasState>((set, get) => ({
  nodes: [],
  edges: [],
  selectedNodeId: null,
  history: [],
  future: [],
  isDirty: false,
  showValidation: false,
  lastAutoSave: null,

  onNodesChange: (changes) => {
    set((state) => ({
      nodes: applyNodeChanges(changes, state.nodes),
      isDirty: true,
    }));
  },

  onEdgesChange: (changes) => {
    set((state) => ({
      edges: applyEdgeChanges(changes, state.edges),
      isDirty: true,
    }));
  },

  onConnect: (connection) => {
    const state = get();
    set({
      ...pushHistory(state),
      edges: addEdge(
        { ...connection, type: "smoothstep", animated: true },
        state.edges,
      ),
    });
  },

  addNode: (node) => {
    const state = get();
    set({
      ...pushHistory(state),
      nodes: [...state.nodes, node],
    });
  },

  updateNodeData: (nodeId, data) => {
    const state = get();
    set({
      ...pushHistory(state),
      nodes: state.nodes.map((n) =>
        n.id === nodeId
          ? { ...n, data: { ...n.data, ...data } as CustomNodeData }
          : n,
      ),
    });
  },

  deleteNode: (nodeId) => {
    const state = get();
    set({
      ...pushHistory(state),
      nodes: state.nodes.filter((n) => n.id !== nodeId),
      edges: state.edges.filter(
        (e) => e.source !== nodeId && e.target !== nodeId,
      ),
      selectedNodeId:
        state.selectedNodeId === nodeId ? null : state.selectedNodeId,
    });
  },

  selectNode: (nodeId) => {
    set({ selectedNodeId: nodeId });
  },

  setNodes: (nodes) => {
    set({ nodes });
  },

  setEdges: (edges) => {
    set({ edges });
  },

  undo: () => {
    const state = get();
    const prev = state.history[state.history.length - 1];
    if (!prev) return;
    set({
      nodes: prev.nodes,
      edges: prev.edges,
      history: state.history.slice(0, -1),
      future: [{ nodes: state.nodes, edges: state.edges }, ...state.future],
      isDirty: true,
    });
  },

  redo: () => {
    const state = get();
    const next = state.future[0];
    if (!next) return;
    set({
      nodes: next.nodes,
      edges: next.edges,
      history: [
        ...state.history,
        { nodes: state.nodes, edges: state.edges },
      ],
      future: state.future.slice(1),
      isDirty: true,
    });
  },

  clearCanvas: () => {
    const state = get();
    set({
      ...pushHistory(state),
      nodes: [],
      edges: [],
      selectedNodeId: null,
    });
  },

  markClean: () => {
    set({ isDirty: false });
  },

  setShowValidation: (show) => {
    set({ showValidation: show });
  },

  setLastAutoSave: (ts) => {
    set({ lastAutoSave: ts });
  },

  loadGraph: (nodes, edges) => {
    set({
      nodes,
      edges,
      selectedNodeId: null,
      history: [],
      future: [],
      isDirty: false,
    });
  },

  serializeGraph: () => {
    const { nodes, edges } = get();
    return { nodes, edges };
  },
}));
