import { useState } from "react";
import { Settings, Play, CheckCircle2, AlertTriangle, Plus, X } from "lucide-react";
import { Button } from "@/components/ui/Button";

interface CustomRegexFormProps {
  onAdd: (name: string, pattern: string) => void;
  existingPatterns?: Record<string, string>;
}

export function CustomRegexForm({ onAdd, existingPatterns = {} }: CustomRegexFormProps) {
  const [name, setName] = useState("");
  const [pattern, setPattern] = useState("");
  const [testText, setTestText] = useState("");
  const [testResult, setTestResult] = useState<{ matches: string[]; valid: boolean } | null>(null);
  const [error, setError] = useState<string | null>(null);

  function handleTest() {
    setError(null);
    setTestResult(null);
    if (!pattern.trim()) {
      setError("Enter a regex pattern");
      return;
    }
    try {
      const re = new RegExp(pattern, "g");
      const matches = testText.match(re) ?? [];
      setTestResult({ matches, valid: true });
    } catch (e) {
      setError(`Invalid regex: ${e instanceof Error ? e.message : "unknown error"}`);
      setTestResult({ matches: [], valid: false });
    }
  }

  function handleAdd() {
    if (!name.trim() || !pattern.trim()) return;
    // Validate regex
    try {
      new RegExp(pattern);
    } catch {
      setError("Fix the regex pattern before adding");
      return;
    }
    onAdd(name, pattern);
    setName("");
    setPattern("");
    setTestText("");
    setTestResult(null);
    setError(null);
  }

  const existingEntries = Object.entries(existingPatterns);

  return (
    <div className="rounded-lg border border-[#2a2d37] bg-[#0f1117] p-4">
      <div className="mb-3 flex items-center gap-2">
        <Settings size={14} className="text-purple-400" />
        <h4 className="text-xs font-semibold text-white">Custom Regex Detector</h4>
      </div>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <div>
          <label className="mb-1 block text-[10px] text-gray-500 uppercase">Pattern Name</label>
          <input
            className="w-full rounded-md border border-[#2a2d37] bg-white/5 px-3 py-1.5 text-sm text-gray-200 placeholder-gray-600 focus:border-purple-500 focus:outline-none"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. internal_id"
          />
        </div>
        <div>
          <label className="mb-1 block text-[10px] text-gray-500 uppercase">Regex Pattern</label>
          <input
            className="w-full rounded-md border border-[#2a2d37] bg-white/5 px-3 py-1.5 font-mono text-sm text-gray-200 placeholder-gray-600 focus:border-purple-500 focus:outline-none"
            value={pattern}
            onChange={(e) => { setPattern(e.target.value); setTestResult(null); }}
            placeholder="e.g. INT-\d{6}"
          />
        </div>
      </div>

      {/* Test preview */}
      <div className="mt-3">
        <label className="mb-1 block text-[10px] text-gray-500 uppercase">Test Text (preview)</label>
        <div className="flex gap-2">
          <input
            className="flex-1 rounded-md border border-[#2a2d37] bg-white/5 px-3 py-1.5 text-sm text-gray-200 placeholder-gray-600 focus:border-purple-500 focus:outline-none"
            value={testText}
            onChange={(e) => { setTestText(e.target.value); setTestResult(null); }}
            placeholder="Paste sample text to test..."
          />
          <Button size="sm" variant="secondary" onClick={handleTest} disabled={!pattern.trim()}>
            <Play size={12} className="mr-1" /> Test
          </Button>
        </div>
      </div>

      {/* Test results */}
      {testResult && (
        <div className={`mt-2 rounded border p-2 text-xs ${
          testResult.matches.length > 0
            ? "border-green-500/30 bg-green-500/10 text-green-400"
            : "border-yellow-500/30 bg-yellow-500/10 text-yellow-400"
        }`}>
          {testResult.matches.length > 0 ? (
            <div className="flex items-center gap-2">
              <CheckCircle2 size={12} />
              <span>{testResult.matches.length} match{testResult.matches.length > 1 ? "es" : ""}:</span>
              {testResult.matches.slice(0, 5).map((m, i) => (
                <code key={i} className="rounded bg-white/10 px-1">{m}</code>
              ))}
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <AlertTriangle size={12} />
              <span>No matches found in test text</span>
            </div>
          )}
        </div>
      )}

      {error && (
        <div className="mt-2 rounded border border-red-500/30 bg-red-500/10 p-2 text-xs text-red-400">
          {error}
        </div>
      )}

      {/* Add button */}
      <div className="mt-3 flex items-center justify-between">
        <Button
          size="sm"
          onClick={handleAdd}
          disabled={!name.trim() || !pattern.trim()}
        >
          <Plus size={12} className="mr-1" /> Add Custom Detector
        </Button>
      </div>

      {/* Existing custom patterns */}
      {existingEntries.length > 0 && (
        <div className="mt-3 space-y-1">
          <span className="text-[10px] text-gray-500 uppercase">Active Custom Patterns</span>
          {existingEntries.map(([pName, pRegex]) => (
            <div key={pName} className="flex items-center gap-2 rounded bg-white/5 px-2 py-1 text-xs">
              <Settings size={10} className="text-gray-500" />
              <span className="font-medium text-white">{pName}</span>
              <code className="flex-1 truncate text-gray-500">{pRegex}</code>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
