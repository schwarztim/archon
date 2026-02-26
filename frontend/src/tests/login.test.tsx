import { describe, it, expect, vi } from "vitest";
import { render, screen, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { LoginPage } from "@/pages/LoginPage";
import { ThemeProvider } from "@/providers/theme-provider";

// ─── Mocks ────────────────────────────────────────────────────────────

vi.mock("@/providers/auth-provider", () => ({
  useAuth: () => ({
    login: vi.fn(),
    loginSSO: vi.fn(),
    loading: false,
    error: null,
  }),
}));

// ─── Helper ───────────────────────────────────────────────────────────

function renderLogin() {
  return render(
    <ThemeProvider defaultTheme="dark">
      <LoginPage />
    </ThemeProvider>,
  );
}

// ─── Tests ────────────────────────────────────────────────────────────

describe("LoginPage", () => {
  it("renders the login form", () => {
    renderLogin();
    expect(screen.getByText(/sign in to archon/i)).toBeInTheDocument();
  });

  it("displays email and password input fields", () => {
    renderLogin();
    expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument();
  });

  it("displays the sign in button", () => {
    renderLogin();
    expect(screen.getByRole("button", { name: /sign in$/i })).toBeInTheDocument();
  });

  it("displays the SSO button", () => {
    renderLogin();
    expect(
      screen.getByRole("button", { name: /sign in with sso/i }),
    ).toBeInTheDocument();
  });

  it("displays remember me checkbox", () => {
    renderLogin();
    expect(screen.getByText(/remember me/i)).toBeInTheDocument();
  });

  it("displays forgot password link", () => {
    renderLogin();
    expect(screen.getByText(/forgot password/i)).toBeInTheDocument();
  });

  it("validates email format on blur", async () => {
    const user = userEvent.setup();
    renderLogin();

    const emailInput = screen.getByLabelText(/email/i);
    await act(async () => {
      await user.type(emailInput, "invalid-email");
      await user.tab();
    });

    expect(
      await screen.findByText(/please enter a valid email address/i),
    ).toBeInTheDocument();
  });

  it("shows password required error on blur when empty", async () => {
    const user = userEvent.setup();
    renderLogin();

    const passwordInput = screen.getByLabelText(/password/i);
    await act(async () => {
      await user.click(passwordInput);
      await user.tab();
    });

    expect(
      await screen.findByText(/password is required/i),
    ).toBeInTheDocument();
  });
});
