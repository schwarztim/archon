import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { AuthProvider, RequireAuth } from "@/providers/auth-provider";
import type { ReactNode } from "react";

// ─── Mocks ────────────────────────────────────────────────────────────
// Mock /api/v1/auth/me so AuthProvider resolves to different user states.

function mockMeResponse(
  user: {
    name: string;
    email: string;
    permissions: string[];
    roles: string[];
  } | null,
) {
  vi.stubGlobal(
    "fetch",
    vi.fn((_url: string) => {
      if (user === null) {
        // Simulate 401 — causes AuthProvider to set user = null
        return Promise.resolve({
          ok: false,
          status: 401,
          statusText: "Unauthorized",
          json: () => Promise.resolve({ errors: [{ code: "401", message: "Unauthorized" }] }),
        });
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () =>
          Promise.resolve({
            data: {
              user,
              expires_at: new Date(Date.now() + 3_600_000).toISOString(),
            },
          }),
      });
    }),
  );
}

// ─── Helper ───────────────────────────────────────────────────────────

function renderGuard(props: {
  children?: ReactNode;
  permission?: string;
  role?: string;
  fallback?: ReactNode;
}) {
  return render(
    <AuthProvider>
      <RequireAuth {...props}>
        {props.children ?? <span>Protected Content</span>}
      </RequireAuth>
    </AuthProvider>,
  );
}

// ─── Tests ────────────────────────────────────────────────────────────

describe("RequireAuth RBAC guard", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("shows loading state while auth is loading", () => {
    // Stall the fetch so loading stays true
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));

    renderGuard({});
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
  });

  it("renders fallback when user is not authenticated", async () => {
    mockMeResponse(null);

    renderGuard({ fallback: <span>Please log in</span> });

    // Initially loading — then resolves to null user
    expect(await screen.findByText("Please log in")).toBeInTheDocument();
    expect(screen.queryByText("Protected Content")).not.toBeInTheDocument();
  });

  it("renders null when unauthenticated and no fallback provided", async () => {
    mockMeResponse(null);

    renderGuard({});
    // Wait for loading to resolve then assert content is absent
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.queryByText("Protected Content")).not.toBeInTheDocument();
  });

  it("renders children when user is authenticated with no permission/role required", async () => {
    mockMeResponse({ name: "Test User", email: "test@archon.ai", permissions: [], roles: [] });

    renderGuard({});
    expect(await screen.findByText("Protected Content")).toBeInTheDocument();
  });

  it("renders children when user has the required permission", async () => {
    mockMeResponse({
      name: "Test User",
      email: "test@archon.ai",
      permissions: ["agents:read"],
      roles: [],
    });

    renderGuard({ permission: "agents:read" });
    expect(await screen.findByText("Protected Content")).toBeInTheDocument();
  });

  it("shows insufficient-permissions message when user lacks required permission", async () => {
    mockMeResponse({
      name: "Test User",
      email: "test@archon.ai",
      permissions: [],
      roles: [],
    });

    renderGuard({ permission: "agents:write" });
    expect(await screen.findByText(/insufficient permissions/i)).toBeInTheDocument();
    expect(screen.queryByText("Protected Content")).not.toBeInTheDocument();
  });

  it("renders children when user has the required role", async () => {
    mockMeResponse({
      name: "Test User",
      email: "test@archon.ai",
      permissions: [],
      roles: ["admin"],
    });

    renderGuard({ role: "admin" });
    expect(await screen.findByText("Protected Content")).toBeInTheDocument();
  });

  it("shows insufficient-role message when user lacks required role", async () => {
    mockMeResponse({
      name: "Test User",
      email: "test@archon.ai",
      permissions: [],
      roles: ["viewer"],
    });

    renderGuard({ role: "admin" });
    expect(await screen.findByText(/insufficient role/i)).toBeInTheDocument();
    expect(screen.queryByText("Protected Content")).not.toBeInTheDocument();
  });

  it("checks permission before role — shows permission error first", async () => {
    mockMeResponse({
      name: "Test User",
      email: "test@archon.ai",
      permissions: [],
      roles: ["admin"],
    });

    renderGuard({ permission: "agents:write", role: "admin" });
    expect(await screen.findByText(/insufficient permissions/i)).toBeInTheDocument();
    expect(screen.queryByText("Protected Content")).not.toBeInTheDocument();
  });

  it("renders custom fallback when unauthenticated", async () => {
    mockMeResponse(null);

    renderGuard({ fallback: <div data-testid="custom-fallback">Unauthorized</div> });
    expect(await screen.findByTestId("custom-fallback")).toBeInTheDocument();
  });
});
