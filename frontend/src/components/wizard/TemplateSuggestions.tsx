import { useState, useEffect } from "react";
import { Layers, Loader2, ArrowRight } from "lucide-react";
import { listTemplates, type Template } from "@/api/templates";

interface TemplateSuggestionsProps {
  keywords: string[];
  onSelect: (template: Template) => void;
}

/** Sidebar section showing templates matching the wizard description keywords. */
export function TemplateSuggestions({
  keywords,
  onSelect,
}: TemplateSuggestionsProps) {
  const [templates, setTemplates] = useState<Template[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (keywords.length === 0) {
      setTemplates([]);
      return;
    }

    let cancelled = false;
    const searchQuery = keywords.slice(0, 5).join(" ");

    async function fetchTemplates() {
      setLoading(true);
      try {
        const res = await listTemplates({ search: searchQuery, limit: 5 });
        if (!cancelled && Array.isArray(res.data)) {
          setTemplates(res.data);
        }
      } catch {
        // Template search is optional, fail silently
        if (!cancelled) setTemplates([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void fetchTemplates();
    return () => {
      cancelled = true;
    };
  }, [keywords.join(",")]);

  if (loading) {
    return (
      <div className="rounded-lg border border-surface-border bg-surface-base p-4">
        <div className="flex items-center gap-2 mb-3">
          <Layers size={14} className="text-purple-400" />
          <h4 className="text-xs font-medium text-gray-400">Similar Templates</h4>
        </div>
        <div className="flex items-center justify-center py-4">
          <Loader2 size={16} className="animate-spin text-gray-500" />
        </div>
      </div>
    );
  }

  if (templates.length === 0) return null;

  return (
    <div className="rounded-lg border border-surface-border bg-surface-base p-4">
      <div className="flex items-center gap-2 mb-3">
        <Layers size={14} className="text-purple-400" />
        <h4 className="text-xs font-medium text-gray-400">Similar Templates</h4>
      </div>
      <div className="space-y-2">
        {templates.map((tpl) => (
          <button
            key={tpl.id}
            type="button"
            onClick={() => onSelect(tpl)}
            className="flex w-full items-center gap-2 rounded-lg border border-surface-border bg-surface-raised p-2.5 text-left transition-colors hover:border-purple-500/30"
          >
            <div className="flex-1 min-w-0">
              <p className="text-xs font-medium text-white truncate">
                {tpl.name}
              </p>
              {tpl.description && (
                <p className="text-[10px] text-gray-500 line-clamp-2 mt-0.5">
                  {tpl.description}
                </p>
              )}
              {tpl.tags.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-1">
                  {tpl.tags.slice(0, 3).map((tag) => (
                    <span
                      key={tag}
                      className="rounded bg-purple-500/10 px-1.5 py-0.5 text-[9px] text-purple-400"
                    >
                      {tag}
                    </span>
                  ))}
                </div>
              )}
            </div>
            <ArrowRight size={12} className="text-gray-600 flex-shrink-0" />
          </button>
        ))}
      </div>
    </div>
  );
}
