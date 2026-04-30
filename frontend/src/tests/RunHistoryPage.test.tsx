/**
 * Tests for RunHistoryPage.
 *
 * Coverage
 *  - Empty state when no runs come back
 *  - Run rows render with correct status badges
 *  - Filter (status) propagates to the listRuns API call
 *  - Pagination cursor advances when "Next page" is clicked
 *  - Click on a row navigates via react-router
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";

import { RunHistoryPage } from "@/pages/RunHistoryPage";
import * as runsApi from "@/api/runs";
import type { WorkflowRunListResponse } from "@/types/workflow_run";

// ── Router mock ──────────────────────────────────────────────────────
const navigateMock = vi.fn();
vi.mock("react-router-dom", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router-dom")>();
  return {
    ...actual,
    useNavigate: () => navigateMock,
  };
});

// ── Fixtures ─────────────────────────────────────────────────────────

function makeRun(
  id: string,
  status:
    | "running"
    | "completed"
    | "failed"
    | "queued"
    | "pending"
    | "cancelled"
    | "paused" = "completed",
): WorkflowRunListResponse["items"][number] {
  return {
    id,
    kind: "workflow",
    workflow_id: "wf-1",
    agent_id: null,
    tenant_id: "tenant-a",
    status,
    trigger_type: "manual",
    triggered_by: "alice@example.com",
    queued_at: "2025-01-01T00:00:00Z",
    started_at: "2025-01-01T00:00:01Z",
    completed_at: status === "completed" ? "2025-01-01T00:00:30Z" : null,
    duration_ms: 29_000,
    error_code: null,
    created_at: "2025-01-01T00:00:00Z",
  };
}

function renderPage() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <RunHistoryPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  navigateMock.mockReset();
  vi.restoreAllMocks();
});

describe("RunHistoryPage", () => {
  it("renders empty state when listRuns returns no items", async () => {
    vi.spyOn(runsApi, "listRuns").mockResolvedValue({
      items: [],
      next_cursor: null,
    });

    renderPage();

    expect(await screen.findByTestId("empty-state")).toBeInTheDocument();
    expect(screen.queryAllByTestId("run-row")).toHaveLength(0);
  });

  it("renders run rows with correct status badges", async () => {
    vi.spyOn(runsApi, "listRuns").mockResolvedValue({
      items: [
        makeRun("run-completed", "completed"),
        makeRun("run-running", "running"),
        makeRun("run-failed", "failed"),
      ],
      next_cursor: null,
    });

    renderPage();

    const rows = await screen.findAllByTestId("run-row");
    expect(rows).toHaveLength(3);

    // Default sort is started_at desc; we don't depend on order.
    expect(screen.getByText(/run-completed/)).toBeInTheDocument();
    expect(screen.getByText(/run-running/)).toBeInTheDocument();
    expect(screen.getByText(/run-failed/)).toBeInTheDocument();

    // Status badges use capitalisation classes; check by visible text.
    expect(screen.getAllByText(/^completed$/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/^running$/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/^failed$/i).length).toBeGreaterThan(0);
  });

  it("filters by status and re-issues the query", async () => {
    const spy = vi
      .spyOn(runsApi, "listRuns")
      .mockResolvedValue({ items: [makeRun("run-1", "running")], next_cursor: null });

    renderPage();

    await screen.findByTestId("status-filter");

    fireEvent.change(screen.getByTestId("status-filter"), {
      target: { value: "running" },
    });

    await waitFor(() => {
      expect(spy).toHaveBeenCalledWith(
        expect.objectContaining({ status: "running" }),
      );
    });
  });

  it("advances the cursor when Next page is clicked", async () => {
    const spy = vi.spyOn(runsApi, "listRuns");
    spy.mockResolvedValueOnce({
      items: [makeRun("run-1")],
      next_cursor: "cursor-2",
    });
    spy.mockResolvedValue({
      items: [makeRun("run-2")],
      next_cursor: null,
    });

    renderPage();

    // Wait for the first page to resolve so the Next button picks up the cursor.
    await screen.findByTestId("run-row");
    const next = await waitFor(() => {
      const btn = screen.getByTestId("page-next");
      expect(btn).not.toBeDisabled();
      return btn;
    });
    fireEvent.click(next);

    await waitFor(() => {
      expect(spy).toHaveBeenCalledWith(
        expect.objectContaining({ cursor: "cursor-2" }),
      );
    });
  });

  it("clicking a row navigates to the execution detail page", async () => {
    vi.spyOn(runsApi, "listRuns").mockResolvedValue({
      items: [makeRun("run-clicked")],
      next_cursor: null,
    });

    renderPage();

    const row = await screen.findByTestId("run-row");
    fireEvent.click(row);

    expect(navigateMock).toHaveBeenCalledWith("/executions/run-clicked");
  });
});
