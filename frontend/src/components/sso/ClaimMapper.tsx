import { Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";

export interface ClaimMapping {
  idp_claim: string;
  archon_field: string;
}

const ARCHON_FIELDS = [
  "Email",
  "Username",
  "First Name",
  "Last Name",
  "Groups",
  "Tenant ID",
  "Role",
  "Display Name",
];

interface ClaimMapperProps {
  mappings: ClaimMapping[];
  onChange: (mappings: ClaimMapping[]) => void;
  disabled?: boolean;
}

export function ClaimMapper({ mappings, onChange, disabled }: ClaimMapperProps) {
  function updateRow(index: number, field: keyof ClaimMapping, value: string) {
    const updated = [...mappings];
    updated[index] = { ...updated[index]!, [field]: value };
    onChange(updated);
  }

  function addRow() {
    onChange([...mappings, { idp_claim: "", archon_field: "" }]);
  }

  function removeRow(index: number) {
    onChange(mappings.filter((_, i) => i !== index));
  }

  return (
    <div className="space-y-2">
      <div className="grid grid-cols-[1fr_24px_1fr_32px] items-center gap-2 text-xs font-medium text-gray-500">
        <span>IdP Claim / Attribute</span>
        <span />
        <span>Archon Field</span>
        <span />
      </div>
      {mappings.map((m, i) => (
        <div key={i} className="grid grid-cols-[1fr_24px_1fr_32px] items-center gap-2">
          <Input
            placeholder="e.g. email, preferred_username"
            value={m.idp_claim}
            onChange={(e) => updateRow(i, "idp_claim", e.target.value)}
            disabled={disabled}
            className="h-8 text-xs"
          />
          <span className="text-center text-gray-600">→</span>
          <select
            value={m.archon_field}
            onChange={(e) => updateRow(i, "archon_field", e.target.value)}
            disabled={disabled}
            className="h-8 rounded-md border border-[#2a2d37] bg-[#0f1117] px-2 text-xs text-white dark:bg-[#0f1117]"
          >
            <option value="">Select field…</option>
            {ARCHON_FIELDS.map((f) => (
              <option key={f} value={f}>{f}</option>
            ))}
          </select>
          <Button
            size="icon"
            variant="ghost"
            onClick={() => removeRow(i)}
            disabled={disabled}
            className="h-8 w-8 text-gray-500 hover:text-red-400"
          >
            <Trash2 size={14} />
          </Button>
        </div>
      ))}
      <Button size="sm" variant="outline" onClick={addRow} disabled={disabled} className="mt-1">
        <Plus size={14} className="mr-1.5" />
        Add Mapping
      </Button>
    </div>
  );
}
