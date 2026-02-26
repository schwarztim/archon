import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ThemeProvider, useTheme } from "@/providers/theme-provider";
import type { ReactNode } from "react";

// ─── Helpers ──────────────────────────────────────────────────────────

function TestConsumer() {
  const { theme, toggleTheme, setTheme } = useTheme();
  return (
    <div>
      <span data-testid="theme-value">{theme}</span>
      <button onClick={toggleTheme} data-testid="toggle">
        Toggle
      </button>
      <button onClick={() => setTheme("light")} data-testid="set-light">
        Light
      </button>
      <button onClick={() => setTheme("dark")} data-testid="set-dark">
        Dark
      </button>
    </div>
  );
}

function renderWithTheme(children: ReactNode, defaultTheme?: "dark" | "light") {
  return render(
    <ThemeProvider defaultTheme={defaultTheme}>{children}</ThemeProvider>,
  );
}

// ─── Tests ────────────────────────────────────────────────────────────

describe("ThemeProvider", () => {
  beforeEach(() => {
    // Reset DOM classes
    document.documentElement.classList.remove("dark", "light");
    // Clear storage
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it("defaults to dark theme when no preference set", () => {
    // Mock matchMedia to not prefer light
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      value: vi.fn().mockReturnValue({ matches: false }),
    });

    renderWithTheme(<TestConsumer />);
    expect(screen.getByTestId("theme-value").textContent).toBe("dark");
  });

  it("applies defaultTheme prop", () => {
    renderWithTheme(<TestConsumer />, "light");
    expect(screen.getByTestId("theme-value").textContent).toBe("light");
  });

  it("adds the theme class to <html>", () => {
    renderWithTheme(<TestConsumer />, "dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });

  it("toggles between dark and light", async () => {
    const user = userEvent.setup();
    renderWithTheme(<TestConsumer />, "dark");

    await act(async () => {
      await user.click(screen.getByTestId("toggle"));
    });

    expect(screen.getByTestId("theme-value").textContent).toBe("light");
    expect(document.documentElement.classList.contains("light")).toBe(true);
  });

  it("toggles back to dark from light", async () => {
    const user = userEvent.setup();
    renderWithTheme(<TestConsumer />, "light");

    await act(async () => {
      await user.click(screen.getByTestId("toggle"));
    });

    expect(screen.getByTestId("theme-value").textContent).toBe("dark");
  });

  it("sets theme to light via setTheme", async () => {
    const user = userEvent.setup();
    renderWithTheme(<TestConsumer />, "dark");

    await act(async () => {
      await user.click(screen.getByTestId("set-light"));
    });

    expect(screen.getByTestId("theme-value").textContent).toBe("light");
  });

  it("sets theme to dark via setTheme", async () => {
    const user = userEvent.setup();
    renderWithTheme(<TestConsumer />, "light");

    await act(async () => {
      await user.click(screen.getByTestId("set-dark"));
    });

    expect(screen.getByTestId("theme-value").textContent).toBe("dark");
  });

  it("persists theme to localStorage", async () => {
    const user = userEvent.setup();
    renderWithTheme(<TestConsumer />, "dark");

    await act(async () => {
      await user.click(screen.getByTestId("set-light"));
    });

    expect(localStorage.getItem("archon-theme")).toBe("light");
  });

  it("reads theme from localStorage on mount", () => {
    localStorage.setItem("archon-theme", "light");
    renderWithTheme(<TestConsumer />);
    expect(screen.getByTestId("theme-value").textContent).toBe("light");
  });
});

describe("useTheme hook", () => {
  it("throws when used outside ThemeProvider", () => {
    // Suppress React error boundary console noise
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => render(<TestConsumer />)).toThrow(
      "useTheme must be used within <ThemeProvider>",
    );
    spy.mockRestore();
  });
});
