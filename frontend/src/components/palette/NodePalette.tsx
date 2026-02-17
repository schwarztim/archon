import { useCallback, useState } from "react";
import { PALETTE_ITEMS } from "@/utils/paletteItems";
import type { PaletteItem, NodeCategory } from "@/types";
import { cn } from "@/utils/cn";
import { Input } from "@/components/ui/Input";

const categoryLabels: Record<NodeCategory, string> = {
  input: "Input / Triggers",
  output: "Output",
  llm: "AI / LLM",
  tool: "Tools",
  condition: "Logic",
  rag: "RAG",
  human: "Human-in-the-Loop",
  security: "Security",
  subagent: "Sub-Agents",
  transform: "Transform",
  custom: "Custom",
};

const categoryOrder: NodeCategory[] = [
  "input",
  "output",
  "llm",
  "tool",
  "condition",
  "rag",
  "human",
  "security",
  "subagent",
];

function PaletteCard({ item }: { item: PaletteItem }) {
  const onDragStart = useCallback(
    (event: React.DragEvent) => {
      event.dataTransfer.setData(
        "application/archon-node",
        JSON.stringify(item),
      );
      event.dataTransfer.effectAllowed = "move";
    },
    [item],
  );

  return (
    <div
      draggable
      onDragStart={onDragStart}
      className={cn(
        "flex cursor-grab items-center gap-2 rounded-md border border-border bg-card px-3 py-2 text-sm transition-colors hover:bg-accent active:cursor-grabbing",
      )}
      role="listitem"
      aria-label={`Drag to add ${item.label} node`}
    >
      <span className="text-muted-foreground text-xs font-medium">
        {item.label}
      </span>
    </div>
  );
}

function CollapsibleGroup({
  label,
  children,
  defaultOpen = true,
}: {
  label: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between px-1 py-1 text-xs font-medium uppercase tracking-wider text-muted-foreground hover:text-foreground transition-colors"
        aria-expanded={open}
      >
        <span>{label}</span>
        <span className="text-[10px]">{open ? "▼" : "▶"}</span>
      </button>
      {open && <div className="mt-1 space-y-1">{children}</div>}
    </div>
  );
}

export function NodePalette() {
  const [search, setSearch] = useState("");
  const query = search.toLowerCase();

  const filtered = query
    ? PALETTE_ITEMS.filter(
        (p) =>
          p.label.toLowerCase().includes(query) ||
          p.description.toLowerCase().includes(query),
      )
    : PALETTE_ITEMS;

  const grouped = categoryOrder
    .map((cat) => ({
      category: cat,
      label: categoryLabels[cat],
      items: filtered.filter((p) => p.category === cat),
    }))
    .filter((g) => g.items.length > 0);

  return (
    <aside
      className="flex h-full w-56 flex-col border-r border-border bg-card overflow-y-auto"
      aria-label="Node palette"
    >
      <div className="border-b border-border px-4 py-3">
        <h2 className="text-sm font-semibold">Nodes</h2>
      </div>
      <div className="px-3 pt-3 pb-2">
        <Input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search nodes…"
          className="h-7 text-xs"
          aria-label="Search nodes"
        />
      </div>
      <nav className="flex-1 space-y-3 p-3 pt-0" role="list">
        {grouped.map((group) => (
          <CollapsibleGroup key={group.category} label={group.label}>
            {group.items.map((item) => (
              <PaletteCard key={item.type} item={item} />
            ))}
          </CollapsibleGroup>
        ))}
        {grouped.length === 0 && (
          <p className="text-xs text-muted-foreground px-1">No nodes found</p>
        )}
      </nav>
    </aside>
  );
}
