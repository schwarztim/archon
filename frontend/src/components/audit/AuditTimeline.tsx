import { useState, useCallback, useRef, useEffect } from "react";
import { AuditEventCard, type AuditEntry } from "./AuditEventCard";

interface Props {
  entries: AuditEntry[];
  hasMore: boolean;
  onLoadMore: () => void;
  loadingMore: boolean;
}

export function AuditTimeline({
  entries,
  hasMore,
  onLoadMore,
  loadingMore,
}: Props) {
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const sentinelRef = useRef<HTMLDivElement | null>(null);

  // Infinite scroll via IntersectionObserver
  useEffect(() => {
    if (!hasMore || loadingMore) return;
    const el = sentinelRef.current;
    if (!el) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) onLoadMore();
      },
      { threshold: 0.1 },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [hasMore, loadingMore, onLoadMore]);

  if (entries.length === 0) {
    return (
      <div className="flex h-48 items-center justify-center rounded-lg border border-[#2a2d37] bg-[#1a1d27]">
        <p className="text-sm text-gray-500">No audit events yet.</p>
      </div>
    );
  }

  return (
    <div className="relative border-l-2 border-[#2a2d37] pl-2">
      {entries.map((entry) => (
        <AuditEventCard
          key={entry.id}
          entry={entry}
          expanded={expandedId === entry.id}
          onToggle={() =>
            setExpandedId(expandedId === entry.id ? null : entry.id)
          }
        />
      ))}

      {/* Infinite scroll sentinel */}
      {hasMore && (
        <div ref={sentinelRef} className="flex justify-center py-4">
          {loadingMore ? (
            <span className="text-xs text-gray-500">Loading more…</span>
          ) : (
            <span className="text-xs text-gray-600">Scroll for more</span>
          )}
        </div>
      )}
    </div>
  );
}
