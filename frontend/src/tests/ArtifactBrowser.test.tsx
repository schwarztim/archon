import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ArtifactBrowser } from "@/components/artifacts/ArtifactBrowser";
import type { Artifact } from "@/types/artifacts";
import type { ReactNode } from "react";

// ─── Mocks ────────────────────────────────────────────────────────────

const mockListArtifacts = vi.fn();
const mockGetArtifact = vi.fn();
const mockGetArtifactContent = vi.fn();
const mockDeleteArtifact = vi.fn();

vi.mock("@/api/artifacts", () => ({
  listArtifacts: (...args: unknown[]) => mockListArtifacts(...args),
  getArtifact: (...args: unknown[]) => mockGetArtifact(...args),
  getArtifactContent: (...args: unknown[]) => mockGetArtifactContent(...args),
  deleteArtifact: (...args: unknown[]) => mockDeleteArtifact(...args),
  apiDelete: vi.fn(),
}));

// ─── Helpers ──────────────────────────────────────────────────────────

function makeArtifact(overrides: Partial<Artifact> = {}): Artifact {
  return {
    id: "11111111-1111-1111-1111-111111111111",
    run_id: "22222222-2222-2222-2222-222222222222",
    step_id: "step-1",
    tenant_id: "33333333-3333-3333-3333-333333333333",
    content_type: "application/json",
    content_hash:
      "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
    size_bytes: 4096,
    storage_backend: "local",
    storage_uri: "/tmp/x",
    retention_days: 30,
    expires_at: null,
    created_at: "2026-04-29T12:00:00Z",
    metadata: {},
    ...overrides,
  };
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

// ─── Tests ────────────────────────────────────────────────────────────

describe("ArtifactBrowser", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders empty state when no artifacts exist", async () => {
    mockListArtifacts.mockResolvedValue({ items: [], next_cursor: null });
    wrap(<ArtifactBrowser />);
    await waitFor(() => {
      expect(
        screen.getByTestId("artifacts-empty-state"),
      ).toBeInTheDocument();
    });
    expect(screen.getByText(/no artifacts found/i)).toBeInTheDocument();
  });

  it("renders artifact rows when data is returned", async () => {
    const a1 = makeArtifact({ id: "aaa11111-1111-1111-1111-111111111111" });
    const a2 = makeArtifact({
      id: "bbb22222-2222-2222-2222-222222222222",
      content_type: "image/png",
    });
    mockListArtifacts.mockResolvedValue({
      items: [a1, a2],
      next_cursor: null,
    });
    wrap(<ArtifactBrowser />);
    await waitFor(() => {
      expect(screen.getByTestId(`artifact-row-${a1.id}`)).toBeInTheDocument();
    });
    expect(screen.getByTestId(`artifact-row-${a2.id}`)).toBeInTheDocument();
    expect(screen.getByText("application/json")).toBeInTheDocument();
    expect(screen.getByText("image/png")).toBeInTheDocument();
  });

  it("filters by content_type when the filter input changes", async () => {
    const a = makeArtifact();
    mockListArtifacts.mockResolvedValue({ items: [a], next_cursor: null });
    wrap(<ArtifactBrowser />);
    await waitFor(() => {
      expect(screen.getByTestId(`artifact-row-${a.id}`)).toBeInTheDocument();
    });

    const input = screen.getByLabelText(/content type/i) as HTMLInputElement;
    fireEvent.change(input, { target: { value: "application/json" } });

    await waitFor(() => {
      const lastCall =
        mockListArtifacts.mock.calls[mockListArtifacts.mock.calls.length - 1];
      const opts = lastCall?.[0] as { content_type?: string };
      expect(opts?.content_type).toBe("application/json");
    });
  });

  it("opens the preview modal when a row is clicked", async () => {
    const a = makeArtifact();
    mockListArtifacts.mockResolvedValue({ items: [a], next_cursor: null });
    mockGetArtifact.mockResolvedValue(a);
    mockGetArtifactContent.mockResolvedValue('{"hello":"world"}');
    wrap(<ArtifactBrowser />);
    await waitFor(() => {
      expect(screen.getByTestId(`artifact-row-${a.id}`)).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId(`artifact-row-${a.id}`));

    await waitFor(() => {
      expect(
        screen.getByRole("dialog", { name: /artifact preview/i }),
      ).toBeInTheDocument();
    });
  });

  it("requires confirmation before deleting", async () => {
    const a = makeArtifact();
    mockListArtifacts.mockResolvedValue({ items: [a], next_cursor: null });
    mockGetArtifact.mockResolvedValue(a);
    mockGetArtifactContent.mockResolvedValue('{"x":1}');
    mockDeleteArtifact.mockResolvedValue({ deleted: true });

    wrap(<ArtifactBrowser />);
    await waitFor(() => {
      expect(screen.getByTestId(`artifact-row-${a.id}`)).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId(`artifact-row-${a.id}`));
    await waitFor(() => {
      expect(
        screen.getByRole("dialog", { name: /artifact preview/i }),
      ).toBeInTheDocument();
    });

    // First click is the trigger — does NOT call deleteArtifact yet
    const deleteBtn = screen.getByLabelText(/delete artifact/i);
    fireEvent.click(deleteBtn);
    expect(mockDeleteArtifact).not.toHaveBeenCalled();

    // Confirmation message appears
    expect(screen.getByText(/delete permanently/i)).toBeInTheDocument();

    // Confirm delete fires the mutation
    const confirmBtn = screen.getByRole("button", { name: /confirm delete/i });
    fireEvent.click(confirmBtn);
    await waitFor(() => {
      expect(mockDeleteArtifact).toHaveBeenCalledWith(a.id);
    });
  });

  it("renders 'not found' when the preview fetch returns 404", async () => {
    const a = makeArtifact();
    mockListArtifacts.mockResolvedValue({ items: [a], next_cursor: null });
    // Simulate cross-tenant 404
    mockGetArtifact.mockRejectedValue({
      errors: [{ code: "NOT_FOUND", message: "Artifact not found" }],
    });
    mockGetArtifactContent.mockRejectedValue({
      errors: [{ code: "NOT_FOUND", message: "Artifact not found" }],
    });

    wrap(<ArtifactBrowser />);
    await waitFor(() => {
      expect(screen.getByTestId(`artifact-row-${a.id}`)).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId(`artifact-row-${a.id}`));

    await waitFor(() => {
      expect(screen.getByText(/artifact not found/i)).toBeInTheDocument();
    });
  });
});
