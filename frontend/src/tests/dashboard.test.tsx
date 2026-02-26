import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { DashboardPage } from "@/pages/DashboardPage";
import { BrowserRouter } from "react-router-dom";
import { ThemeProvider } from "@/providers/theme-provider";

// ─── Mocks ────────────────────────────────────────────────────────────

vi.mock("@/providers/auth-provider", () => ({
  useAuth: () => ({
    user: { name: "Test User", email: "test@archon.ai", permissions: [], roles: [] },
    logout: vi.fn(),
  }),
}));

vi.mock("@/api/client", () => ({
  apiGet: vi.fn().mockResolvedValue({
    data: [],
    meta: { pagination: { total: 0, limit: 100, offset: 0 } },
  }),
}));

globalThis.fetch = vi.fn().mockResolvedValue({
  ok: true,
  json: async () => ({ api: true, database: true, redis: true }),
}) as any;

// ─── Helper ───────────────────────────────────────────────────────────

function renderDashboard() {
  return render(
    <BrowserRouter>
      <ThemeProvider defaultTheme="dark">
        <DashboardPage />
      </ThemeProvider>
    </BrowserRouter>,
  );
}

// ─── Tests ────────────────────────────────────────────────────────────

describe("DashboardPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders without crashing and shows loading state", () => {
    renderDashboard();
    // Initial loading state
    expect(screen.getByText(/loading dashboard/i)).toBeInTheDocument();
  });

  it("displays dashboard title after loading", async () => {
    renderDashboard();
    // Wait for dashboard to load
    expect(await screen.findByText("Dashboard")).toBeInTheDocument();
  });

  it("displays stat cards after loading", async () => {
    renderDashboard();
    expect(await screen.findByText("Active Agents")).toBeInTheDocument();
    expect(screen.getByText("Executions Today")).toBeInTheDocument();
    expect(screen.getByText("Models Configured")).toBeInTheDocument();
    expect(screen.getByText("Total Cost This Month")).toBeInTheDocument();
  });

  it("displays Quick Start section", async () => {
    renderDashboard();
    expect(await screen.findByText("Quick Start")).toBeInTheDocument();
    expect(
      screen.getByText(/describe your agent in plain language/i),
    ).toBeInTheDocument();
  });
});
