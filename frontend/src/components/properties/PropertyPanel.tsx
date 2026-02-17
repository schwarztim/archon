import { useCallback } from "react";
import { useCanvasStore } from "@/stores/canvasStore";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { Textarea } from "@/components/ui/Textarea";
import type { CustomNodeData } from "@/types";

// ─── Shared helpers ──────────────────────────────────────────────────

function SelectField({
  id,
  label,
  value,
  options,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (v: string) => void;
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      <select
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
      >
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    </div>
  );
}

function SliderField({
  id,
  label,
  value,
  min,
  max,
  step,
  onChange,
}: {
  id: string;
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (v: number) => void;
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>
        {label}: <span className="font-mono text-xs text-muted-foreground">{value}</span>
      </Label>
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        className="w-full accent-primary"
      />
    </div>
  );
}

function NumberField({
  id,
  label,
  value,
  onChange,
  min,
  max,
}: {
  id: string;
  label: string;
  value: number;
  onChange: (v: number) => void;
  min?: number;
  max?: number;
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        type="number"
        value={value}
        min={min}
        max={max}
        onChange={(e) => onChange(Number(e.target.value))}
      />
    </div>
  );
}

function TextField({
  id,
  label,
  value,
  onChange,
  multiline,
  placeholder,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  multiline?: boolean;
  placeholder?: string;
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      {multiline ? (
        <Textarea
          id={id}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          rows={3}
          placeholder={placeholder}
        />
      ) : (
        <Input
          id={id}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
        />
      )}
    </div>
  );
}

// ─── Type-specific config panels ─────────────────────────────────────

const MODEL_OPTIONS = [
  { value: "gpt-4o", label: "GPT-4o" },
  { value: "gpt-4o-mini", label: "GPT-4o Mini" },
  { value: "gpt-4-turbo", label: "GPT-4 Turbo" },
  { value: "claude-3.5-sonnet", label: "Claude 3.5 Sonnet" },
  { value: "claude-3-opus", label: "Claude 3 Opus" },
  { value: "claude-3-haiku", label: "Claude 3 Haiku" },
  { value: "gemini-2.0-flash", label: "Gemini 2.0 Flash" },
  { value: "gemini-1.5-pro", label: "Gemini 1.5 Pro" },
];

const EMBEDDING_MODEL_OPTIONS = [
  { value: "text-embedding-3-small", label: "text-embedding-3-small" },
  { value: "text-embedding-3-large", label: "text-embedding-3-large" },
  { value: "text-embedding-ada-002", label: "text-embedding-ada-002" },
];

const HTTP_METHOD_OPTIONS = [
  { value: "GET", label: "GET" },
  { value: "POST", label: "POST" },
  { value: "PUT", label: "PUT" },
  { value: "PATCH", label: "PATCH" },
  { value: "DELETE", label: "DELETE" },
];

const DB_TYPE_OPTIONS = [
  { value: "postgresql", label: "PostgreSQL" },
  { value: "mysql", label: "MySQL" },
  { value: "sqlite", label: "SQLite" },
  { value: "mongodb", label: "MongoDB" },
];

const DLP_ACTION_OPTIONS = [
  { value: "redact", label: "Redact" },
  { value: "mask", label: "Mask" },
  { value: "block", label: "Block" },
  { value: "log", label: "Log" },
  { value: "alert", label: "Alert" },
];

const LOOP_TYPE_OPTIONS = [
  { value: "forEach", label: "For Each" },
  { value: "while", label: "While" },
  { value: "repeat", label: "Repeat N" },
];

const MERGE_STRATEGY_OPTIONS = [
  { value: "waitAll", label: "Wait All" },
  { value: "waitAny", label: "Wait Any" },
  { value: "concat", label: "Concatenate" },
];

function LLMConfigPanel({
  config,
  onChange,
}: {
  config: Record<string, unknown>;
  onChange: (key: string, value: unknown) => void;
}) {
  return (
    <>
      <SelectField
        id="config-model"
        label="Model"
        value={String(config.model ?? "gpt-4o")}
        options={MODEL_OPTIONS}
        onChange={(v) => onChange("model", v)}
      />
      <SliderField
        id="config-temperature"
        label="Temperature"
        value={Number(config.temperature ?? 0.7)}
        min={0}
        max={2}
        step={0.1}
        onChange={(v) => onChange("temperature", v)}
      />
      <NumberField
        id="config-maxTokens"
        label="Max Tokens"
        value={Number(config.maxTokens ?? 2048)}
        onChange={(v) => onChange("maxTokens", v)}
        min={1}
        max={128000}
      />
      <TextField
        id="config-systemPrompt"
        label="System Prompt"
        value={String(config.systemPrompt ?? "")}
        onChange={(v) => onChange("systemPrompt", v)}
        multiline
        placeholder="You are a helpful assistant…"
      />
    </>
  );
}

function ToolConfigPanel({
  config,
  onChange,
}: {
  config: Record<string, unknown>;
  onChange: (key: string, value: unknown) => void;
}) {
  return (
    <>
      <TextField
        id="config-toolName"
        label="Tool Name"
        value={String(config.toolName ?? "")}
        onChange={(v) => onChange("toolName", v)}
        placeholder="e.g. search_web"
      />
      <TextField
        id="config-parameters"
        label="Parameters (JSON)"
        value={typeof config.parameters === "string" ? config.parameters : JSON.stringify(config.parameters ?? {}, null, 2)}
        onChange={(v) => onChange("parameters", v)}
        multiline
        placeholder='{"query": "…"}'
      />
    </>
  );
}

function ConditionConfigPanel({
  config,
  onChange,
}: {
  config: Record<string, unknown>;
  onChange: (key: string, value: unknown) => void;
}) {
  return (
    <TextField
      id="config-expression"
      label="Expression"
      value={String(config.expression ?? "")}
      onChange={(v) => onChange("expression", v)}
      multiline
      placeholder="input.value > 10"
    />
  );
}

function InputConfigPanel({
  config,
  onChange,
}: {
  config: Record<string, unknown>;
  onChange: (key: string, value: unknown) => void;
}) {
  return (
    <>
      <SelectField
        id="config-inputType"
        label="Input Type"
        value={String(config.inputType ?? "text")}
        options={[
          { value: "text", label: "Text" },
          { value: "json", label: "JSON" },
          { value: "file", label: "File" },
          { value: "image", label: "Image" },
        ]}
        onChange={(v) => onChange("inputType", v)}
      />
      <TextField
        id="config-defaultValue"
        label="Default Value"
        value={String(config.defaultValue ?? "")}
        onChange={(v) => onChange("defaultValue", v)}
      />
    </>
  );
}

function OutputConfigPanel({
  config,
  onChange,
}: {
  config: Record<string, unknown>;
  onChange: (key: string, value: unknown) => void;
}) {
  return (
    <SelectField
      id="config-outputFormat"
      label="Output Format"
      value={String(config.outputFormat ?? "text")}
      options={[
        { value: "text", label: "Text" },
        { value: "json", label: "JSON" },
        { value: "markdown", label: "Markdown" },
      ]}
      onChange={(v) => onChange("outputFormat", v)}
    />
  );
}

function WebhookConfigPanel({
  config,
  onChange,
}: {
  config: Record<string, unknown>;
  onChange: (key: string, value: unknown) => void;
}) {
  return (
    <>
      <SelectField
        id="config-method"
        label="HTTP Method"
        value={String(config.method ?? "POST")}
        options={HTTP_METHOD_OPTIONS}
        onChange={(v) => onChange("method", v)}
      />
      <TextField
        id="config-path"
        label="Webhook Path"
        value={String(config.path ?? "/webhook")}
        onChange={(v) => onChange("path", v)}
        placeholder="/webhook"
      />
    </>
  );
}

function ScheduleConfigPanel({
  config,
  onChange,
}: {
  config: Record<string, unknown>;
  onChange: (key: string, value: unknown) => void;
}) {
  return (
    <>
      <TextField
        id="config-cron"
        label="Cron Expression"
        value={String(config.cron ?? "0 * * * *")}
        onChange={(v) => onChange("cron", v)}
        placeholder="0 * * * *"
      />
      <TextField
        id="config-timezone"
        label="Timezone"
        value={String(config.timezone ?? "UTC")}
        onChange={(v) => onChange("timezone", v)}
        placeholder="UTC"
      />
    </>
  );
}

function StreamOutputConfigPanel({
  config,
  onChange,
}: {
  config: Record<string, unknown>;
  onChange: (key: string, value: unknown) => void;
}) {
  return (
    <>
      <SelectField
        id="config-format"
        label="Stream Format"
        value={String(config.format ?? "sse")}
        options={[
          { value: "sse", label: "SSE" },
          { value: "websocket", label: "WebSocket" },
          { value: "ndjson", label: "NDJSON" },
        ]}
        onChange={(v) => onChange("format", v)}
      />
      <NumberField
        id="config-chunkSize"
        label="Chunk Size"
        value={Number(config.chunkSize ?? 256)}
        onChange={(v) => onChange("chunkSize", v)}
        min={1}
      />
    </>
  );
}

function EmbeddingConfigPanel({
  config,
  onChange,
}: {
  config: Record<string, unknown>;
  onChange: (key: string, value: unknown) => void;
}) {
  return (
    <>
      <SelectField
        id="config-model"
        label="Embedding Model"
        value={String(config.model ?? "text-embedding-3-small")}
        options={EMBEDDING_MODEL_OPTIONS}
        onChange={(v) => onChange("model", v)}
      />
      <NumberField
        id="config-dimensions"
        label="Dimensions"
        value={Number(config.dimensions ?? 1536)}
        onChange={(v) => onChange("dimensions", v)}
        min={1}
      />
    </>
  );
}

function VisionConfigPanel({
  config,
  onChange,
}: {
  config: Record<string, unknown>;
  onChange: (key: string, value: unknown) => void;
}) {
  return (
    <>
      <SelectField
        id="config-model"
        label="Model"
        value={String(config.model ?? "gpt-4o")}
        options={MODEL_OPTIONS}
        onChange={(v) => onChange("model", v)}
      />
      <NumberField
        id="config-maxTokens"
        label="Max Tokens"
        value={Number(config.maxTokens ?? 2048)}
        onChange={(v) => onChange("maxTokens", v)}
        min={1}
      />
      <SelectField
        id="config-detail"
        label="Detail Level"
        value={String(config.detail ?? "auto")}
        options={[
          { value: "auto", label: "Auto" },
          { value: "low", label: "Low" },
          { value: "high", label: "High" },
        ]}
        onChange={(v) => onChange("detail", v)}
      />
    </>
  );
}

function StructuredOutputConfigPanel({
  config,
  onChange,
}: {
  config: Record<string, unknown>;
  onChange: (key: string, value: unknown) => void;
}) {
  return (
    <>
      <SelectField
        id="config-model"
        label="Model"
        value={String(config.model ?? "gpt-4o")}
        options={MODEL_OPTIONS}
        onChange={(v) => onChange("model", v)}
      />
      <SliderField
        id="config-temperature"
        label="Temperature"
        value={Number(config.temperature ?? 0.2)}
        min={0}
        max={2}
        step={0.1}
        onChange={(v) => onChange("temperature", v)}
      />
      <TextField
        id="config-schema"
        label="JSON Schema"
        value={String(config.schema ?? "{}")}
        onChange={(v) => onChange("schema", v)}
        multiline
        placeholder='{"type": "object", "properties": {…}}'
      />
    </>
  );
}

function MCPToolConfigPanel({
  config,
  onChange,
}: {
  config: Record<string, unknown>;
  onChange: (key: string, value: unknown) => void;
}) {
  return (
    <>
      <TextField
        id="config-serverName"
        label="MCP Server"
        value={String(config.serverName ?? "")}
        onChange={(v) => onChange("serverName", v)}
        placeholder="e.g. github-mcp-server"
      />
      <TextField
        id="config-toolName"
        label="Tool Name"
        value={String(config.toolName ?? "")}
        onChange={(v) => onChange("toolName", v)}
        placeholder="e.g. search_code"
      />
    </>
  );
}

function HTTPRequestConfigPanel({
  config,
  onChange,
}: {
  config: Record<string, unknown>;
  onChange: (key: string, value: unknown) => void;
}) {
  return (
    <>
      <SelectField
        id="config-method"
        label="Method"
        value={String(config.method ?? "GET")}
        options={HTTP_METHOD_OPTIONS}
        onChange={(v) => onChange("method", v)}
      />
      <TextField
        id="config-url"
        label="URL"
        value={String(config.url ?? "")}
        onChange={(v) => onChange("url", v)}
        placeholder="https://api.example.com/…"
      />
      <TextField
        id="config-headers"
        label="Headers (JSON)"
        value={String(config.headers ?? "{}")}
        onChange={(v) => onChange("headers", v)}
        multiline
        placeholder='{"Authorization": "Bearer …"}'
      />
      <TextField
        id="config-body"
        label="Body"
        value={String(config.body ?? "")}
        onChange={(v) => onChange("body", v)}
        multiline
      />
    </>
  );
}

function DatabaseQueryConfigPanel({
  config,
  onChange,
}: {
  config: Record<string, unknown>;
  onChange: (key: string, value: unknown) => void;
}) {
  return (
    <>
      <SelectField
        id="config-dbType"
        label="Database Type"
        value={String(config.dbType ?? "postgresql")}
        options={DB_TYPE_OPTIONS}
        onChange={(v) => onChange("dbType", v)}
      />
      <TextField
        id="config-connectionString"
        label="Connection String"
        value={String(config.connectionString ?? "")}
        onChange={(v) => onChange("connectionString", v)}
        placeholder="postgresql://user:pass@host/db"
      />
      <TextField
        id="config-query"
        label="Query"
        value={String(config.query ?? "")}
        onChange={(v) => onChange("query", v)}
        multiline
        placeholder="SELECT * FROM …"
      />
    </>
  );
}

function FunctionCallConfigPanel({
  config,
  onChange,
}: {
  config: Record<string, unknown>;
  onChange: (key: string, value: unknown) => void;
}) {
  return (
    <>
      <TextField
        id="config-functionName"
        label="Function Name"
        value={String(config.functionName ?? "")}
        onChange={(v) => onChange("functionName", v)}
        placeholder="myFunction"
      />
      <TextField
        id="config-code"
        label="Code"
        value={String(config.code ?? "")}
        onChange={(v) => onChange("code", v)}
        multiline
        placeholder="return input.toUpperCase();"
      />
    </>
  );
}

function SwitchConfigPanel({
  config,
  onChange,
}: {
  config: Record<string, unknown>;
  onChange: (key: string, value: unknown) => void;
}) {
  return (
    <>
      <TextField
        id="config-expression"
        label="Switch Expression"
        value={String(config.expression ?? "")}
        onChange={(v) => onChange("expression", v)}
        placeholder="input.status"
      />
      <TextField
        id="config-cases"
        label="Cases (comma-separated)"
        value={String(config.cases ?? "")}
        onChange={(v) => onChange("cases", v)}
        placeholder="case_0,case_1"
      />
    </>
  );
}

function LoopConfigPanel({
  config,
  onChange,
}: {
  config: Record<string, unknown>;
  onChange: (key: string, value: unknown) => void;
}) {
  return (
    <>
      <SelectField
        id="config-loopType"
        label="Loop Type"
        value={String(config.loopType ?? "forEach")}
        options={LOOP_TYPE_OPTIONS}
        onChange={(v) => onChange("loopType", v)}
      />
      <NumberField
        id="config-maxIterations"
        label="Max Iterations"
        value={Number(config.maxIterations ?? 100)}
        onChange={(v) => onChange("maxIterations", v)}
        min={1}
        max={10000}
      />
    </>
  );
}

function ParallelConfigPanel({
  config,
  onChange,
}: {
  config: Record<string, unknown>;
  onChange: (key: string, value: unknown) => void;
}) {
  return (
    <NumberField
      id="config-branches"
      label="Number of Branches"
      value={Number(config.branches ?? 2)}
      onChange={(v) => onChange("branches", v)}
      min={2}
      max={20}
    />
  );
}

function MergeConfigPanel({
  config,
  onChange,
}: {
  config: Record<string, unknown>;
  onChange: (key: string, value: unknown) => void;
}) {
  return (
    <SelectField
      id="config-strategy"
      label="Merge Strategy"
      value={String(config.strategy ?? "waitAll")}
      options={MERGE_STRATEGY_OPTIONS}
      onChange={(v) => onChange("strategy", v)}
    />
  );
}

function DelayConfigPanel({
  config,
  onChange,
}: {
  config: Record<string, unknown>;
  onChange: (key: string, value: unknown) => void;
}) {
  return (
    <NumberField
      id="config-delayMs"
      label="Delay (ms)"
      value={Number(config.delayMs ?? 1000)}
      onChange={(v) => onChange("delayMs", v)}
      min={0}
    />
  );
}

function VectorSearchConfigPanel({
  config,
  onChange,
}: {
  config: Record<string, unknown>;
  onChange: (key: string, value: unknown) => void;
}) {
  return (
    <>
      <TextField
        id="config-collection"
        label="Collection"
        value={String(config.collection ?? "")}
        onChange={(v) => onChange("collection", v)}
        placeholder="my_vectors"
      />
      <NumberField
        id="config-topK"
        label="Top K"
        value={Number(config.topK ?? 5)}
        onChange={(v) => onChange("topK", v)}
        min={1}
        max={100}
      />
      <SliderField
        id="config-threshold"
        label="Similarity Threshold"
        value={Number(config.threshold ?? 0.7)}
        min={0}
        max={1}
        step={0.05}
        onChange={(v) => onChange("threshold", v)}
      />
    </>
  );
}

function DocumentLoaderConfigPanel({
  config,
  onChange,
}: {
  config: Record<string, unknown>;
  onChange: (key: string, value: unknown) => void;
}) {
  return (
    <>
      <TextField
        id="config-source"
        label="Source"
        value={String(config.source ?? "")}
        onChange={(v) => onChange("source", v)}
        placeholder="https://… or file path"
      />
      <NumberField
        id="config-chunkSize"
        label="Chunk Size"
        value={Number(config.chunkSize ?? 512)}
        onChange={(v) => onChange("chunkSize", v)}
        min={1}
      />
      <NumberField
        id="config-overlap"
        label="Overlap"
        value={Number(config.overlap ?? 64)}
        onChange={(v) => onChange("overlap", v)}
        min={0}
      />
    </>
  );
}

function HumanApprovalConfigPanel({
  config,
  onChange,
}: {
  config: Record<string, unknown>;
  onChange: (key: string, value: unknown) => void;
}) {
  return (
    <>
      <TextField
        id="config-approver"
        label="Approver"
        value={String(config.approver ?? "")}
        onChange={(v) => onChange("approver", v)}
        placeholder="user@example.com"
      />
      <NumberField
        id="config-timeoutMinutes"
        label="Timeout (minutes)"
        value={Number(config.timeoutMinutes ?? 60)}
        onChange={(v) => onChange("timeoutMinutes", v)}
        min={1}
      />
      <TextField
        id="config-message"
        label="Approval Message"
        value={String(config.message ?? "")}
        onChange={(v) => onChange("message", v)}
        multiline
        placeholder="Please review and approve…"
      />
    </>
  );
}

function HumanInputConfigPanel({
  config,
  onChange,
}: {
  config: Record<string, unknown>;
  onChange: (key: string, value: unknown) => void;
}) {
  return (
    <>
      <TextField
        id="config-prompt"
        label="Prompt"
        value={String(config.prompt ?? "")}
        onChange={(v) => onChange("prompt", v)}
        multiline
        placeholder="Please provide…"
      />
      <SelectField
        id="config-inputType"
        label="Input Type"
        value={String(config.inputType ?? "text")}
        options={[
          { value: "text", label: "Text" },
          { value: "choice", label: "Choice" },
          { value: "confirm", label: "Confirm" },
        ]}
        onChange={(v) => onChange("inputType", v)}
      />
    </>
  );
}

function DLPScanConfigPanel({
  config,
  onChange,
}: {
  config: Record<string, unknown>;
  onChange: (key: string, value: unknown) => void;
}) {
  return (
    <>
      <TextField
        id="config-policyId"
        label="Policy ID"
        value={String(config.policyId ?? "")}
        onChange={(v) => onChange("policyId", v)}
        placeholder="policy_abc123"
      />
      <SelectField
        id="config-action"
        label="Action"
        value={String(config.action ?? "redact")}
        options={DLP_ACTION_OPTIONS}
        onChange={(v) => onChange("action", v)}
      />
    </>
  );
}

function CostGateConfigPanel({
  config,
  onChange,
}: {
  config: Record<string, unknown>;
  onChange: (key: string, value: unknown) => void;
}) {
  return (
    <>
      <NumberField
        id="config-maxCost"
        label="Max Cost"
        value={Number(config.maxCost ?? 10)}
        onChange={(v) => onChange("maxCost", v)}
        min={0}
      />
      <SelectField
        id="config-currency"
        label="Currency"
        value={String(config.currency ?? "$")}
        options={[
          { value: "$", label: "USD ($)" },
          { value: "€", label: "EUR (€)" },
          { value: "£", label: "GBP (£)" },
        ]}
        onChange={(v) => onChange("currency", v)}
      />
    </>
  );
}

function SubAgentConfigPanel({
  config,
  onChange,
}: {
  config: Record<string, unknown>;
  onChange: (key: string, value: unknown) => void;
}) {
  return (
    <>
      <TextField
        id="config-agentId"
        label="Agent ID"
        value={String(config.agentId ?? "")}
        onChange={(v) => onChange("agentId", v)}
        placeholder="agent_abc123"
      />
      <TextField
        id="config-agentName"
        label="Agent Name"
        value={String(config.agentName ?? "")}
        onChange={(v) => onChange("agentName", v)}
        placeholder="My Sub-Agent"
      />
    </>
  );
}

// ─── Node type → config panel mapping ────────────────────────────────

const CONFIG_PANELS: Record<
  string,
  (props: {
    config: Record<string, unknown>;
    onChange: (key: string, value: unknown) => void;
  }) => React.ReactNode
> = {
  llmNode: LLMConfigPanel,
  toolNode: ToolConfigPanel,
  conditionNode: ConditionConfigPanel,
  inputNode: InputConfigPanel,
  outputNode: OutputConfigPanel,
  webhookTriggerNode: WebhookConfigPanel,
  scheduleTriggerNode: ScheduleConfigPanel,
  streamOutputNode: StreamOutputConfigPanel,
  embeddingNode: EmbeddingConfigPanel,
  visionNode: VisionConfigPanel,
  structuredOutputNode: StructuredOutputConfigPanel,
  mcpToolNode: MCPToolConfigPanel,
  httpRequestNode: HTTPRequestConfigPanel,
  databaseQueryNode: DatabaseQueryConfigPanel,
  functionCallNode: FunctionCallConfigPanel,
  switchNode: SwitchConfigPanel,
  loopNode: LoopConfigPanel,
  parallelNode: ParallelConfigPanel,
  mergeNode: MergeConfigPanel,
  delayNode: DelayConfigPanel,
  vectorSearchNode: VectorSearchConfigPanel,
  documentLoaderNode: DocumentLoaderConfigPanel,
  humanApprovalNode: HumanApprovalConfigPanel,
  humanInputNode: HumanInputConfigPanel,
  dlpScanNode: DLPScanConfigPanel,
  costGateNode: CostGateConfigPanel,
  subAgentNode: SubAgentConfigPanel,
};

// ─── Main panel ──────────────────────────────────────────────────────

/** Right-side panel that shows properties for the selected node */
export function PropertyPanel() {
  const { nodes, selectedNodeId, updateNodeData, deleteNode } =
    useCanvasStore();

  const selectedNode = nodes.find((n) => n.id === selectedNodeId);

  const handleLabelChange = useCallback(
    (value: string) => {
      if (!selectedNodeId) return;
      updateNodeData(selectedNodeId, { label: value } as Partial<CustomNodeData>);
    },
    [selectedNodeId, updateNodeData],
  );

  const handleDescriptionChange = useCallback(
    (value: string) => {
      if (!selectedNodeId) return;
      updateNodeData(selectedNodeId, {
        description: value,
      } as Partial<CustomNodeData>);
    },
    [selectedNodeId, updateNodeData],
  );

  const handleConfigChange = useCallback(
    (key: string, value: unknown) => {
      if (!selectedNodeId || !selectedNode) return;
      const currentData = selectedNode.data as CustomNodeData;
      updateNodeData(selectedNodeId, {
        config: { ...currentData.config, [key]: value },
      } as Partial<CustomNodeData>);
    },
    [selectedNodeId, selectedNode, updateNodeData],
  );

  const handleDelete = useCallback(() => {
    if (!selectedNodeId) return;
    deleteNode(selectedNodeId);
  }, [selectedNodeId, deleteNode]);

  if (!selectedNode) {
    return (
      <aside
        className="flex h-full w-72 flex-col border-l border-border bg-card"
        aria-label="Property panel"
      >
        <div className="border-b border-border px-4 py-3">
          <h2 className="text-sm font-semibold">Properties</h2>
        </div>
        <div className="flex flex-1 items-center justify-center p-4">
          <p className="text-sm text-muted-foreground">
            Select a node to edit its properties
          </p>
        </div>
      </aside>
    );
  }

  const nodeData = selectedNode.data as CustomNodeData;
  const nodeType = selectedNode.type ?? "";
  const ConfigPanel = CONFIG_PANELS[nodeType];

  return (
    <aside
      className="flex h-full w-72 flex-col border-l border-border bg-card overflow-y-auto"
      aria-label="Property panel"
    >
      <div className="border-b border-border px-4 py-3">
        <h2 className="text-sm font-semibold">Properties</h2>
      </div>

      <div className="flex-1 space-y-4 p-4">
        {/* Node type badge */}
        <div className="flex items-center gap-2">
          <span className="rounded-full bg-muted px-2 py-0.5 text-xs font-medium uppercase">
            {nodeData.category}
          </span>
          <span className="text-xs text-muted-foreground truncate">
            {selectedNode.id}
          </span>
        </div>

        {/* Label */}
        <div className="space-y-1.5">
          <Label htmlFor="node-label">Label</Label>
          <Input
            id="node-label"
            value={nodeData.label}
            onChange={(e) => handleLabelChange(e.target.value)}
          />
        </div>

        {/* Description */}
        <div className="space-y-1.5">
          <Label htmlFor="node-description">Description</Label>
          <Textarea
            id="node-description"
            value={nodeData.description ?? ""}
            onChange={(e) => handleDescriptionChange(e.target.value)}
            rows={2}
          />
        </div>

        {/* Divider */}
        <div className="border-t border-border pt-2">
          <h3 className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-3">
            Configuration
          </h3>
        </div>

        {/* Type-specific config panel */}
        {ConfigPanel ? (
          <ConfigPanel config={nodeData.config} onChange={handleConfigChange} />
        ) : (
          /* Fallback: generic key/value fields */
          Object.entries(nodeData.config)
            .filter(([, v]) => typeof v === "string" || typeof v === "number")
            .map(([key, value]) => (
              <div key={key} className="space-y-1.5">
                <Label htmlFor={`config-${key}`}>{key}</Label>
                {typeof value === "string" && value.length > 60 ? (
                  <Textarea
                    id={`config-${key}`}
                    value={value}
                    onChange={(e) => handleConfigChange(key, e.target.value)}
                    rows={3}
                  />
                ) : (
                  <Input
                    id={`config-${key}`}
                    value={String(value)}
                    onChange={(e) => handleConfigChange(key, e.target.value)}
                  />
                )}
              </div>
            ))
        )}

        {/* Delete */}
        <Button
          variant="destructive"
          size="sm"
          className="w-full"
          onClick={handleDelete}
          aria-label="Delete selected node"
        >
          Delete Node
        </Button>
      </div>
    </aside>
  );
}
