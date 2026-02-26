import { useState, useRef, useEffect } from "react";
import { useAuth } from "@/providers/auth-provider";
import { useTheme } from "@/providers/theme-provider";
import { cn } from "@/utils/cn";
import {
  Search,
  Bell,
  User,
  ChevronDown,
  Menu,
  LogOut,
  Settings,
  Building2,
  Sun,
  Moon,
} from "lucide-react";

// ─── Types ───────────────────────────────────────────────────────────

interface TopBarProps {
  onMenuToggle?: () => void;
}

// ─── Component ───────────────────────────────────────────────────────

export function TopBar({ onMenuToggle }: TopBarProps) {
  const { user, logout } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  // Close dropdown on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setUserMenuOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  const initials = user?.name
    ? user.name
        .split(" ")
        .map((n) => n[0])
        .join("")
        .slice(0, 2)
        .toUpperCase()
    : "?";

  return (
    <header className="flex h-14 shrink-0 items-center justify-between border-b border-white/10 bg-surface-base px-4 md:px-6">
      {/* Left: mobile menu + workspace */}
      <div className="flex items-center gap-3">
        {/* Hamburger — mobile only */}
        <button
          onClick={onMenuToggle}
          className="rounded p-1 text-gray-400 hover:bg-white/10 hover:text-white md:hidden"
          aria-label="Toggle menu"
        >
          <Menu size={20} />
        </button>

        {/* Workspace / tenant selector */}
        <button
          className="flex items-center gap-2 rounded-md border border-white/10 bg-white/5 px-3 py-1.5 text-sm text-gray-300 hover:bg-white/10"
          aria-label="Select workspace"
        >
          <Building2 size={14} className="text-purple-400" />
          <span className="hidden sm:inline">{user?.name ?? "Workspace"}</span>
          <ChevronDown size={14} className="text-gray-500" />
        </button>
      </div>

      {/* Right: search, notifications, avatar */}
      <div className="flex items-center gap-3">
        {/* Search trigger */}
        <button
          className="flex items-center gap-2 rounded-md border border-white/10 bg-white/5 px-3 py-1.5 text-sm text-gray-400 hover:bg-white/10"
          aria-label="Search (Cmd+K)"
        >
          <Search size={14} />
          <span className="hidden sm:inline">Search…</span>
          <kbd className="ml-2 hidden rounded border border-white/10 px-1.5 text-[10px] sm:inline">
            ⌘K
          </kbd>
        </button>

        {/* Notification bell */}
        <button
          className="relative rounded p-1.5 text-gray-400 hover:bg-white/10 hover:text-white"
          aria-label="Notifications"
        >
          <Bell size={18} />
        </button>

        {/* Theme toggle */}
        <button
          onClick={toggleTheme}
          className="rounded p-1.5 text-gray-400 hover:bg-white/10 hover:text-white"
          aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
        >
          {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
        </button>

        {/* User avatar dropdown */}
        <div className="relative" ref={menuRef}>
          <button
            onClick={() => setUserMenuOpen((o) => !o)}
            className="flex h-8 w-8 items-center justify-center rounded-full bg-purple-600/30 text-sm font-medium text-purple-300 hover:bg-purple-600/50"
            aria-label="User menu"
            aria-expanded={userMenuOpen}
          >
            {user ? initials : <User size={16} />}
          </button>

          {userMenuOpen && (
            <div className="absolute right-0 top-10 z-50 w-56 rounded-md border border-white/10 bg-surface-raised py-1 shadow-lg">
              {user && (
                <div className="border-b border-white/10 px-4 py-2">
                  <p className="text-sm font-medium text-white">{user.name}</p>
                  <p className="text-xs text-gray-400">{user.email}</p>
                </div>
              )}
              <DropdownItem
                icon={User}
                label="Profile"
                onClick={() => setUserMenuOpen(false)}
              />
              <DropdownItem
                icon={Settings}
                label="Settings"
                onClick={() => setUserMenuOpen(false)}
              />
              <div className="border-t border-white/10" />
              <DropdownItem
                icon={LogOut}
                label="Logout"
                onClick={() => {
                  setUserMenuOpen(false);
                  void logout();
                }}
              />
            </div>
          )}
        </div>
      </div>
    </header>
  );
}

// ─── Dropdown Item ───────────────────────────────────────────────────

function DropdownItem({
  icon: Icon,
  label,
  onClick,
}: {
  icon: React.ComponentType<{ size?: number }>;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "flex w-full items-center gap-3 px-4 py-2 text-sm text-gray-300",
        "hover:bg-white/5 hover:text-white",
      )}
    >
      <Icon size={14} />
      <span>{label}</span>
    </button>
  );
}
