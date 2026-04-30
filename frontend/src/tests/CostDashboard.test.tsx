import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { CostDashboard } from "@/components/cost/CostDashboard";
import type { CostSummary } from "@/types/artifacts";
import type { ReactNode } from "react";

// ─── Mocks ────────────────────────────────────────────────────────────

const mockGetCostSummary = vi.fn();
const mockGetRunCost = vi.fn();
const mockApiGet = vi.fn();

vi.mock("@/api/cost", async () => {
  // Preserve the rest of the module so existing exports keep working.
  const actual = await vi.importActual<Record<string, unknown>>("@/api/cost");
  return {
    ...actual,
    getCostSummary: (...args: unknown[]) => mockGetCostSummary(...args),
    getRunCost: (...args: unknown[]) => mockGetRunCost(...args),
  };
});

vi.mock("@/api/client", () => ({
  apiGet: (...args: unknown[]) => mockApiGet(...args),
  apiPost: vi.fn(),
  apiPut: vi.fn(),
  apiDelete: vi.fn(),
}));

// ─── Helpers ──────────────────────────────────────────────────────────

function makeSummary(overrides: Partial<CostSummary> = {}): CostSummary {
  return {
    total_cost: 12.34,
    total_input_tokens: 1500,
    total_output_tokens: 750,
    call_count: 42,
    by_provider: { openai: 8.0, anthropic: 4.34 },
    by_model: { "gpt-4o": 8.0, "claude-3.5-sonnet": 4.34 },
    by_department: {},
    by_user: {},
    period: { since: "2026-04-01T00:00:00Z", until: "2026-05-01T00:00:00Z" },
    ...overrides,
  };
}

function envelope<T>(data: T) {
  return { data, meta: { request_id: "req", timestamp: "now" } };
}

function wrap(ui: ReactNode) {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

// Default routes: alerts, usage, chart all empty unless overridden in a test.
function defaultApiGet(path: string) {
  if (path === "/cost/usage") return Promise.resolve(envelope([]));
  if (path === "/cost/alerts") return Promise.resolve(envelope([]));
  if (path === "/cost/chart")
    return Promise.resolve(
      envelope({ granularity: "daily", providers: [], series: [] }),
    );
  return Promise.resolve(envelope({}));
}

// ─── Tests ────────────────────────────────────────────────────────────

describe("CostDashboard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockApiGet.mockImplementation(defaultApiGet);
  });

  it("renders summary card totals from cost summary", async () => {
    mockGetCostSummary.mockResolvedValue(makeSummary());
    wrap(<CostDashboard />);
    expect(await screen.findByText("$12.34")).toBeInTheDocument();
    expect(screen.getByText("42")).toBeInTheDocument();
  });

  it("paginates / sorts top runs from usage entries", async () => {
    mockGetCostSummary.mockResolvedValue(makeSummary());
    mockApiGet.mockImplementation((path: string) => {
      if (path === "/cost/usage") {
        return Promise.resolve(
          envelope([
            // execution A: 0.05 + 0.03 = 0.08
            {
              id: "u1",
              execution_id: "aaa",
              model_id: "gpt-4o",
              input_tokens: 100,
              output_tokens: 50,
              total_cost: 0.05,
            },
            {
              id: "u2",
              execution_id: "aaa",
              model_id: "gpt-4o",
              input_tokens: 100,
              output_tokens: 50,
              total_cost: 0.03,
            },
            // execution B: 0.5 (more expensive — should rank first)
            {
              id: "u3",
              execution_id: "bbb",
              model_id: "claude-3.5-sonnet",
              input_tokens: 1000,
              output_tokens: 200,
              total_cost: 0.5,
            },
          ]),
        );
      }
      return defaultApiGet(path);
    });

    wrap(<CostDashboard />);
    await waitFor(() => {
      expect(
        screen.getByText(/top 10 most expensive runs/i),
      ).toBeInTheDocument();
    });

    // Look for both rows by their model labels
    await screen.findByText("claude-3.5-sonnet");
    expect(screen.getByText("gpt-4o")).toBeInTheDocument();

    // The most expensive run ($0.50) should appear before the cheaper ($0.08)
    const rows = screen.getAllByRole("row");
    // header row + 2 data rows
    expect(rows.length).toBeGreaterThanOrEqual(3);
    // The first data row should contain claude (more expensive)
    const firstDataRow = rows[1];
    expect(firstDataRow?.textContent ?? "").toContain("claude-3.5-sonnet");
  });

  it("respects the per-tenant filter input when admin", async () => {
    mockGetCostSummary.mockResolvedValue(makeSummary({ total_cost: 0 }));
    wrap(<CostDashboard showTenantFilter />);

    const tenantInput = await screen.findByLabelText(/tenant id/i);
    fireEvent.change(tenantInput, { target: { value: "tenant-xyz" } });

    await waitFor(() => {
      // Last call to getCostSummary should include the filter
      const calls = mockGetCostSummary.mock.calls;
      const lastCall = calls[calls.length - 1];
      const args = lastCall?.[0] as { tenant_id?: string } | undefined;
      expect(args?.tenant_id).toBe("tenant-xyz");
    });
  });

  it("shows the 'no costs recorded' empty state when there is no data", async () => {
    mockGetCostSummary.mockResolvedValue(makeSummary({ total_cost: 0, call_count: 0 }));
    wrap(<CostDashboard />);
    await waitFor(() => {
      expect(screen.getByTestId("cost-empty-state")).toBeInTheDocument();
    });
    expect(screen.getByText(/no costs recorded/i)).toBeInTheDocument();
  });

  it("renders the spend sparkline structure when chart data is present", async () => {
    mockGetCostSummary.mockResolvedValue(makeSummary());
    mockApiGet.mockImplementation((path: string) => {
      if (path === "/cost/chart") {
        return Promise.resolve(
          envelope({
            granularity: "daily",
            providers: ["openai", "anthropic"],
            series: [
              { date: "2026-04-25", openai: 1.0, anthropic: 0.5 },
              { date: "2026-04-26", openai: 2.0, anthropic: 0.0 },
              { date: "2026-04-27", openai: 0.5, anthropic: 1.5 },
            ],
          }),
        );
      }
      return defaultApiGet(path);
    });
    wrap(<CostDashboard />);
    await waitFor(() => {
      expect(screen.getByTestId("cost-sparkline")).toBeInTheDocument();
    });
    const spark = screen.getByTestId("cost-sparkline");
    // 3 series points → 3 bars
    expect(spark.children.length).toBe(3);
  });
});
