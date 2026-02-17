import type { MCPComponentPayload } from "@/api/mcp";
import { DataTable } from "./components/DataTable";
import { ChartComponent } from "./components/ChartComponent";
import { DynamicForm } from "./components/DynamicForm";
import { ApprovalPanel } from "./components/ApprovalPanel";
import { CodeEditor } from "./components/CodeEditor";
import { MarkdownViewer } from "./components/MarkdownViewer";
import { ImageGallery } from "./components/ImageGallery";

// ── Types ────────────────────────────────────────────────────────────

interface ComponentRendererProps {
  component: MCPComponentPayload;
  onAction?: (action: string, payload: Record<string, unknown>) => void;
}

// ── Component ────────────────────────────────────────────────────────

/**
 * Routes an MCP component payload to the correct React component.
 */
export function ComponentRenderer({
  component,
  onAction,
}: ComponentRendererProps) {
  const { type, props } = component;

  switch (type) {
    case "data_table":
      return (
        <DataTable
          columns={(props.columns as { key: string; label: string; sortable?: boolean }[]) ?? []}
          rows={(props.rows as Record<string, unknown>[]) ?? []}
          pageSize={(props.pageSize as number) ?? 10}
          onAction={onAction}
        />
      );

    case "chart":
      return (
        <ChartComponent
          chartType={(props.chartType as "bar" | "line" | "pie") ?? "bar"}
          data={(props.data as Record<string, unknown>[]) ?? []}
          xKey={(props.xKey as string) ?? "x"}
          yKey={(props.yKey as string) ?? "y"}
          title={props.title as string | undefined}
          height={(props.height as number) ?? 300}
        />
      );

    case "form":
      return (
        <DynamicForm
          title={props.title as string | undefined}
          fields={(props.fields as {
            name: string;
            label: string;
            type: "text" | "number" | "email" | "select" | "textarea" | "checkbox";
            required?: boolean;
            placeholder?: string;
            options?: { label: string; value: string }[];
          }[]) ?? []}
          submitLabel={props.submitLabel as string | undefined}
          onSubmit={(values) => onAction?.("form_submit", values)}
          onAction={onAction}
        />
      );

    case "approval":
      return (
        <ApprovalPanel
          title={(props.title as string) ?? "Approval Required"}
          description={props.description as string | undefined}
          metadata={props.metadata as Record<string, string> | undefined}
          requireComment={props.requireComment as boolean | undefined}
          onAction={(decision, comment) =>
            onAction?.("approval_decision", { decision, comment })
          }
        />
      );

    case "code":
      return (
        <CodeEditor
          code={(props.code as string) ?? ""}
          language={props.language as string | undefined}
          title={props.title as string | undefined}
          readOnly={(props.readOnly as boolean) ?? true}
        />
      );

    case "markdown":
      return <MarkdownViewer content={(props.content as string) ?? ""} />;

    case "image_gallery":
      return (
        <ImageGallery
          images={(props.images as { src: string; alt?: string; caption?: string }[]) ?? []}
          columns={(props.columns as number) ?? 3}
        />
      );

    default:
      return (
        <div className="rounded-lg border border-yellow-500/30 bg-yellow-500/5 p-3 text-xs text-yellow-400">
          Unknown component type: {type}
        </div>
      );
  }
}
