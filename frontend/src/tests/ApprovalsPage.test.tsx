import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ApprovalsPage } from "@/pages/ApprovalsPage";
import type { Approval } from "@/types/approvals";

// ─── Mocks ────────────────────────────────────────────────────────────

vi.mock("@/api/approvals", () => ({
  listApprovals: vi.fn(),
  getApproval: vi.fn(),
  approveApproval: vi.fn(),
  rejectApproval: vi.fn(),
  resumeRun: vi.fn(),
}));

import {
  listApprovals,
  approveApproval,
  rejectApproval,
} from "@/api/approvals";

// Default to non-admin tenant user; individual tests override via setAuth.
let mockUser: {
  id: string;
  tenant_id: string;
  roles: string[];
  permissions: string[];
} | null = {
  id: "00000000-0000-0000-0000-000000000099",
  tenant_id: "00000000-0000-0000-0000-000000000001",
  roles: [],
  permissions: [],
};

vi.mock("@/providers/auth-provider", () => ({
  useAuth: () => ({
    user: mockUser,
    hasRole: (role: string) => (mockUser?.roles ?? []).includes(role),
    hasPermission: (perm: string) =>
      (mockUser?.permissions ?? []).includes(perm),
  }),
}));

// ─── Fixtures ─────────────────────────────────────────────────────────

function makeApproval(overrides: Partial<Approval> = {}): Approval {
  return {
    id: "approval-1",
    run_id: "run-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    step_id: "step_1",
    tenant_id: "00000000-0000-0000-0000-000000000001",
    requester_id: "user-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    approver_id: null,
    status: "pending",
    decision_reason: null,
    requested_at: "2025-01-01T10:00:00Z",
    decided_at: null,
    expires_at: "2025-01-02T10:00:00Z",
    payload: { reason: "needs review" },
    ...overrides,
  };
}

// ─── Helpers ──────────────────────────────────────────────────────────

function renderPage() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <BrowserRouter>
        <ApprovalsPage />
      </BrowserRouter>
    </QueryClientProvider>,
  );
}

// ─── Tests ────────────────────────────────────────────────────────────

describe("ApprovalsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUser = {
      id: "00000000-0000-0000-0000-000000000099",
      tenant_id: "00000000-0000-0000-0000-000000000001",
      roles: [],
      permissions: [],
    };
  });

  it("renders pending approvals from the list endpoint", async () => {
    vi.mocked(listApprovals).mockResolvedValueOnce([
      makeApproval({ id: "a-1", step_id: "human_gate" }),
      makeApproval({ id: "a-2", step_id: "deploy_gate" }),
    ]);

    renderPage();

    expect(await screen.findByText("Approvals")).toBeInTheDocument();
    const cards = await screen.findAllByTestId("approval-card");
    expect(cards).toHaveLength(2);
    expect(cards[0]).toHaveAttribute("data-approval-id", "a-1");
    expect(cards[1]).toHaveAttribute("data-approval-id", "a-2");
    expect(screen.getByText("human_gate")).toBeInTheDocument();
    expect(screen.getByText("deploy_gate")).toBeInTheDocument();
  });

  it("opens the approve dialog and submits with reason", async () => {
    const user = userEvent.setup();
    vi.mocked(listApprovals).mockResolvedValue([
      makeApproval({ id: "a-1" }),
    ]);
    vi.mocked(approveApproval).mockResolvedValueOnce({
      approval: makeApproval({ id: "a-1", status: "approved" }),
      signal_id: "sig-1",
    });

    renderPage();

    const card = await screen.findByTestId("approval-card");
    await act(async () => {
      await user.click(within(card).getByLabelText(/approve approval a-1/i));
    });

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/approve approval/i)).toBeInTheDocument();

    const textarea = within(dialog).getByLabelText(/reason/i);
    await act(async () => {
      await user.type(textarea, "looks good");
    });

    const submit = within(dialog).getByRole("button", {
      name: /^approve$/i,
    });
    await act(async () => {
      await user.click(submit);
    });

    await waitFor(() => {
      expect(approveApproval).toHaveBeenCalledWith("a-1", "looks good");
    });
  });

  it("refreshes the list after a decision via TanStack invalidation", async () => {
    const user = userEvent.setup();
    vi.mocked(listApprovals)
      .mockResolvedValueOnce([makeApproval({ id: "a-1" })])
      .mockResolvedValueOnce([]);

    vi.mocked(approveApproval).mockResolvedValueOnce({
      approval: makeApproval({ id: "a-1", status: "approved" }),
      signal_id: "sig-1",
    });

    renderPage();

    const card = await screen.findByTestId("approval-card");
    await act(async () => {
      await user.click(within(card).getByLabelText(/approve approval a-1/i));
    });

    const dialog = await screen.findByRole("dialog");
    await act(async () => {
      await user.click(
        within(dialog).getByRole("button", { name: /^approve$/i }),
      );
    });

    await waitFor(() => {
      expect(approveApproval).toHaveBeenCalled();
    });

    // After invalidation the list is fetched again — empty this time.
    await waitFor(() => {
      expect(listApprovals).toHaveBeenCalledTimes(2);
    });

    expect(
      await screen.findByText(/no approvals to show/i),
    ).toBeInTheDocument();
  });

  it("shows the empty state when there are no approvals", async () => {
    vi.mocked(listApprovals).mockResolvedValueOnce([]);
    renderPage();
    expect(
      await screen.findByText(/no approvals to show/i),
    ).toBeInTheDocument();
  });

  it("shows the admin badge when the caller is an admin", async () => {
    mockUser = {
      id: "00000000-0000-0000-0000-000000000099",
      tenant_id: "00000000-0000-0000-0000-000000000001",
      roles: ["admin"],
      permissions: [],
    };
    vi.mocked(listApprovals).mockResolvedValueOnce([]);
    renderPage();
    expect(
      await screen.findByText(/admin · all tenants/i),
    ).toBeInTheDocument();
  });

  it("does not show admin badge for non-admin tenant user", async () => {
    vi.mocked(listApprovals).mockResolvedValueOnce([]);
    renderPage();
    expect(await screen.findByText("Approvals")).toBeInTheDocument();
    expect(screen.queryByText(/admin · all tenants/i)).not.toBeInTheDocument();
  });

  it("submits a reject decision with reason", async () => {
    const user = userEvent.setup();
    vi.mocked(listApprovals).mockResolvedValueOnce([
      makeApproval({ id: "a-1" }),
    ]);
    vi.mocked(rejectApproval).mockResolvedValueOnce({
      approval: makeApproval({ id: "a-1", status: "rejected" }),
      signal_id: "sig-2",
    });

    renderPage();

    const card = await screen.findByTestId("approval-card");
    await act(async () => {
      await user.click(within(card).getByLabelText(/reject approval a-1/i));
    });

    const dialog = await screen.findByRole("dialog");
    await act(async () => {
      await user.type(
        within(dialog).getByLabelText(/reason/i),
        "missing context",
      );
      await user.click(
        within(dialog).getByRole("button", { name: /^reject$/i }),
      );
    });

    await waitFor(() => {
      expect(rejectApproval).toHaveBeenCalledWith("a-1", "missing context");
    });
  });
});
