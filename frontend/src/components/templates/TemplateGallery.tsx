import { useState, useCallback, useMemo } from "react";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { TemplateCard } from "./TemplateCard";
import type { Template } from "@/api/templates";

/** Available template categories for filtering */
const CATEGORIES = [
  { value: "", label: "All Categories" },
  { value: "customer_support", label: "Customer Support" },
  { value: "data_analysis", label: "Data Analysis" },
  { value: "content_creation", label: "Content Creation" },
  { value: "development", label: "Development" },
  { value: "sales_marketing", label: "Sales & Marketing" },
  { value: "hr_recruiting", label: "HR & Recruiting" },
  { value: "legal_compliance", label: "Legal & Compliance" },
  { value: "operations", label: "Operations" },
] as const;

interface TemplateGalleryProps {
  /** List of templates to display */
  templates: Template[];
  /** Whether templates are currently loading */
  isLoading?: boolean;
  /** Error message if loading failed */
  error?: string | null;
  /** Called when user clicks "Use Template" */
  onUseTemplate: (template: Template) => void;
  /** Called when filters change (for server-side filtering) */
  onFilterChange?: (filters: {
    category: string;
    search: string;
  }) => void;
}

export function TemplateGallery({
  templates,
  isLoading = false,
  error = null,
  onUseTemplate,
  onFilterChange,
}: TemplateGalleryProps) {
  const [search, setSearch] = useState("");
  const [selectedCategory, setSelectedCategory] = useState("");

  const handleSearchChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const value = e.target.value;
      setSearch(value);
      onFilterChange?.({ category: selectedCategory, search: value });
    },
    [selectedCategory, onFilterChange],
  );

  const handleCategoryChange = useCallback(
    (category: string) => {
      setSelectedCategory(category);
      onFilterChange?.({ category, search });
    },
    [search, onFilterChange],
  );

  // Client-side filtering as fallback when onFilterChange is not provided
  const filteredTemplates = useMemo(() => {
    if (onFilterChange) return templates;

    return templates.filter((t) => {
      const matchesCategory =
        !selectedCategory || t.category === selectedCategory;
      const matchesSearch =
        !search ||
        t.name.toLowerCase().includes(search.toLowerCase()) ||
        t.description?.toLowerCase().includes(search.toLowerCase()) ||
        t.tags.some((tag) =>
          tag.toLowerCase().includes(search.toLowerCase()),
        );
      return matchesCategory && matchesSearch;
    });
  }, [templates, selectedCategory, search, onFilterChange]);

  return (
    <div className="flex h-full flex-col gap-4 p-6">
      {/* Header */}
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-bold text-foreground">
          Template Gallery
        </h1>
        <p className="text-sm text-muted-foreground">
          Browse pre-built agent templates and deploy them with one click.
        </p>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3">
        <Input
          type="search"
          placeholder="Search templates..."
          value={search}
          onChange={handleSearchChange}
          className="max-w-xs"
          aria-label="Search templates"
        />
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Category filters">
          {CATEGORIES.map((cat) => (
            <Button
              key={cat.value}
              variant={selectedCategory === cat.value ? "default" : "outline"}
              size="sm"
              onClick={() => handleCategoryChange(cat.value)}
              aria-pressed={selectedCategory === cat.value}
            >
              {cat.label}
            </Button>
          ))}
        </div>
      </div>

      {/* Content */}
      {error && (
        <div
          className="rounded-md border border-destructive/50 bg-destructive/10 p-4 text-sm text-destructive"
          role="alert"
        >
          {error}
        </div>
      )}

      {isLoading && (
        <div className="flex flex-1 items-center justify-center">
          <div className="flex flex-col items-center gap-2 text-muted-foreground">
            <div className="h-8 w-8 animate-spin rounded-full border-2 border-muted-foreground border-t-transparent" aria-hidden="true" />
            <span className="text-sm">Loading templates...</span>
          </div>
        </div>
      )}

      {!isLoading && !error && filteredTemplates.length === 0 && (
        <div className="flex flex-1 items-center justify-center">
          <p className="text-sm text-muted-foreground">
            No templates found. Try adjusting your filters.
          </p>
        </div>
      )}

      {!isLoading && !error && filteredTemplates.length > 0 && (
        <div
          className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4"
          role="list"
          aria-label="Template list"
        >
          {filteredTemplates.map((template) => (
            <div key={template.id} role="listitem">
              <TemplateCard
                template={template}
                onUse={onUseTemplate}
              />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
