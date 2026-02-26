import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { Sidebar } from "@/components/navigation/Sidebar";
import { BrowserRouter } from "react-router-dom";
import { ThemeProvider } from "@/providers/theme-provider";

// ─── Mocks ────────────────────────────────────────────────────────────

vi.mock("@/providers/auth-provider", () => ({
  useAuth: () => ({
    user: { name: "Test User", email: "test@archon.ai", permissions: [], roles: ["user"] },
    hasRole: (role: string) => role === "user",
    hasPermission: () => true,
  }),
}));

// ─── Helper ───────────────────────────────────────────────────────────

function renderSidebar(collapsed = false) {
  return render(
    <BrowserRouter>
      <ThemeProvider defaultTheme="dark">
        <Sidebar collapsed={collapsed} onToggle={vi.fn()} />
      </ThemeProvider>
    </BrowserRouter>,
  );
}

// ─── Tests ────────────────────────────────────────────────────────────

describe("Sidebar", () => {
  it("renders without crashing", () => {
    renderSidebar();
    expect(screen.getByText("Archon")).toBeInTheDocument();
  });

  it("renders navigation links", () => {
    renderSidebar();
    expect(screen.getByText("Dashboard")).toBeInTheDocument();
    expect(screen.getByText("Agents")).toBeInTheDocument();
    expect(screen.getByText("Templates")).toBeInTheDocument();
    expect(screen.getByText("Executions")).toBeInTheDocument();
  });

  it("shows collapse button", () => {
    renderSidebar();
    const button = screen.getByRole("button", { name: /collapse sidebar/i });
    expect(button).toBeInTheDocument();
  });

  it("hides section titles when collapsed", () => {
    renderSidebar(true);
    expect(screen.queryByText("CORE")).not.toBeInTheDocument();
  });

  it("shows section titles when expanded", () => {
    renderSidebar(false);
    expect(screen.getByText("CORE")).toBeInTheDocument();
    expect(screen.getByText("OPERATIONS")).toBeInTheDocument();
    expect(screen.getByText("SECURITY")).toBeInTheDocument();
  });

  it("renders navigation with ARIA label", () => {
    renderSidebar();
    expect(screen.getByRole("navigation", { name: /main navigation/i })).toBeInTheDocument();
  });

  it("renders link to dashboard at root path", () => {
    renderSidebar();
    const dashboardLink = screen.getByRole("link", { name: /dashboard/i });
    expect(dashboardLink).toHaveAttribute("href", "/");
  });
});
