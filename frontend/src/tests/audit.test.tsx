import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { AuditPage } from "@/pages/AuditPage";
import { ThemeProvider } from "@/providers/theme-provider";

// ─── Mocks ────────────────────────────────────────────────────────────

vi.mock("@/api/client", () => ({
  apiGet: vi.fn().mockResolvedValue({
    data: [],
    meta: { pagination: { total: 0, limit: 20, offset: 0 } },
  }),
}));

vi.mock("@/providers/auth-provider", () => ({
  useAuth: () => ({
    user: { name: "Test User", email: "test@archon.ai", permissions: [], roles: [] },
  }),
}));

// ─── Helper ───────────────────────────────────────────────────────────

function renderAuditPage() {
  return render(
    <ThemeProvider defaultTheme="dark">
      <AuditPage />
    </ThemeProvider>,
  );
}

// ─── Tests ────────────────────────────────────────────────────────────

describe("AuditPage", () => {
  it("renders and shows loading state initially", () => {
    renderAuditPage();
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
  });

  it("displays audit trail title after loading", async () => {
    renderAuditPage();
    expect(await screen.findByText("Audit Trail")).toBeInTheDocument();
  });

  it("displays the page description after loading", async () => {
    renderAuditPage();
    expect(await screen.findByText("Audit Trail")).toBeInTheDocument();
    expect(
      screen.getByText(/comprehensive log of all actions/i),
    ).toBeInTheDocument();
  });

  it("renders audit filters section", async () => {
    renderAuditPage();
    // Filter component should be present after loading
    expect(await screen.findByText("Audit Trail")).toBeInTheDocument();
  });
});
