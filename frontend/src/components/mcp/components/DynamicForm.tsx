import { useState } from "react";
import { Button } from "@/components/ui/Button";

// ── Types ────────────────────────────────────────────────────────────

interface FieldDef {
  name: string;
  label: string;
  type: "text" | "number" | "email" | "select" | "textarea" | "checkbox";
  required?: boolean;
  placeholder?: string;
  options?: { label: string; value: string }[];
  defaultValue?: string | number | boolean;
}

interface DynamicFormProps {
  title?: string;
  fields: FieldDef[];
  submitLabel?: string;
  onSubmit: (values: Record<string, unknown>) => void;
  onAction?: (action: string, payload: Record<string, unknown>) => void;
}

// ── Component ────────────────────────────────────────────────────────

export function DynamicForm({
  title,
  fields,
  submitLabel = "Submit",
  onSubmit,
  onAction,
}: DynamicFormProps) {
  const [values, setValues] = useState<Record<string, unknown>>(() => {
    const init: Record<string, unknown> = {};
    for (const f of fields) {
      init[f.name] = f.defaultValue ?? (f.type === "checkbox" ? false : "");
    }
    return init;
  });
  const [errors, setErrors] = useState<Record<string, string>>({});

  function validate(): boolean {
    const errs: Record<string, string> = {};
    for (const f of fields) {
      if (f.required && !values[f.name] && values[f.name] !== 0) {
        errs[f.name] = `${f.label} is required`;
      }
      if (f.type === "email" && values[f.name]) {
        const v = String(values[f.name]);
        if (!v.includes("@")) errs[f.name] = "Invalid email";
      }
    }
    setErrors(errs);
    return Object.keys(errs).length === 0;
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!validate()) return;
    onSubmit(values);
    onAction?.("form_submit", values);
  }

  function set(name: string, value: unknown) {
    setValues((prev) => ({ ...prev, [name]: value }));
    setErrors((prev) => {
      const next = { ...prev };
      delete next[name];
      return next;
    });
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="space-y-4 rounded-lg border border-[#2a2d37] bg-[#0f1117] p-4"
    >
      {title && (
        <h4 className="mb-2 text-sm font-semibold text-white">{title}</h4>
      )}

      {fields.map((f) => (
        <div key={f.name}>
          <label className="mb-1 block text-xs font-medium text-gray-400">
            {f.label}
            {f.required && <span className="ml-0.5 text-red-400">*</span>}
          </label>

          {f.type === "textarea" ? (
            <textarea
              className="w-full rounded-md border border-[#2a2d37] bg-[#1a1d27] px-3 py-1.5 text-sm text-gray-200 placeholder-gray-600 focus:border-purple-500 focus:outline-none"
              placeholder={f.placeholder}
              rows={3}
              value={String(values[f.name] ?? "")}
              onChange={(e) => set(f.name, e.target.value)}
            />
          ) : f.type === "select" ? (
            <select
              className="w-full rounded-md border border-[#2a2d37] bg-[#1a1d27] px-3 py-1.5 text-sm text-gray-200 focus:border-purple-500 focus:outline-none"
              value={String(values[f.name] ?? "")}
              onChange={(e) => set(f.name, e.target.value)}
            >
              <option value="">Select…</option>
              {f.options?.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          ) : f.type === "checkbox" ? (
            <input
              type="checkbox"
              className="h-4 w-4 rounded border-gray-600 bg-[#1a1d27] text-purple-500 focus:ring-purple-500"
              checked={Boolean(values[f.name])}
              onChange={(e) => set(f.name, e.target.checked)}
            />
          ) : (
            <input
              type={f.type}
              className="w-full rounded-md border border-[#2a2d37] bg-[#1a1d27] px-3 py-1.5 text-sm text-gray-200 placeholder-gray-600 focus:border-purple-500 focus:outline-none"
              placeholder={f.placeholder}
              value={String(values[f.name] ?? "")}
              onChange={(e) =>
                set(
                  f.name,
                  f.type === "number" ? Number(e.target.value) : e.target.value,
                )
              }
            />
          )}

          {errors[f.name] && (
            <p className="mt-1 text-xs text-red-400">{errors[f.name]}</p>
          )}
        </div>
      ))}

      <Button type="submit" size="sm">
        {submitLabel}
      </Button>
    </form>
  );
}
