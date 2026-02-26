import { useState, useMemo } from "react";
import {
  Search,
} from "lucide-react";
import { DetectorCard } from "@/components/dlp/DetectorCard";

export interface DetectorInfo {
  id: string;
  name: string;
  category: string;
  sensitivity: string;
  description?: string;
  icon?: string;
}

const DETECTOR_DESCRIPTIONS: Record<string, string> = {
  ssn: "US Social Security Numbers (XXX-XX-XXXX)",
  credit_card: "Visa, Mastercard, Amex with Luhn validation",
  email: "Email addresses in standard format",
  phone: "US and international phone numbers",
  address: "Physical street addresses and postal codes",
  passport: "Passport numbers from various countries",
  drivers_license: "Driver's license numbers (US formats)",
  api_key: "API keys from major cloud providers",
  password: "Passwords and credential strings",
  jwt_token: "JSON Web Tokens (Bearer tokens)",
  aws_key: "AWS access key IDs and secret keys",
  private_key: "RSA, EC, DSA, PGP private key blocks",
  oauth_token: "OAuth bearer and refresh tokens",
  person_name: "Person names and identifiers",
  dob: "Dates of birth in common formats",
  ip_address: "IPv4 and IPv6 addresses",
  medical_record: "Medical record and health IDs",
  bank_account: "Bank account and routing numbers",
  custom: "User-defined regex pattern with test preview",
};

// Fallback detectors when the API is not available
const FALLBACK_DETECTORS: DetectorInfo[] = [
  { id: "ssn", name: "Social Security Number", category: "pii", sensitivity: "high" },
  { id: "credit_card", name: "Credit Card", category: "pii", sensitivity: "high" },
  { id: "email", name: "Email Address", category: "pii", sensitivity: "medium" },
  { id: "phone", name: "Phone Number", category: "pii", sensitivity: "medium" },
  { id: "address", name: "Street Address", category: "pii", sensitivity: "medium" },
  { id: "passport", name: "Passport Number", category: "pii", sensitivity: "high" },
  { id: "drivers_license", name: "Driver's License", category: "pii", sensitivity: "high" },
  { id: "api_key", name: "API Key", category: "secret", sensitivity: "high" },
  { id: "password", name: "Password", category: "secret", sensitivity: "high" },
  { id: "jwt_token", name: "JWT Token", category: "secret", sensitivity: "high" },
  { id: "aws_key", name: "AWS Access Key", category: "secret", sensitivity: "critical" },
  { id: "private_key", name: "Private Key", category: "secret", sensitivity: "critical" },
  { id: "oauth_token", name: "OAuth Token", category: "secret", sensitivity: "high" },
  { id: "person_name", name: "Person Name", category: "pii", sensitivity: "low" },
  { id: "dob", name: "Date of Birth", category: "pii", sensitivity: "medium" },
  { id: "ip_address", name: "IP Address", category: "network", sensitivity: "medium" },
  { id: "medical_record", name: "Medical Record", category: "phi", sensitivity: "high" },
  { id: "bank_account", name: "Bank Account", category: "pii", sensitivity: "high" },
  { id: "custom", name: "Custom Regex", category: "custom", sensitivity: "configurable" },
];

interface DetectorPickerProps {
  selected: string[];
  onChange: (selected: string[]) => void;
  detectors?: DetectorInfo[];
}

export function DetectorPicker({ selected, onChange, detectors }: DetectorPickerProps) {
  const [searchQuery, setSearchQuery] = useState("");
  const [categoryFilter, setCategoryFilter] = useState<string>("all");
  const allDetectors = detectors ?? FALLBACK_DETECTORS;

  const categories = useMemo(() => {
    const cats = new Set(allDetectors.map((d) => d.category));
    return ["all", ...Array.from(cats)];
  }, [allDetectors]);

  const filtered = useMemo(() => {
    const q = searchQuery.toLowerCase();
    const list = allDetectors.filter((d) => {
      const matchesSearch =
        d.name.toLowerCase().includes(q) ||
        d.id.toLowerCase().includes(q) ||
        d.category.toLowerCase().includes(q) ||
        (DETECTOR_DESCRIPTIONS[d.id] ?? "").toLowerCase().includes(q);
      const matchesCategory = categoryFilter === "all" || d.category === categoryFilter;
      return matchesSearch && matchesCategory;
    });
    // Enabled detectors first
    return list.sort((a, b) => {
      const aSelected = selected.includes(a.id) ? 0 : 1;
      const bSelected = selected.includes(b.id) ? 0 : 1;
      return aSelected - bSelected;
    });
  }, [allDetectors, searchQuery, categoryFilter, selected]);

  function toggle(id: string) {
    onChange(
      selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id],
    );
  }

  return (
    <div>
      {/* Search bar + category filter */}
      <div className="mb-3 flex gap-2">
        <div className="relative flex-1">
          <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-500" />
          <input
            type="text"
            className="w-full rounded-md border border-surface-border bg-white/5 py-1.5 pl-8 pr-3 text-sm text-gray-200 placeholder-gray-500 focus:border-purple-500 focus:outline-none"
            placeholder="Search detectors..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </div>
        <select
          className="rounded-md border border-surface-border bg-white/5 px-2 text-xs text-gray-300 focus:border-purple-500 focus:outline-none"
          value={categoryFilter}
          onChange={(e) => setCategoryFilter(e.target.value)}
        >
          {categories.map((cat) => (
            <option key={cat} value={cat}>
              {cat === "all" ? "All Categories" : cat.toUpperCase()}
            </option>
          ))}
        </select>
      </div>

      {/* Selected count */}
      <div className="mb-3 flex items-center justify-between">
        <span className="text-xs text-gray-500">
          {selected.length} of {allDetectors.length} detectors enabled
        </span>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => onChange(allDetectors.map((d) => d.id))}
            className="text-[10px] text-purple-400 hover:text-purple-300"
          >
            Select All
          </button>
          <button
            type="button"
            onClick={() => onChange([])}
            className="text-[10px] text-gray-500 hover:text-gray-400"
          >
            Clear
          </button>
        </div>
      </div>

      {/* Detector card grid */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {filtered.map((det) => (
          <DetectorCard
            key={det.id}
            id={det.id}
            name={det.name}
            description={det.description ?? DETECTOR_DESCRIPTIONS[det.id]}
            category={det.category}
            sensitivity={det.sensitivity}
            isSelected={selected.includes(det.id)}
            onToggle={toggle}
          />
        ))}
      </div>
    </div>
  );
}

export { FALLBACK_DETECTORS };
