import { useState, useCallback } from "react";
import { X } from "lucide-react";

// ─── Types ───────────────────────────────────────────────────────────

export interface IdentityData {
  name: string;
  description: string;
  icon: string;
  tags: string[];
  group_id: string;
}

interface IdentityStepProps {
  data: IdentityData;
  onChange: (data: IdentityData) => void;
}

// ─── Constants ───────────────────────────────────────────────────────

const ICON_OPTIONS = ["🤖", "🧠", "⚡", "🔧", "📊", "🎯", "💡", "🚀", "🔍", "📝", "🛡️", "🌐"];

const GROUP_OPTIONS = [
  { value: "", label: "No group" },
  { value: "customer-support", label: "Customer Support" },
  { value: "engineering", label: "Engineering" },
  { value: "sales", label: "Sales" },
  { value: "analytics", label: "Analytics" },
  { value: "operations", label: "Operations" },
];

const inputClass =
  "w-full rounded-lg border border-[#2a2d37] bg-[#1a1d27] px-3 py-2 text-sm text-white placeholder-gray-500 focus:border-purple-500 focus:outline-none";
const labelClass = "mb-1 block text-xs font-medium text-gray-400";

// ─── Component ───────────────────────────────────────────────────────

export function IdentityStep({ data, onChange }: IdentityStepProps) {
  const [tagInput, setTagInput] = useState("");

  const addTag = useCallback(() => {
    const t = tagInput.trim().toLowerCase();
    if (t && !data.tags.includes(t)) {
      onChange({ ...data, tags: [...data.tags, t] });
    }
    setTagInput("");
  }, [tagInput, data, onChange]);

  return (
    <div className="space-y-4">
      {/* Name */}
      <div>
        <label className={labelClass}>Name *</label>
        <input
          type="text"
          required
          value={data.name}
          onChange={(e) => onChange({ ...data, name: e.target.value })}
          className={inputClass}
          placeholder="My Agent"
        />
      </div>

      {/* Description */}
      <div>
        <label className={labelClass}>Description</label>
        <textarea
          value={data.description}
          onChange={(e) => onChange({ ...data, description: e.target.value })}
          rows={3}
          className={inputClass}
          placeholder="What does this agent do?"
        />
      </div>

      {/* Icon Picker */}
      <div>
        <label className={labelClass}>Icon</label>
        <div className="flex flex-wrap gap-2">
          {ICON_OPTIONS.map((ico) => (
            <button
              key={ico}
              type="button"
              onClick={() => onChange({ ...data, icon: ico })}
              className={`flex h-10 w-10 items-center justify-center rounded-lg border text-lg ${
                data.icon === ico
                  ? "border-purple-500 bg-purple-500/20"
                  : "border-[#2a2d37] bg-[#1a1d27] hover:border-gray-600"
              }`}
            >
              {ico}
            </button>
          ))}
        </div>
      </div>

      {/* Tags */}
      <div>
        <label className={labelClass}>Tags</label>
        <div className="mb-2 flex flex-wrap gap-1">
          {data.tags.map((t) => (
            <span
              key={t}
              className="flex items-center gap-1 rounded-full bg-purple-500/20 px-2 py-0.5 text-xs text-purple-300"
            >
              {t}
              <button
                type="button"
                onClick={() => onChange({ ...data, tags: data.tags.filter((x) => x !== t) })}
                className="hover:text-white"
              >
                <X size={10} />
              </button>
            </span>
          ))}
        </div>
        <div className="flex gap-2">
          <input
            type="text"
            value={tagInput}
            onChange={(e) => setTagInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") { e.preventDefault(); addTag(); }
            }}
            className={`flex-1 ${inputClass}`}
            placeholder="Add tag..."
          />
          <button
            type="button"
            onClick={addTag}
            className="rounded-lg border border-[#2a2d37] px-3 py-2 text-sm text-gray-400 hover:bg-white/5"
          >
            Add
          </button>
        </div>
      </div>

      {/* Group */}
      <div>
        <label className={labelClass}>Group</label>
        <select
          value={data.group_id}
          onChange={(e) => onChange({ ...data, group_id: e.target.value })}
          className={inputClass}
        >
          {GROUP_OPTIONS.map((g) => (
            <option key={g.value} value={g.value}>{g.label}</option>
          ))}
        </select>
      </div>
    </div>
  );
}
