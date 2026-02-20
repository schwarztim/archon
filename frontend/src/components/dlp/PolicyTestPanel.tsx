import { useState } from "react";
import {
  Search,
  Play,
  Loader2,
  AlertTriangle,
  CheckCircle2,
  Shield,
  Clock,
  Eye,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import { apiPost } from "@/api/client";
import type { ManualScanResult } from "@/api/dlp";

interface PolicyTestPanelProps {
  policies: Array<{ id: string; name: string }>;
}

const SAMPLE_TEXTS = [
  "SSN: 123-45-6789, CC: 4111-1111-1111-1111",
  "Email: john@example.com, Phone: (555) 123-4567",
  "API Key: AKIAIOSFODNN7EXAMPLE, Password: s3cret123!",
  "JWT: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
];

function severityBadge(severity: string) {
  const styles: Record<string, string> = {
    critical: "bg-red-600/20 text-red-300",
    high: "bg-red-500/20 text-red-400",
    medium: "bg-yellow-500/20 text-yellow-400",
    low: "bg-green-500/20 text-green-400",
  };
  return (
    <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${styles[severity] ?? styles.medium}`}>
      {severity}
    </span>
  );
}

function actionBadge(action: string) {
  const styles: Record<string, string> = {
    block: "bg-red-500/20 text-red-400",
    redact: "bg-purple-500/20 text-purple-400",
    allow: "bg-green-500/20 text-green-400",
    log: "bg-gray-500/20 text-gray-400",
    alert: "bg-yellow-500/20 text-yellow-400",
  };
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${styles[action] ?? styles.allow}`}>
      {action}
    </span>
  );
}

export function PolicyTestPanel({ policies }: PolicyTestPanelProps) {
  const [content, setContent] = useState("");
  const [selectedPolicy, setSelectedPolicy] = useState("");
  const [scanning, setScanning] = useState(false);
  const [result, setResult] = useState<ManualScanResult | null>(null);
  const [showRedacted, setShowRedacted] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleScan() {
    if (!content.trim()) return;
    setScanning(true);
    setResult(null);
    setError(null);
    try {
      const body: Record<string, unknown> = { content };
      if (selectedPolicy) body.policy_id = selectedPolicy;
      const res = await apiPost<ManualScanResult>("/api/v1/dlp/scan/test", body);
      setResult(res.data);
    } catch {
      setError("Scan failed. Check connection and try again.");
    } finally {
      setScanning(false);
    }
  }

  function insertSample(idx: number) {
    setContent(SAMPLE_TEXTS[idx] ?? "");
    setResult(null);
  }

  // Highlight detections in the content
  function renderHighlighted(): React.ReactNode {
    if (!result || result.detections.length === 0) return content;

    const sorted = [...result.detections].sort((a, b) => a.position[0] - b.position[0]);
    const parts: React.ReactNode[] = [];
    let cursor = 0;

    sorted.forEach((det, i) => {
      const [start, end] = det.position;
      if (start > cursor) {
        parts.push(<span key={`t-${i}`}>{content.slice(cursor, start)}</span>);
      }
      parts.push(
        <span
          key={`d-${i}`}
          className="relative inline-block rounded bg-red-500/20 px-0.5 text-red-300"
          title={`${det.type} (${Math.round(det.confidence * 100)}%)`}
        >
          {content.slice(start, end)}
          <span className="ml-1 rounded bg-red-500/30 px-1 text-[9px] font-medium uppercase text-red-400">
            {det.type}
          </span>
        </span>,
      );
      cursor = end;
    });
    if (cursor < content.length) {
      parts.push(<span key="tail">{content.slice(cursor)}</span>);
    }
    return parts;
  }

  return (
    <div className="rounded-lg border border-[#2a2d37] bg-[#1a1d27]">
      <div className="border-b border-[#2a2d37] px-4 py-3">
        <div className="flex items-center gap-2">
          <Search size={16} className="text-purple-400" />
          <h2 className="text-sm font-semibold text-white">Policy Test Scanner</h2>
        </div>
        <p className="mt-1 text-xs text-gray-500">
          Paste text to test DLP detection. See highlighted findings with type labels and actions.
        </p>
      </div>

      <div className="p-4">
        {/* Sample text buttons */}
        <div className="mb-3 flex flex-wrap gap-2">
          <span className="text-xs text-gray-500">Quick samples:</span>
          {["SSN + CC", "Email + Phone", "API Keys", "JWT Token"].map((label, i) => (
            <button
              key={label}
              type="button"
              onClick={() => insertSample(i)}
              className="rounded border border-[#2a2d37] bg-white/5 px-2 py-0.5 text-[10px] text-gray-400 hover:border-purple-500/50 hover:text-white"
            >
              {label}
            </button>
          ))}
        </div>

        {/* Input */}
        <textarea
          className="mb-3 w-full rounded-md border border-[#2a2d37] bg-[#0f1117] p-3 text-sm text-gray-200 placeholder-gray-600 focus:border-purple-500 focus:outline-none font-mono"
          rows={5}
          placeholder="Paste text to scan for sensitive data..."
          value={content}
          onChange={(e) => { setContent(e.target.value); setResult(null); }}
        />

        {/* Controls */}
        <div className="flex items-center gap-2">
          {policies.length > 0 && (
            <select
              className="h-8 rounded-md border border-[#2a2d37] bg-[#0f1117] px-2 text-xs text-white"
              value={selectedPolicy}
              onChange={(e) => setSelectedPolicy(e.target.value)}
            >
              <option value="">All detectors</option>
              {policies.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          )}
          <Button size="sm" onClick={handleScan} disabled={scanning || !content.trim()}>
            {scanning ? <Loader2 size={14} className="mr-1.5 animate-spin" /> : <Play size={14} className="mr-1.5" />}
            Scan
          </Button>
        </div>

        {error && (
          <div className="mt-3 rounded border border-red-500/30 bg-red-500/10 p-2 text-xs text-red-400">{error}</div>
        )}

        {/* Results */}
        {result && (
          <div className="mt-4 space-y-4">
            {/* Summary bar */}
            <div className="flex items-center gap-4 rounded-lg border border-[#2a2d37] bg-[#0f1117] p-3">
              {result.total_findings > 0 ? (
                <AlertTriangle size={18} className="shrink-0 text-orange-400" />
              ) : (
                <CheckCircle2 size={18} className="shrink-0 text-green-400" />
              )}
              <div className="flex-1">
                <span className="text-sm font-medium text-white">
                  {result.total_findings > 0
                    ? `${result.total_findings} detection${result.total_findings > 1 ? "s" : ""} found`
                    : "No sensitive data detected"}
                </span>
              </div>
              <div className="flex items-center gap-2">
                {actionBadge(result.action)}
                <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                  result.risk_level === "critical" || result.risk_level === "high"
                    ? "bg-red-500/20 text-red-400"
                    : result.risk_level === "medium"
                      ? "bg-yellow-500/20 text-yellow-400"
                      : "bg-green-500/20 text-green-400"
                }`}>
                  {result.risk_level}
                </span>
                <span className="flex items-center gap-1 text-xs text-gray-500">
                  <Clock size={10} />
                  {result.processing_time_ms.toFixed(1)}ms
                </span>
              </div>
            </div>

            {/* Highlighted content */}
            {result.total_findings > 0 && (
              <div>
                <div className="mb-2 flex items-center justify-between">
                  <span className="text-xs font-medium text-gray-400">Highlighted Detections</span>
                  <button
                    type="button"
                    onClick={() => setShowRedacted(!showRedacted)}
                    className="flex items-center gap-1 text-xs text-purple-400 hover:text-purple-300"
                  >
                    <Eye size={12} />
                    {showRedacted ? "Show Original" : "Show Redacted"}
                  </button>
                </div>
                <div className="rounded-lg border border-[#2a2d37] bg-[#0f1117] p-3 font-mono text-sm leading-relaxed text-gray-300 whitespace-pre-wrap">
                  {showRedacted ? result.redacted_text : renderHighlighted()}
                </div>
              </div>
            )}

            {/* Detection details table */}
            {result.detections.length > 0 && (
              <div>
                <span className="mb-2 block text-xs font-medium text-gray-400">Detection Details</span>
                <div className="space-y-1.5">
                  {result.detections.map((det, i) => (
                    <div
                      key={i}
                      className="flex items-center gap-3 rounded border border-[#2a2d37] bg-white/5 px-3 py-2 text-sm"
                    >
                      <Shield size={14} className="shrink-0 text-purple-400" />
                      <span className="rounded bg-purple-500/20 px-1.5 py-0.5 text-xs font-medium text-purple-300">
                        {det.type}
                      </span>
                      <code className="flex-1 truncate text-gray-400">{det.preview}</code>
                      {severityBadge(det.severity)}
                      <span className="text-xs text-gray-500">
                        {Math.round(det.confidence * 100)}%
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
