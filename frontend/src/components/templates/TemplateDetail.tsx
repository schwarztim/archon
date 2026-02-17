import {
  X,
  Tag,
  Zap,
  Loader2,
  BarChart3,
  Clock,
  User,
  GitBranch,
} from "lucide-react";
import { Button } from "@/components/ui/Button";

interface TemplateDetailProps {
  /** Template object (API or seed-derived) */
  template: {
    id?: string;
    name: string;
    description: string;
    category: string;
    tags: string[];
    definition?: Record<string, unknown>;
    usage_count?: number;
    created_at?: string;
    author_id?: string;
  };
  /** Close the modal */
  onClose: () => void;
  /** Instantiate or use this template */
  onUse: () => void;
  /** Whether instantiation is in progress */
  loading?: boolean;
}

const CATEGORY_COLORS: Record<string, string> = {
  "Customer Support": "bg-blue-500/20 text-blue-400",
  "Data Analysis": "bg-emerald-500/20 text-emerald-400",
  "Content Generation": "bg-orange-500/20 text-orange-400",
  "Code Assistant": "bg-cyan-500/20 text-cyan-400",
  "Research": "bg-violet-500/20 text-violet-400",
  "DevOps": "bg-red-500/20 text-red-400",
  "Custom": "bg-gray-500/20 text-gray-400",
};

/**
 * Modal that shows full template details with a graph preview placeholder
 * and a one-click "Use Template" action.
 */
export function TemplateDetail({
  template,
  onClose,
  onUse,
  loading = false,
}: TemplateDetailProps) {
  const catColor =
    CATEGORY_COLORS[template.category] ?? "bg-gray-500/20 text-gray-400";

  const definition = template.definition ?? {};
  const model = (definition.model as string) ?? null;
  const tools = (definition.tools as string[]) ?? [];
  const temperature = definition.temperature as number | undefined;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label={`Template details: ${template.name}`}
    >
      <div className="relative w-full max-w-lg rounded-xl border border-[#2a2d37] bg-[#12141e] shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-[#2a2d37] px-6 py-4">
          <div>
            <h2 className="text-lg font-semibold text-white">
              {template.name}
            </h2>
            <span
              className={`mt-1 inline-block rounded-full px-2 py-0.5 text-[10px] font-medium ${catColor}`}
            >
              {template.category}
            </span>
          </div>
          <button
            onClick={onClose}
            className="rounded p-1 text-gray-400 hover:bg-white/10 hover:text-white"
            aria-label="Close"
          >
            <X size={18} />
          </button>
        </div>

        {/* Body */}
        <div className="max-h-[60vh] overflow-y-auto px-6 py-5 space-y-5">
          {/* Description */}
          <p className="text-sm leading-relaxed text-gray-300">
            {template.description}
          </p>

          {/* Graph Preview placeholder */}
          <div className="rounded-lg border border-[#2a2d37] bg-[#0f1117] p-4">
            <div className="mb-2 flex items-center gap-2 text-xs font-medium text-gray-400">
              <GitBranch size={12} /> Graph Preview
            </div>
            <div className="flex h-24 items-center justify-center text-xs text-gray-600">
              {tools.length > 0 ? (
                <div className="flex flex-wrap items-center gap-2">
                  <span className="rounded bg-purple-500/10 px-2 py-1 text-purple-400">
                    Input
                  </span>
                  <span className="text-gray-600">→</span>
                  {tools.map((t, i) => (
                    <span key={i}>
                      <span className="rounded bg-blue-500/10 px-2 py-1 text-blue-400">
                        {String(t).replace(/_/g, " ")}
                      </span>
                      {i < tools.length - 1 && (
                        <span className="mx-1 text-gray-600">→</span>
                      )}
                    </span>
                  ))}
                  <span className="text-gray-600">→</span>
                  <span className="rounded bg-green-500/10 px-2 py-1 text-green-400">
                    Output
                  </span>
                </div>
              ) : (
                <span>No graph definition — uses default pipeline</span>
              )}
            </div>
          </div>

          {/* Configuration details */}
          {(model || temperature !== undefined) && (
            <div className="grid grid-cols-2 gap-3 text-sm">
              {model && (
                <div className="rounded-lg border border-[#2a2d37] bg-[#0f1117] px-3 py-2">
                  <span className="text-[10px] uppercase text-gray-500">
                    Model
                  </span>
                  <p className="text-white">{model}</p>
                </div>
              )}
              {temperature !== undefined && (
                <div className="rounded-lg border border-[#2a2d37] bg-[#0f1117] px-3 py-2">
                  <span className="text-[10px] uppercase text-gray-500">
                    Temperature
                  </span>
                  <p className="text-white">{temperature}</p>
                </div>
              )}
            </div>
          )}

          {/* Tags */}
          {template.tags.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {template.tags.map((tag) => (
                <span
                  key={tag}
                  className="inline-flex items-center gap-1 rounded-full bg-white/10 px-2 py-0.5 text-xs text-gray-400"
                >
                  <Tag size={10} /> {tag}
                </span>
              ))}
            </div>
          )}

          {/* Metadata row */}
          <div className="flex items-center gap-4 text-xs text-gray-500">
            {template.usage_count !== undefined && (
              <span className="flex items-center gap-1">
                <BarChart3 size={10} /> {template.usage_count} uses
              </span>
            )}
            {template.created_at && (
              <span className="flex items-center gap-1">
                <Clock size={10} />{" "}
                {new Date(template.created_at).toLocaleDateString()}
              </span>
            )}
            {template.author_id && (
              <span className="flex items-center gap-1">
                <User size={10} /> {template.author_id.slice(0, 8)}…
              </span>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="border-t border-[#2a2d37] px-6 py-4">
          <Button
            className="w-full bg-purple-600 hover:bg-purple-700"
            onClick={onUse}
            disabled={loading}
            aria-label={`Use template: ${template.name}`}
          >
            {loading ? (
              <Loader2 size={14} className="mr-1.5 animate-spin" />
            ) : (
              <Zap size={14} className="mr-1.5" />
            )}
            Use Template
          </Button>
        </div>
      </div>
    </div>
  );
}
