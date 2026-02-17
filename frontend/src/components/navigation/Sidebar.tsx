import { NavLink } from "react-router-dom";
import { cn } from "@/utils/cn";
import { useAuth } from "@/providers/auth-provider";
import {
  LayoutDashboard,
  Blocks,
  LayoutTemplate,
  Play,
  GitBranch,
  GitFork,
  Plug,
  DollarSign,
  Shield,
  ShieldCheck,
  Radar,
  Store,
  Building2,
  Rocket,
  Users,
  KeyRound,
  ClipboardList,
  Settings,
  ChevronLeft,
  ChevronRight,
  type LucideIcon,
} from "lucide-react";

// ─── Types ───────────────────────────────────────────────────────────

interface NavItem {
  label: string;
  path: string;
  icon: LucideIcon;
  /** Permission string required to see this item */
  permission?: string;
  /** Role required to see this item */
  role?: string;
}

interface NavSection {
  title: string;
  items: NavItem[];
  /** If set, the entire section requires this role */
  role?: string;
}

// ─── Navigation Config ──────────────────────────────────────────────

const navSections: NavSection[] = [
  {
    title: "CORE",
    items: [
      { label: "Dashboard", path: "/", icon: LayoutDashboard },
      { label: "Agents", path: "/agents", icon: Blocks },
      { label: "Templates", path: "/templates", icon: LayoutTemplate },
      { label: "Marketplace", path: "/marketplace", icon: Store },
    ],
  },
  {
    title: "OPERATIONS",
    items: [
      { label: "Executions", path: "/executions", icon: Play },
      { label: "Workflows", path: "/workflows", icon: GitBranch },
      { label: "Model Router", path: "/router", icon: GitFork },
      { label: "Connectors", path: "/connectors", icon: Plug },
      { label: "Lifecycle", path: "/lifecycle", icon: Rocket },
      { label: "Cost", path: "/cost", icon: DollarSign },
    ],
  },
  {
    title: "SECURITY",
    items: [
      { label: "DLP", path: "/dlp", icon: Shield },
      { label: "Governance", path: "/governance", icon: ShieldCheck },
      { label: "SentinelScan", path: "/sentinelscan", icon: Radar },
      { label: "Tenants", path: "/tenants", icon: Building2 },
      { label: "SSO", path: "/sso", icon: KeyRound },
    ],
  },
  {
    title: "ADMIN",
    role: "admin",
    items: [
      { label: "Users", path: "/admin/users", icon: Users, role: "admin" },
      { label: "Secrets", path: "/admin/secrets", icon: KeyRound, role: "admin" },
      { label: "Audit Log", path: "/admin/audit", icon: ClipboardList, role: "admin" },
      { label: "Settings", path: "/settings", icon: Settings },
    ],
  },
];

// ─── Component ───────────────────────────────────────────────────────

interface SidebarProps {
  collapsed: boolean;
  onToggle: () => void;
  /** Mobile overlay mode — visible on small screens */
  mobileOpen?: boolean;
  onMobileClose?: () => void;
}

export function Sidebar({
  collapsed,
  onToggle,
  mobileOpen,
  onMobileClose,
}: SidebarProps) {
  const { hasRole, hasPermission } = useAuth();

  function isItemVisible(item: NavItem): boolean {
    if (item.role && !hasRole(item.role)) return false;
    if (item.permission && !hasPermission(item.permission)) return false;
    return true;
  }

  function isSectionVisible(section: NavSection): boolean {
    if (section.role && !hasRole(section.role)) return false;
    return section.items.some(isItemVisible);
  }

  const sidebarContent = (
    <aside
      className={cn(
        "flex h-full flex-col border-r border-white/10 bg-[#0f1117] transition-all duration-200",
        collapsed ? "w-16" : "w-60",
      )}
    >
      {/* Logo */}
      <div className="flex h-14 items-center justify-between border-b border-white/10 px-4">
        {!collapsed && (
          <span className="text-lg font-bold tracking-wide text-purple-400">
            Archon
          </span>
        )}
        <button
          onClick={onToggle}
          className="rounded p-1 text-gray-400 hover:bg-white/10 hover:text-white"
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {collapsed ? <ChevronRight size={18} /> : <ChevronLeft size={18} />}
        </button>
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto px-2 py-3" aria-label="Main navigation">
        {navSections.filter(isSectionVisible).map((section) => (
          <div key={section.title} className="mb-4">
            {!collapsed && (
              <p className="mb-1 px-2 text-[10px] font-semibold uppercase tracking-widest text-gray-500">
                {section.title}
              </p>
            )}
            <ul className="space-y-0.5">
              {section.items.filter(isItemVisible).map((item) => (
                <li key={item.path}>
                  <NavLink
                    to={item.path}
                    end={item.path === "/"}
                    onClick={onMobileClose}
                    className={({ isActive }) =>
                      cn(
                        "flex items-center gap-3 rounded-md px-2 py-1.5 text-sm font-medium transition-colors",
                        collapsed && "justify-center",
                        isActive
                          ? "bg-purple-600/20 text-purple-400"
                          : "text-gray-400 hover:bg-white/5 hover:text-white",
                      )
                    }
                    title={collapsed ? item.label : undefined}
                  >
                    <item.icon size={18} aria-hidden="true" />
                    {!collapsed && <span>{item.label}</span>}
                  </NavLink>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>
    </aside>
  );

  return (
    <>
      {/* Desktop sidebar */}
      <div className="hidden md:block">{sidebarContent}</div>

      {/* Mobile overlay */}
      {mobileOpen && (
        <div className="fixed inset-0 z-40 md:hidden">
          <div
            className="absolute inset-0 bg-black/50"
            onClick={onMobileClose}
            aria-hidden="true"
          />
          <div className="relative z-50">{sidebarContent}</div>
        </div>
      )}
    </>
  );
}
