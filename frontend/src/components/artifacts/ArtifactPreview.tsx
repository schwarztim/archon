/**
 * ArtifactPreview — modal preview for a single artifact.
 *
 * Handles three content-type families:
 *   - text/* and application/*json — render in a syntax-light <pre> block
 *   - image/*                       — inline <img> from a blob URL
 *   - everything else (binary)      — download button + hash advice
 *
 * Always shows a metadata table and a delete button. Delete confirms
 * before firing the mutation. Cross-tenant fetches return 404 from the
 * backend; this component surfaces that as "not found" via the parent.
 */

import { useEffect, useMemo, useState } from "react";
import {
  Download,
  Trash2,
  X,
  FileText,
  Image as ImageIcon,
  Package,
  Loader2,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import {
  useArtifact,
  useArtifactContent,
  useDeleteArtifact,
} from "@/hooks/useArtifacts";
import type { Artifact } from "@/types/artifacts";

interface ArtifactPreviewProps {
  artifactId: string;
  onClose: () => void;
  /** Allow the operator to delete. Defaults to ``true``; the parent should
   *  pass ``false`` for read-only contexts. */
  canDelete?: boolean;
}

function isTextLike(contentType: string): boolean {
  const ct = (contentType || "").toLowerCase();
  return ct.startsWith("text/") || ct.includes("json") || ct.includes("xml");
}

function isImageLike(contentType: string): boolean {
  return (contentType || "").toLowerCase().startsWith("image/");
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KiB`;
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MiB`;
  return `${(n / 1024 / 1024 / 1024).toFixed(2)} GiB`;
}

function shortHash(hash: string): string {
  if (!hash) return "";
  return hash.length > 16 ? `${hash.slice(0, 8)}…${hash.slice(-8)}` : hash;
}

export function ArtifactPreview({
  artifactId,
  onClose,
  canDelete = true,
}: ArtifactPreviewProps) {
  const meta = useArtifact(artifactId);
  const content = useArtifactContent(artifactId);
  const del = useDeleteArtifact();
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [imageUrl, setImageUrl] = useState<string | null>(null);

  // Build a blob URL for image previews; revoke on unmount.
  useEffect(() => {
    if (!meta.data || !content.data) return;
    if (!isImageLike(meta.data.content_type)) return;
    if (!(content.data instanceof Blob)) return;
    const url = URL.createObjectURL(content.data);
    setImageUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [meta.data, content.data]);

  const handleDownload = useMemo(
    () => () => {
      if (!meta.data || !content.data) return;
      const blob =
        content.data instanceof Blob
          ? content.data
          : new Blob([content.data], {
              type: meta.data.content_type || "application/octet-stream",
            });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `artifact-${meta.data.id}`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    },
    [meta.data, content.data],
  );

  async function handleDelete() {
    try {
      await del.mutateAsync(artifactId);
      onClose();
    } catch {
      // The mutation onError surface is owned by the parent's toast; the
      // dialog stays open so the operator can try again.
    }
  }

  const isLoading = meta.isLoading || content.isLoading;
  const hasError = meta.isError || content.isError;
  const a: Artifact | undefined = meta.data;

  if (hasError) {
    return (
      <div
        role="dialog"
        aria-label="Artifact preview"
        className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      >
        <div className="w-full max-w-md rounded-lg border border-surface-border bg-surface-raised p-6">
          <div className="mb-4 flex items-center justify-between">
            <h3 className="text-base font-semibold text-white">
              Artifact not found
            </h3>
            <button
              onClick={onClose}
              aria-label="Close preview"
              className="text-gray-400 hover:text-white"
            >
              <X size={16} />
            </button>
          </div>
          <p className="text-sm text-gray-400">
            This artifact does not exist, has expired, or belongs to a
            different tenant.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div
      role="dialog"
      aria-label="Artifact preview"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
    >
      <div className="flex h-full max-h-[90vh] w-full max-w-4xl flex-col overflow-hidden rounded-lg border border-surface-border bg-surface-raised">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-surface-border px-4 py-3">
          <div className="flex items-center gap-2">
            {a && isTextLike(a.content_type) && (
              <FileText size={14} className="text-gray-400" />
            )}
            {a && isImageLike(a.content_type) && (
              <ImageIcon size={14} className="text-gray-400" />
            )}
            {a && !isTextLike(a.content_type) && !isImageLike(a.content_type) && (
              <Package size={14} className="text-gray-400" />
            )}
            <h3 className="text-sm font-semibold text-white">
              {a ? a.content_type : "Artifact"}
            </h3>
          </div>
          <button
            onClick={onClose}
            aria-label="Close preview"
            className="text-gray-400 hover:text-white"
          >
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-4">
          {isLoading ? (
            <div className="flex items-center justify-center py-12 text-gray-400">
              <Loader2 size={20} className="mr-2 animate-spin" /> Loading…
            </div>
          ) : a && content.data !== undefined ? (
            <>
              {isTextLike(a.content_type) &&
                typeof content.data === "string" && (
                  <pre
                    data-testid="artifact-text-preview"
                    className="max-h-[50vh] overflow-auto rounded-md border border-surface-border bg-black/30 p-3 text-xs text-gray-200"
                  >
                    {content.data}
                  </pre>
                )}
              {isImageLike(a.content_type) && imageUrl && (
                <img
                  data-testid="artifact-image-preview"
                  src={imageUrl}
                  alt="Artifact preview"
                  className="mx-auto max-h-[50vh] rounded-md border border-surface-border"
                />
              )}
              {!isTextLike(a.content_type) && !isImageLike(a.content_type) && (
                <div
                  data-testid="artifact-binary-preview"
                  className="rounded-md border border-surface-border bg-black/30 p-4 text-sm text-gray-400"
                >
                  <p className="mb-2 text-white">
                    Binary content ({formatBytes(a.size_bytes)}).
                  </p>
                  <p className="mb-3 text-xs">
                    Verify the SHA-256 hash after download to ensure
                    integrity:{" "}
                    <code className="rounded bg-black/40 px-1.5 py-0.5 text-[11px] text-gray-200">
                      {a.content_hash}
                    </code>
                  </p>
                  <Button
                    size="sm"
                    onClick={handleDownload}
                    aria-label="Download artifact"
                  >
                    <Download size={14} className="mr-1.5" /> Download
                  </Button>
                </div>
              )}

              {/* Metadata */}
              <table className="mt-4 w-full text-xs">
                <tbody className="divide-y divide-surface-border">
                  <tr>
                    <td className="py-2 pr-4 text-gray-500">ID</td>
                    <td className="py-2 font-mono text-gray-200">{a.id}</td>
                  </tr>
                  <tr>
                    <td className="py-2 pr-4 text-gray-500">Run</td>
                    <td className="py-2 font-mono text-gray-200">
                      {a.run_id ?? "—"}
                    </td>
                  </tr>
                  <tr>
                    <td className="py-2 pr-4 text-gray-500">Step</td>
                    <td className="py-2 font-mono text-gray-200">
                      {a.step_id ?? "—"}
                    </td>
                  </tr>
                  <tr>
                    <td className="py-2 pr-4 text-gray-500">Tenant</td>
                    <td className="py-2 font-mono text-gray-200">
                      {a.tenant_id ?? "—"}
                    </td>
                  </tr>
                  <tr>
                    <td className="py-2 pr-4 text-gray-500">Size</td>
                    <td className="py-2 text-gray-200">
                      {formatBytes(a.size_bytes)}
                    </td>
                  </tr>
                  <tr>
                    <td className="py-2 pr-4 text-gray-500">SHA-256</td>
                    <td className="py-2 font-mono text-gray-200">
                      {shortHash(a.content_hash)}
                    </td>
                  </tr>
                  <tr>
                    <td className="py-2 pr-4 text-gray-500">Created</td>
                    <td className="py-2 text-gray-200">
                      {new Date(a.created_at).toLocaleString()}
                    </td>
                  </tr>
                  {a.expires_at && (
                    <tr>
                      <td className="py-2 pr-4 text-gray-500">Expires</td>
                      <td className="py-2 text-gray-200">
                        {new Date(a.expires_at).toLocaleString()}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </>
          ) : null}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between border-t border-surface-border px-4 py-3">
          <Button
            size="sm"
            variant="outline"
            onClick={handleDownload}
            disabled={!a || content.data === undefined}
          >
            <Download size={14} className="mr-1.5" /> Download
          </Button>
          {canDelete && (
            <div className="flex items-center gap-2">
              {confirmDelete ? (
                <>
                  <span className="text-xs text-red-300">
                    Delete permanently?
                  </span>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => setConfirmDelete(false)}
                  >
                    Cancel
                  </Button>
                  <Button
                    size="sm"
                    variant="destructive"
                    onClick={handleDelete}
                    disabled={del.isPending}
                  >
                    {del.isPending ? (
                      <Loader2 size={14} className="animate-spin" />
                    ) : (
                      <>
                        <Trash2 size={14} className="mr-1.5" /> Confirm delete
                      </>
                    )}
                  </Button>
                </>
              ) : (
                <Button
                  size="sm"
                  variant="destructive"
                  onClick={() => setConfirmDelete(true)}
                  aria-label="Delete artifact"
                >
                  <Trash2 size={14} className="mr-1.5" /> Delete
                </Button>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
