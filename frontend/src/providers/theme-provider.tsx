import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

// ─── Types ────────────────────────────────────────────────────────────

export type Theme = "dark" | "light";

interface ThemeContextType {
  theme: Theme;
  toggleTheme: () => void;
  setTheme: (theme: Theme) => void;
}

// ─── Context ──────────────────────────────────────────────────────────

const ThemeContext = createContext<ThemeContextType | null>(null);

// ─── Hook ─────────────────────────────────────────────────────────────

export function useTheme(): ThemeContextType {
  const ctx = useContext(ThemeContext);
  if (!ctx) {
    throw new Error("useTheme must be used within <ThemeProvider>");
  }
  return ctx;
}

// ─── Constants ────────────────────────────────────────────────────────

const STORAGE_KEY = "archon-theme";
const DEFAULT_THEME: Theme = "dark";

function getInitialTheme(): Theme {
  try {
    const stored = localStorage.getItem(STORAGE_KEY) as Theme | null;
    if (stored === "dark" || stored === "light") return stored;
  } catch {
    // localStorage unavailable (SSR / private browsing)
  }
  // Fall back to OS preference, defaulting to dark
  if (typeof window !== "undefined" && window.matchMedia) {
    return window.matchMedia("(prefers-color-scheme: light)").matches
      ? "light"
      : "dark";
  }
  return DEFAULT_THEME;
}

function applyTheme(theme: Theme) {
  const root = document.documentElement;
  root.classList.remove("dark", "light");
  root.classList.add(theme);
}

// ─── Provider ─────────────────────────────────────────────────────────

interface ThemeProviderProps {
  children: ReactNode;
  defaultTheme?: Theme;
}

export function ThemeProvider({ children, defaultTheme }: ThemeProviderProps) {
  const [theme, setThemeState] = useState<Theme>(
    () => defaultTheme ?? getInitialTheme(),
  );

  // Apply theme class to <html> on mount and changes
  useEffect(() => {
    applyTheme(theme);
    try {
      localStorage.setItem(STORAGE_KEY, theme);
    } catch {
      // ignore
    }
  }, [theme]);

  const setTheme = useCallback((next: Theme) => {
    setThemeState(next);
  }, []);

  const toggleTheme = useCallback(() => {
    setThemeState((prev) => (prev === "dark" ? "light" : "dark"));
  }, []);

  return (
    <ThemeContext.Provider value={{ theme, toggleTheme, setTheme }}>
      {children}
    </ThemeContext.Provider>
  );
}
