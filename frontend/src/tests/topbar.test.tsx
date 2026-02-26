import { describe, it, expect, vi } from "vitest";
import { render, screen, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TopBar } from "@/components/navigation/TopBar";
import { ThemeProvider } from "@/providers/theme-provider";

// ─── Mocks ────────────────────────────────────────────────────────────

vi.mock("@/providers/auth-provider", () => ({
  useAuth: () => ({
    user: { name: "Ada Lovelace", email: "ada@archon.ai", permissions: [], roles: [] },
    logout: vi.fn(),
  }),
}));

// ─── Helper ───────────────────────────────────────────────────────────

function renderTopBar(defaultTheme: "dark" | "light" = "dark") {
  return render(
    <ThemeProvider defaultTheme={defaultTheme}>
      <TopBar />
    </ThemeProvider>,
  );
}

// ─── Tests ────────────────────────────────────────────────────────────

describe("TopBar theme toggle", () => {
  it("renders a theme toggle button", () => {
    renderTopBar("dark");
    const btn = screen.getByRole("button", { name: /switch to light mode/i });
    expect(btn).toBeInTheDocument();
  });

  it("shows 'Switch to dark mode' label when in light theme", () => {
    renderTopBar("light");
    expect(
      screen.getByRole("button", { name: /switch to dark mode/i }),
    ).toBeInTheDocument();
  });

  it("toggles theme on button click", async () => {
    const user = userEvent.setup();
    renderTopBar("dark");

    const btn = screen.getByRole("button", { name: /switch to light mode/i });
    await act(async () => {
      await user.click(btn);
    });

    expect(
      screen.getByRole("button", { name: /switch to dark mode/i }),
    ).toBeInTheDocument();
  });

  it("renders user initials in avatar", () => {
    renderTopBar();
    // Ada Lovelace → "AL"
    expect(screen.getByText("AL")).toBeInTheDocument();
  });

  it("calls onMenuToggle when hamburger clicked", async () => {
    const user = userEvent.setup();
    const onMenuToggle = vi.fn();
    render(
      <ThemeProvider defaultTheme="dark">
        <TopBar onMenuToggle={onMenuToggle} />
      </ThemeProvider>,
    );

    const hamburger = screen.getByRole("button", { name: /toggle menu/i });
    await act(async () => {
      await user.click(hamburger);
    });

    expect(onMenuToggle).toHaveBeenCalledOnce();
  });
});
