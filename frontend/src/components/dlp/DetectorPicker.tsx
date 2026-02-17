import { useState, useMemo } from "react";
import {
  Search,
  CreditCard,
  Mail,
  Phone,
  MapPin,
  Key,
  Lock,
  KeyRound,
  User,
  Calendar,
  Globe,
  Heart,
  Landmark,
  BookOpen,
  Settings,
  Shield,
} from "lucide-react";

export interface DetectorInfo {
  id: string;
  name: string;
  category: string;
  sensitivity: string;
}

// Icon mapping for each detector type
const DETECTOR_ICONS: Record<string, React.ReactNode> = {
  ssn: <Shield size={18} />,
  credit_card: <CreditCard size={18} />,
  email: <Mail size={18} />,
  phone: <Phone size={18} />,
  address: <MapPin size={18} />,
  api_key: <Key size={18} />,
  password: <Lock size={18} />,
  oauth_token: <KeyRound size={18} />,
  person_name: <User size={18} />,
  dob: <Calendar size={18} />,
  ip_address: <Globe size={18} />,
  medical_record: <Heart size={18} />,
  bank_account: <Landmark size={18} />,
  passport: <BookOpen size={18} />,
  custom: <Settings size={18} />,
};

const DETECTOR_DESCRIPTIONS: Record<string, string> = {
  ssn: "US Social Security Numbers (XXX-XX-XXXX)",
  credit_card: "Visa, Mastercard, Amex, and other card numbers",
  email: "Email addresses in standard format",
  phone: "Phone numbers in various formats",
  address: "Street addresses and postal codes",
  api_key: "API keys from major cloud providers",
  password: "Passwords and credential strings",
  oauth_token: "OAuth bearer and refresh tokens",
  person_name: "Person names and identifiers",
  dob: "Dates of birth in common formats",
  ip_address: "IPv4 and IPv6 addresses",
  medical_record: "Medical record and health IDs",
  bank_account: "Bank account and routing numbers",
  passport: "Passport numbers from various countries",
  custom: "User-defined regex or pattern",
};

const SENSITIVITY_CONFIG: Record<string, { label: string; color: string; dot: string }> = {
  high: { label: "High", color: "bg-red-500/20 text-red-400", dot: "🔴" },
  medium: { label: "Medium", color: "bg-yellow-500/20 text-yellow-400", dot: "🟡" },
  low: { label: "Low", color: "bg-green-500/20 text-green-400", dot: "🟢" },
  configurable: { label: "Custom", color: "bg-gray-500/20 text-gray-400", dot: "⚪" },
};

// Fallback detectors when the API is not available
const FALLBACK_DETECTORS: DetectorInfo[] = [
  { id: "ssn", name: "Social Security Number", category: "pii", sensitivity: "high" },
  { id: "credit_card", name: "Credit Card", category: "pii", sensitivity: "high" },
  { id: "email", name: "Email Address", category: "pii", sensitivity: "medium" },
  { id: "phone", name: "Phone Number", category: "pii", sensitivity: "medium" },
  { id: "address", name: "Physical Address", category: "pii", sensitivity: "medium" },
  { id: "api_key", name: "API Key", category: "secret", sensitivity: "high" },
  { id: "password", name: "Password", category: "secret", sensitivity: "high" },
  { id: "oauth_token", name: "OAuth Token", category: "secret", sensitivity: "high" },
  { id: "person_name", name: "Person Name", category: "pii", sensitivity: "low" },
  { id: "dob", name: "Date of Birth", category: "pii", sensitivity: "medium" },
  { id: "ip_address", name: "IP Address", category: "network", sensitivity: "medium" },
  { id: "medical_record", name: "Medical Record", category: "phi", sensitivity: "high" },
  { id: "bank_account", name: "Bank Account", category: "pii", sensitivity: "high" },
  { id: "passport", name: "Passport Number", category: "pii", sensitivity: "high" },
  { id: "custom", name: "Custom Pattern", category: "custom", sensitivity: "configurable" },
];

interface DetectorPickerProps {
  selected: string[];
  onChange: (selected: string[]) => void;
  detectors?: DetectorInfo[];
}

export function DetectorPicker({ selected, onChange, detectors }: DetectorPickerProps) {
  const [searchQuery, setSearchQuery] = useState("");
  const allDetectors = detectors ?? FALLBACK_DETECTORS;

  const filtered = useMemo(() => {
    const q = searchQuery.toLowerCase();
    const list = allDetectors.filter(
      (d) =>
        d.name.toLowerCase().includes(q) ||
        d.id.toLowerCase().includes(q) ||
        d.category.toLowerCase().includes(q),
    );
    // Enabled detectors first
    return list.sort((a, b) => {
      const aSelected = selected.includes(a.id) ? 0 : 1;
      const bSelected = selected.includes(b.id) ? 0 : 1;
      return aSelected - bSelected;
    });
  }, [allDetectors, searchQuery, selected]);

  function toggle(id: string) {
    onChange(
      selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id],
    );
  }

  return (
    <div>
      {/* Search bar */}
      <div className="relative mb-3">
        <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-500" />
        <input
          type="text"
          className="w-full rounded-md border border-[#2a2d37] bg-white/5 py-1.5 pl-8 pr-3 text-sm text-gray-200 placeholder-gray-500 focus:border-purple-500 focus:outline-none"
          placeholder="Search detectors..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
        />
      </div>

      {/* Selected count */}
      <div className="mb-2 text-xs text-gray-500">
        {selected.length} of {allDetectors.length} detectors enabled
      </div>

      {/* Detector grid */}
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {filtered.map((det) => {
          const isSelected = selected.includes(det.id);
          const sens = SENSITIVITY_CONFIG[det.sensitivity] ?? SENSITIVITY_CONFIG.configurable;
          return (
            <button
              key={det.id}
              type="button"
              onClick={() => toggle(det.id)}
              className={`flex items-start gap-3 rounded-lg border p-3 text-left transition-colors ${
                isSelected
                  ? "border-purple-500 bg-purple-500/10"
                  : "border-[#2a2d37] bg-white/5 hover:border-white/20"
              }`}
            >
              {/* Icon */}
              <span className={`mt-0.5 shrink-0 ${isSelected ? "text-purple-400" : "text-gray-500"}`}>
                {DETECTOR_ICONS[det.id] ?? <Settings size={18} />}
              </span>

              {/* Info */}
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-white truncate">{det.name}</span>
                  <span className={`inline-block shrink-0 rounded-full px-1.5 py-0.5 text-[10px] font-medium ${sens.color}`}>
                    {sens.dot} {sens.label}
                  </span>
                </div>
                <p className="mt-0.5 text-xs text-gray-500 truncate">
                  {DETECTOR_DESCRIPTIONS[det.id] ?? det.category}
                </p>
              </div>

              {/* Toggle indicator */}
              <div className={`mt-1 h-4 w-7 shrink-0 rounded-full transition-colors ${isSelected ? "bg-purple-500" : "bg-gray-600"}`}>
                <div className={`h-3 w-3 translate-y-0.5 rounded-full bg-white transition-transform ${isSelected ? "translate-x-3.5" : "translate-x-0.5"}`} />
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}

export { FALLBACK_DETECTORS };
