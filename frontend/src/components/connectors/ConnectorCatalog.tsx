import { useState, useMemo } from "react";
import { Search } from "lucide-react";
import { Input } from "@/components/ui/Input";
import { ConnectorCard } from "./ConnectorCard";
import type { ConnectorTypeSchema } from "@/api/connectors";

const ALL_CATEGORIES = ["Database", "SaaS", "Communication", "Cloud", "AI", "Custom"];

interface ConnectorCatalogProps {
  types: ConnectorTypeSchema[];
  onSelectType: (type: ConnectorTypeSchema) => void;
}

export function ConnectorCatalog({ types, onSelectType }: ConnectorCatalogProps) {
  const [searchQuery, setSearchQuery] = useState("");
  const [categoryFilter, setCategoryFilter] = useState<string>("All");

  const filteredTypes = useMemo(() => {
    return types.filter((t) => {
      const matchesSearch =
        !searchQuery ||
        t.label.toLowerCase().includes(searchQuery.toLowerCase()) ||
        t.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        t.description.toLowerCase().includes(searchQuery.toLowerCase());
      const matchesCategory = categoryFilter === "All" || t.category === categoryFilter;
      return matchesSearch && matchesCategory;
    });
  }, [types, searchQuery, categoryFilter]);

  return (
    <div>
      {/* Search & Category Filter */}
      <div className="mb-6 flex flex-wrap items-center gap-3">
        <div className="relative max-w-xs flex-1">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
          <Input
            placeholder="Search connectors…"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="bg-gray-50 pl-9 dark:bg-surface-base"
          />
        </div>
        <div className="flex gap-1">
          <button
            onClick={() => setCategoryFilter("All")}
            className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${
              categoryFilter === "All"
                ? "bg-purple-600 text-white"
                : "bg-gray-100 text-gray-600 hover:text-gray-900 dark:bg-surface-raised dark:text-gray-400 dark:hover:text-white"
            }`}
          >
            All
          </button>
          {ALL_CATEGORIES.map((cat) => (
            <button
              key={cat}
              onClick={() => setCategoryFilter(cat)}
              className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${
                categoryFilter === cat
                  ? "bg-purple-600 text-white"
                  : "bg-gray-100 text-gray-600 hover:text-gray-900 dark:bg-surface-raised dark:text-gray-400 dark:hover:text-white"
              }`}
            >
              {cat}
            </button>
          ))}
        </div>
      </div>

      {/* Grid of connector cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {filteredTypes.map((t) => (
          <ConnectorCard
            key={t.name}
            name={t.name}
            label={t.label}
            category={t.category}
            icon={t.icon}
            description={t.description}
            supportsOauth={t.supports_oauth}
            onConnect={() => onSelectType(t)}
          />
        ))}
      </div>

      {filteredTypes.length === 0 && (
        <div className="flex flex-col items-center justify-center py-12">
          <p className="text-sm text-gray-500 dark:text-gray-500">
            No connectors match your search.
          </p>
        </div>
      )}
    </div>
  );
}
