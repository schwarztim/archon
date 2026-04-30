/**
 * ArtifactBrowser — filterable, cursor-paginated list of artifacts.
 *
 * Filters: ``run_id``, ``content_type`` (substring match), ``tenant_id``
 * (admin-only). Pagination uses the backend's cursor scheme — the
 * "Next" button advances when ``next_cursor`` is non-null. Clicking a row
 * opens ``ArtifactPreview`` as a modal.
 */

import { useEffect, useState } from "react";
import {
  FileText,
  Image as ImageIcon,
  Package,
  Search,
  RefreshCw,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { useArtifacts } from "@/hooks/useArtifacts";
import type { Artifact, ListArtifactsOptions } from "@/types/artifacts";
import { ArtifactPreview } from "./ArtifactPreview";

interface ArtifactBrowserProps {
  /** Pre-filter to a specific run (used by ExecutionDetailPage). */
  runId?: string;
  /** Admin-only tenant filter. The backend silently overrides for non-admins,
   *  so it's safe to expose this UI to everyone — the filter is advisory. */
  showTenantFilter?: boolean;
  /** Whether the operator can delete artifacts. Defaults to ``true``. */
  canDelete?: boolean;
}

function pickIcon(contentType: string) {
  const ct = (contentType || "").toLowerCase();
  if (ct.startsWith("image/")) return ImageIcon;
  if (ct.startsWith("text/") || ct.includes("json") || ct.includes("xml"))
    return FileText;
  return Package;
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KiB`;
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MiB`;
  return `${(n / 1024 / 1024 / 1024).toFixed(2)} GiB`;
}

function shortId(id: string): string {
  return id ? `${id.slice(0, 8)}…` : "—";
}

export function ArtifactBrowser({
  runId,
  showTenantFilter = false,
  canDelete = true,
}: ArtifactBrowserProps) {
  const [filterRun, setFilterRun] = useState<string>(runId ?? "");
  const [filterContentType, setFilterContentType] = useState<string>("");
  const [filterTenant, setFilterTenant] = useState<string>("");
  const [cursor, setCursor] = useState<string | undefined>(undefined);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  // Reset cursor whenever a filter changes — filters re-page from the start.
  useEffect(() => {
    setCursor(undefined);
  }, [filterRun, filterContentType, filterTenant]);

  const opts: ListArtifactsOptions = {
    run_id: filterRun || undefined,
    content_type: filterContentType || undefined,
    tenant_id: filterTenant || undefined,
    limit: 25,
    cursor,
  };
  const query = useArtifacts(opts);

  const items: Artifact[] = query.data?.items ?? [];
  const nextCursor = query.data?.next_cursor ?? null;

  return (
    <div className="space-y-4">
      {/* Filters */}
      <div className="rounded-lg border border-surface-border bg-surface-raised p-4">
        <div className="flex items-center justify-between">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-white">
            <Search size={14} /> Filters
          </h2>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => void query.refetch()}
            aria-label="Refresh artifacts"
          >
            <RefreshCw size={14} className="mr-1.5" /> Refresh
          </Button>
        </div>
        <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <div>
            <Label htmlFor="filter-run" className="mb-1 block text-xs">
              Run ID
            </Label>
            <Input
              id="filter-run"
              value={filterRun}
              placeholder="UUID"
              onChange={(e) => setFilterRun(e.target.value)}
              disabled={Boolean(runId)}
            />
          </div>
          <div>
            <Label htmlFor="filter-content-type" className="mb-1 block text-xs">
              Content type
            </Label>
            <Input
              id="filter-content-type"
              value={filterContentType}
              placeholder="application/json"
              onChange={(e) => setFilterContentType(e.target.value)}
            />
          </div>
          {showTenantFilter && (
            <div>
              <Label htmlFor="filter-tenant" className="mb-1 block text-xs">
                Tenant ID
              </Label>
              <Input
                id="filter-tenant"
                value={filterTenant}
                placeholder="Admin only"
                onChange={(e) => setFilterTenant(e.target.value)}
              />
            </div>
          )}
        </div>
      </div>

      {/* Table */}
      <div className="rounded-lg border border-surface-border bg-surface-raised">
        <div className="border-b border-surface-border px-4 py-3">
          <h2 className="text-sm font-semibold text-white">Artifacts</h2>
        </div>
        <div className="overflow-x-auto">
          {query.isLoading ? (
            <div className="flex items-center justify-center py-12 text-gray-400">
              Loading…
            </div>
          ) : query.isError ? (
            <div className="flex items-center justify-center py-12 text-red-400">
              Failed to load artifacts.
            </div>
          ) : items.length === 0 ? (
            <div
              data-testid="artifacts-empty-state"
              className="flex flex-col items-center justify-center py-12 text-gray-500"
            >
              <Package size={32} className="mb-2 text-gray-600" />
              <p className="text-sm">No artifacts found.</p>
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-surface-border text-left text-xs text-gray-500">
                  <th className="px-4 py-2 font-medium">Created</th>
                  <th className="px-4 py-2 font-medium">Type</th>
                  <th className="px-4 py-2 font-medium text-right">Size</th>
                  <th className="px-4 py-2 font-medium">Run</th>
                  <th className="px-4 py-2 font-medium">Hash</th>
                </tr>
              </thead>
              <tbody>
                {items.map((a) => {
                  const Icon = pickIcon(a.content_type);
                  return (
                    <tr
                      key={a.id}
                      data-testid={`artifact-row-${a.id}`}
                      onClick={() => setSelectedId(a.id)}
                      className="cursor-pointer border-b border-surface-border hover:bg-white/5"
                    >
                      <td className="px-4 py-2 text-gray-400">
                        {new Date(a.created_at).toLocaleString()}
                      </td>
                      <td className="px-4 py-2">
                        <span className="inline-flex items-center gap-1.5 text-gray-200">
                          <Icon size={12} className="text-gray-400" />
                          {a.content_type}
                        </span>
                      </td>
                      <td className="px-4 py-2 text-right text-gray-300">
                        {formatBytes(a.size_bytes)}
                      </td>
                      <td className="px-4 py-2 font-mono text-xs text-gray-400">
                        {a.run_id ? shortId(a.run_id) : "—"}
                      </td>
                      <td className="px-4 py-2 font-mono text-xs text-gray-400">
                        {a.content_hash
                          ? `${a.content_hash.slice(0, 10)}…`
                          : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
        {/* Pagination */}
        {(items.length > 0 || cursor) && (
          <div className="flex items-center justify-between border-t border-surface-border px-4 py-3 text-xs text-gray-400">
            <span>{items.length} on this page</span>
            <div className="flex gap-2">
              <Button
                size="sm"
                variant="outline"
                disabled={!cursor}
                onClick={() => setCursor(undefined)}
              >
                First
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={!nextCursor}
                onClick={() => nextCursor && setCursor(nextCursor)}
              >
                Next
              </Button>
            </div>
          </div>
        )}
      </div>

      {selectedId && (
        <ArtifactPreview
          artifactId={selectedId}
          onClose={() => setSelectedId(null)}
          canDelete={canDelete}
        />
      )}
    </div>
  );
}
