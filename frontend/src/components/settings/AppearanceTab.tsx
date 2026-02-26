import { useState, useEffect } from "react";
import { Palette, Sun, Moon, Monitor } from "lucide-react";
import { Button } from "@/components/ui/Button";

function Card({
  icon: Icon,
  title,
  children,
}: {
  icon: React.ElementType;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-lg border border-surface-border bg-surface-raised p-5">
      <h2 className="mb-4 flex items-center gap-2 text-sm font-semibold">
        <Icon size={14} className="text-purple-400" />
        {title}
      </h2>
      {children}
    </div>
  );
}

type ThemeMode = "dark" | "light" | "system";

export function AppearanceTab() {
  const [theme, setTheme] = useState<ThemeMode>(() => {
    return (localStorage.getItem("archon-theme") as ThemeMode) || "dark";
  });
  const [accentColor, setAccentColor] = useState("#8b5cf6");
  const [compactMode, setCompactMode] = useState(false);

  useEffect(() => {
    localStorage.setItem("archon-theme", theme);

    const root = document.documentElement;
    if (theme === "system") {
      const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
      root.classList.toggle("dark", prefersDark);
      root.classList.toggle("light", !prefersDark);
    } else {
      root.classList.toggle("dark", theme === "dark");
      root.classList.toggle("light", theme === "light");
    }
  }, [theme]);

  const accentColors = [
    { name: "Purple", value: "#8b5cf6" },
    { name: "Blue", value: "#3b82f6" },
    { name: "Green", value: "#10b981" },
    { name: "Orange", value: "#f97316" },
    { name: "Pink", value: "#ec4899" },
  ];

  return (
    <div className="space-y-6">
      <Card icon={Palette} title="Theme">
        <p className="mb-4 text-sm text-gray-400">Choose your preferred color scheme.</p>
        <div className="flex gap-3">
          <Button
            variant={theme === "dark" ? "default" : "outline"}
            size="sm"
            onClick={() => setTheme("dark")}
          >
            <Moon size={14} className="mr-1.5" />
            Dark
          </Button>
          <Button
            variant={theme === "light" ? "default" : "outline"}
            size="sm"
            onClick={() => setTheme("light")}
          >
            <Sun size={14} className="mr-1.5" />
            Light
          </Button>
          <Button
            variant={theme === "system" ? "default" : "outline"}
            size="sm"
            onClick={() => setTheme("system")}
          >
            <Monitor size={14} className="mr-1.5" />
            System
          </Button>
        </div>
      </Card>

      <Card icon={Palette} title="Accent Color">
        <div className="flex gap-3">
          {accentColors.map((color) => (
            <button
              key={color.value}
              title={color.name}
              onClick={() => setAccentColor(color.value)}
              className={`h-8 w-8 rounded-full border-2 transition-transform ${
                accentColor === color.value
                  ? "scale-110 border-white"
                  : "border-transparent hover:scale-105"
              }`}
              style={{ backgroundColor: color.value }}
              aria-label={`Select ${color.name} accent color`}
            />
          ))}
        </div>
      </Card>

      <Card icon={Palette} title="Layout">
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={compactMode}
            onChange={(e) => setCompactMode(e.target.checked)}
            className="rounded border-gray-600 accent-purple-500"
          />
          Compact mode — reduce spacing and padding
        </label>
      </Card>
    </div>
  );
}
