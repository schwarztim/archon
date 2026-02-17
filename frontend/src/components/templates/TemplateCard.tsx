import { cn } from "@/utils/cn";
import { Button } from "@/components/ui/Button";
import type { Template } from "@/api/templates";

/** Human-readable labels for template categories */
const CATEGORY_LABELS: Record<string, string> = {
  customer_support: "Customer Support",
  data_analysis: "Data Analysis",
  content_creation: "Content Creation",
  development: "Development",
  sales_marketing: "Sales & Marketing",
  hr_recruiting: "HR & Recruiting",
  legal_compliance: "Legal & Compliance",
  operations: "Operations",
};

interface TemplateCardProps {
  template: Template;
  onUse: (template: Template) => void;
}

export function TemplateCard({ template, onUse }: TemplateCardProps) {
  const categoryLabel =
    CATEGORY_LABELS[template.category] ?? template.category;

  return (
    <div
      className={cn(
        "group flex flex-col rounded-lg border border-border bg-card p-4 shadow-sm transition-shadow hover:shadow-md",
        template.is_featured && "ring-2 ring-primary/30",
      )}
    >
      {/* Header */}
      <div className="mb-2 flex items-start justify-between gap-2">
        <h3 className="text-sm font-semibold text-card-foreground leading-tight">
          {template.name}
        </h3>
        {template.is_featured && (
          <span
            className="shrink-0 rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-medium text-primary"
            aria-label="Featured template"
          >
            Featured
          </span>
        )}
      </div>

      {/* Category badge */}
      <span className="mb-2 inline-block w-fit rounded-md bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">
        {categoryLabel}
      </span>

      {/* Description */}
      <p className="mb-3 flex-1 text-xs text-muted-foreground line-clamp-3">
        {template.description ?? "No description provided."}
      </p>

      {/* Tags */}
      {template.tags.length > 0 && (
        <div className="mb-3 flex flex-wrap gap-1" aria-label="Template tags">
          {template.tags.slice(0, 4).map((tag) => (
            <span
              key={tag}
              className="rounded bg-secondary px-1.5 py-0.5 text-[10px] text-secondary-foreground"
            >
              {tag}
            </span>
          ))}
          {template.tags.length > 4 && (
            <span className="text-[10px] text-muted-foreground">
              +{template.tags.length - 4}
            </span>
          )}
        </div>
      )}

      {/* Footer */}
      <div className="flex items-center justify-between border-t border-border pt-3">
        <span className="text-[11px] text-muted-foreground">
          {template.usage_count} {template.usage_count === 1 ? "use" : "uses"}
        </span>
        <Button
          size="sm"
          onClick={() => onUse(template)}
          aria-label={`Use template: ${template.name}`}
        >
          Use Template
        </Button>
      </div>
    </div>
  );
}
