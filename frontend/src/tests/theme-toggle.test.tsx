import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ThemeProvider } from "@/providers/theme-provider";
import { TopBar } from "@/components/navigation/TopBar";

// ─── Mocks ────────────────────────────────────────────────────────────

vi.mock("@/providers/auth-provider", () => ({
  useAuth: () => ({
    user: { name: "Test User", email: "test@archon.ai", permissions: [], roles: [] },
    logout: vi.fn(),
  }),
}));

// ─── Helper ───────────────────────────────────────────────────────────

function renderWithTheme(defaultTheme: "dark" | "light" = "dark") {
  return render(
    <ThemeProvider defaultTheme={defaultTheme}>
      <TopBar />
    </ThemeProvider>,
  );
}

// ─── Tests ────────────────────────────────────────────────────────────

describe("Theme toggle — classList changes", () => {
  beforeEach(() => {
    document.documentElement.classList.remove("dark", "light");
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it("applies 'dark' class to <html> when defaultTheme is dark", () => {
    renderWithTheme("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(document.documentElement.classList.contains("light")).toBe(false);
  });

  it("applies 'light' class to <html> when defaultTheme is light", () => {
    renderWithTheme("light");
    expect(document.documentElement.classList.contains("light")).toBe(true);
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });

  it("clicking toggle in dark mode adds 'light' class and removes 'dark'", async () => {
    const user = userEvent.setup();
    renderWithTheme("dark");

    expect(document.documentElement.classList.contains("dark")).toBe(true);

    const btn = screen.getByRole("button", { name: /switch to light mode/i });
    await act(async () => {
      await user.click(btn);
    });

    expect(document.documentElement.classList.contains("light")).toBe(true);
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });

  it("clicking toggle in light mode adds 'dark' class and removes 'light'", async () => {
    const user = userEvent.setup();
    renderWithTheme("light");

    expect(document.documentElement.classList.contains("light")).toBe(true);

    const btn = screen.getByRole("button", { name: /switch to dark mode/i });
    await act(async () => {
      await user.click(btn);
    });

    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(document.documentElement.classList.contains("light")).toBe(false);
  });

  it("double-click returns to original theme class", async () => {
    const user = userEvent.setup();
    renderWithTheme("dark");

    const btnDark = screen.getByRole("button", { name: /switch to light mode/i });
    await act(async () => {
      await user.click(btnDark);
    });

    const btnLight = screen.getByRole("button", { name: /switch to dark mode/i });
    await act(async () => {
      await user.click(btnLight);
    });

    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(document.documentElement.classList.contains("light")).toBe(false);
  });

  it("toggle persists the new theme to localStorage", async () => {
    const user = userEvent.setup();
    renderWithTheme("dark");

    const btn = screen.getByRole("button", { name: /switch to light mode/i });
    await act(async () => {
      await user.click(btn);
    });

    expect(localStorage.getItem("archon-theme")).toBe("light");
  });

  it("toggle button aria-label updates after each click", async () => {
    const user = userEvent.setup();
    renderWithTheme("dark");

    expect(
      screen.getByRole("button", { name: /switch to light mode/i }),
    ).toBeInTheDocument();

    await act(async () => {
      await user.click(screen.getByRole("button", { name: /switch to light mode/i }));
    });

    expect(
      screen.getByRole("button", { name: /switch to dark mode/i }),
    ).toBeInTheDocument();
  });
});
