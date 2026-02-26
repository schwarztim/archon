import {
  Shield,
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
  Cloud,
  FileLock,
  IdCard,
} from "lucide-react";

/** Maps detector id to a Lucide icon component */
const DETECTOR_ICON_MAP: Record<string, React.ReactNode> = {
  ssn: <Shield size={20} />,
  credit_card: <CreditCard size={20} />,
  email: <Mail size={20} />,
  phone: <Phone size={20} />,
  address: <MapPin size={20} />,
  passport: <BookOpen size={20} />,
  drivers_license: <IdCard size={20} />,
  api_key: <Key size={20} />,
  password: <Lock size={20} />,
  jwt_token: <KeyRound size={20} />,
  aws_key: <Cloud size={20} />,
  private_key: <FileLock size={20} />,
  oauth_token: <KeyRound size={20} />,
  person_name: <User size={20} />,
  dob: <Calendar size={20} />,
  ip_address: <Globe size={20} />,
  medical_record: <Heart size={20} />,
  bank_account: <Landmark size={20} />,
  custom: <Settings size={20} />,
};

const SENSITIVITY_STYLES: Record<string, { label: string; bg: string; dot: string }> = {
  critical: { label: "Critical", bg: "bg-red-600/20 text-red-300", dot: "🔴" },
  high: { label: "High", bg: "bg-red-500/20 text-red-400", dot: "🔴" },
  medium: { label: "Medium", bg: "bg-yellow-500/20 text-yellow-400", dot: "🟡" },
  low: { label: "Low", bg: "bg-green-500/20 text-green-400", dot: "🟢" },
  configurable: { label: "Custom", bg: "bg-gray-500/20 text-gray-400", dot: "⚪" },
};

const CATEGORY_STYLES: Record<string, string> = {
  pii: "bg-blue-500/20 text-blue-400",
  secret: "bg-red-500/20 text-red-400",
  network: "bg-cyan-500/20 text-cyan-400",
  phi: "bg-pink-500/20 text-pink-400",
  custom: "bg-gray-500/20 text-gray-400",
};

interface DetectorCardProps {
  id: string;
  name: string;
  description?: string;
  category: string;
  sensitivity: string;
  isSelected: boolean;
  onToggle: (id: string) => void;
}

export function DetectorCard({
  id,
  name,
  description,
  category,
  sensitivity,
  isSelected,
  onToggle,
}: DetectorCardProps) {
  const sens = SENSITIVITY_STYLES[sensitivity] ?? SENSITIVITY_STYLES.configurable;
  const catStyle = CATEGORY_STYLES[category] ?? CATEGORY_STYLES.custom;

  return (
    <button
      type="button"
      onClick={() => onToggle(id)}
      className={`group relative flex flex-col gap-2 rounded-xl border p-4 text-left transition-all duration-200 ${
        isSelected
          ? "border-purple-500 bg-purple-500/10 shadow-lg shadow-purple-500/10"
          : "border-surface-border bg-surface-raised hover:border-white/20 hover:bg-white/5"
      }`}
    >
      {/* Header: Icon + Toggle */}
      <div className="flex items-start justify-between">
        <span className={`rounded-lg p-2 ${isSelected ? "bg-purple-500/20 text-purple-400" : "bg-white/5 text-gray-500"}`}>
          {DETECTOR_ICON_MAP[id] ?? <Settings size={20} />}
        </span>
        <div className={`h-5 w-9 rounded-full transition-colors ${isSelected ? "bg-purple-500" : "bg-gray-600"}`}>
          <div className={`mt-0.5 h-4 w-4 rounded-full bg-white transition-transform ${isSelected ? "translate-x-4.5 ml-[18px]" : "ml-0.5"}`} />
        </div>
      </div>

      {/* Name */}
      <div className="text-sm font-semibold text-white">{name}</div>

      {/* Description */}
      {description && (
        <p className="text-xs leading-relaxed text-gray-500">{description}</p>
      )}

      {/* Badges: Category + Sensitivity */}
      <div className="mt-auto flex items-center gap-2">
        <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium uppercase ${catStyle}`}>
          {category}
        </span>
        <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${sens?.bg}`}>
          {sens?.dot} {sens?.label}
        </span>
      </div>
    </button>
  );
}
