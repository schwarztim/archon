import { useState } from "react";
import { Copy, Check } from "lucide-react";
import { cn } from "@/utils/cn";

// ── Types ────────────────────────────────────────────────────────────

interface CodeEditorProps {
  code: string;
  language?: string;
  title?: string;
  readOnly?: boolean;
  onChange?: (code: string) => void;
}

// ── Component ────────────────────────────────────────────────────────

export function CodeEditor({
  code,
  language = "text",
  title,
  readOnly = true,
  onChange,
}: CodeEditorProps) {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    await navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  const lines = code.split("\n");

  return (
    <div className="overflow-hidden rounded-lg border border-[#2a2d37]">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-[#2a2d37] bg-[#0f1117] px-4 py-2">
        <span className="text-xs text-gray-400">
          {title ?? language}
        </span>
        <button
          onClick={handleCopy}
          className="flex items-center gap-1 rounded px-2 py-0.5 text-xs text-gray-400 hover:bg-white/10 hover:text-white"
        >
          {copied ? <Check size={12} /> : <Copy size={12} />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>

      {/* Code area */}
      {readOnly ? (
        <div className="overflow-x-auto bg-[#0a0c10] p-4 font-mono text-sm leading-relaxed">
          {lines.map((line, i) => (
            <div key={i} className="flex">
              <span className="mr-4 inline-block w-8 select-none text-right text-gray-600">
                {i + 1}
              </span>
              <span className="text-gray-300">{line || "\u00A0"}</span>
            </div>
          ))}
        </div>
      ) : (
        <textarea
          className={cn(
            "w-full bg-[#0a0c10] p-4 font-mono text-sm leading-relaxed text-gray-300",
            "resize-y focus:outline-none",
          )}
          value={code}
          rows={Math.max(lines.length, 5)}
          onChange={(e) => onChange?.(e.target.value)}
          spellCheck={false}
        />
      )}
    </div>
  );
}
