import { useState, type FormEvent } from "react";
import { useAuth } from "@/providers/auth-provider";
import { ShieldCheck, Loader2, AlertCircle, KeyRound } from "lucide-react";

type LoginError =
  | "invalid_credentials"
  | "account_locked"
  | "mfa_required"
  | "idp_unavailable"
  | "unknown";

function classifyError(message: string): LoginError {
  const lower = message.toLowerCase();
  if (lower.includes("locked")) return "account_locked";
  if (lower.includes("invalid") || lower.includes("credentials"))
    return "invalid_credentials";
  if (lower.includes("mfa")) return "mfa_required";
  if (lower.includes("idp") || lower.includes("unavailable"))
    return "idp_unavailable";
  return "unknown";
}

const ERROR_MESSAGES: Record<LoginError, string> = {
  invalid_credentials: "Invalid email or password. Please try again.",
  account_locked:
    "Your account has been locked due to too many failed attempts. Contact your administrator.",
  mfa_required: "Multi-factor authentication is required.",
  idp_unavailable:
    "The identity provider is currently unavailable. Please try again later.",
  unknown: "An unexpected error occurred. Please try again.",
};

export function LoginPage() {
  const { login, loginSSO, loading, error } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [rememberMe, setRememberMe] = useState(false);
  const [emailTouched, setEmailTouched] = useState(false);
  const [passwordTouched, setPasswordTouched] = useState(false);
  const [ssoLoading, setSsoLoading] = useState(false);

  const emailValid = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
  const passwordValid = password.length >= 1;
  const formValid = emailValid && passwordValid;

  const errorType = error ? classifyError(error) : null;

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setEmailTouched(true);
    setPasswordTouched(true);
    if (!formValid) return;
    await login(email, password, rememberMe);
  }

  async function handleSSO() {
    setSsoLoading(true);
    try {
      await loginSSO("saml");
    } finally {
      setSsoLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#0f1117] px-4">
      <div className="w-full max-w-md">
        {/* Logo & Title */}
        <div className="mb-8 text-center">
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-xl bg-purple-600/20">
            <ShieldCheck size={28} className="text-purple-400" />
          </div>
          <h1 className="text-2xl font-bold text-white">Sign in to Archon</h1>
          <p className="mt-1 text-sm text-gray-400">
            Enterprise AI Orchestration Platform
          </p>
        </div>

        {/* Error Banner */}
        {errorType && (
          <div
            className="mb-4 flex items-start gap-3 rounded-lg border border-red-500/30 bg-red-500/10 p-3"
            role="alert"
          >
            <AlertCircle size={18} className="mt-0.5 shrink-0 text-red-400" />
            <p className="text-sm text-red-300">{ERROR_MESSAGES[errorType]}</p>
          </div>
        )}

        {/* Login Form */}
        <form
          onSubmit={(e) => void handleSubmit(e)}
          className="rounded-lg border border-[#2a2d37] bg-[#1a1d27] p-6"
          noValidate
        >
          {/* Email */}
          <div className="mb-4">
            <label
              htmlFor="login-email"
              className="mb-1.5 block text-sm font-medium text-gray-300"
            >
              Email
            </label>
            <input
              id="login-email"
              type="email"
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              onBlur={() => setEmailTouched(true)}
              className={`w-full rounded-md border bg-[#0f1117] px-3 py-2 text-sm text-white placeholder-gray-500 outline-none transition focus:ring-2 focus:ring-purple-500 ${
                emailTouched && !emailValid
                  ? "border-red-500"
                  : "border-[#2a2d37]"
              }`}
              placeholder="you@company.com"
              disabled={loading}
              aria-invalid={emailTouched && !emailValid}
              aria-describedby={
                emailTouched && !emailValid ? "email-error" : undefined
              }
            />
            {emailTouched && !emailValid && (
              <p id="email-error" className="mt-1 text-xs text-red-400">
                Please enter a valid email address.
              </p>
            )}
          </div>

          {/* Password */}
          <div className="mb-4">
            <label
              htmlFor="login-password"
              className="mb-1.5 block text-sm font-medium text-gray-300"
            >
              Password
            </label>
            <input
              id="login-password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              onBlur={() => setPasswordTouched(true)}
              className={`w-full rounded-md border bg-[#0f1117] px-3 py-2 text-sm text-white placeholder-gray-500 outline-none transition focus:ring-2 focus:ring-purple-500 ${
                passwordTouched && !passwordValid
                  ? "border-red-500"
                  : "border-[#2a2d37]"
              }`}
              placeholder="••••••••"
              disabled={loading}
              aria-invalid={passwordTouched && !passwordValid}
              aria-describedby={
                passwordTouched && !passwordValid ? "password-error" : undefined
              }
            />
            {passwordTouched && !passwordValid && (
              <p id="password-error" className="mt-1 text-xs text-red-400">
                Password is required.
              </p>
            )}
          </div>

          {/* Remember Me & Forgot Password */}
          <div className="mb-6 flex items-center justify-between">
            <label className="flex items-center gap-2 text-sm text-gray-400">
              <input
                type="checkbox"
                checked={rememberMe}
                onChange={(e) => setRememberMe(e.target.checked)}
                className="h-4 w-4 rounded border-gray-600 bg-[#0f1117] text-purple-600 focus:ring-purple-500"
                disabled={loading}
              />
              Remember me
            </label>
            <a
              href="/forgot-password"
              className="text-sm text-purple-400 hover:text-purple-300"
            >
              Forgot password?
            </a>
          </div>

          {/* Submit */}
          <button
            type="submit"
            disabled={loading || !formValid}
            className="flex w-full items-center justify-center gap-2 rounded-md bg-purple-600 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-purple-700 disabled:cursor-not-allowed disabled:opacity-50"
            aria-label="Sign in"
          >
            {loading && !ssoLoading ? (
              <Loader2 size={16} className="animate-spin" />
            ) : null}
            Sign in
          </button>

          {/* Divider */}
          <div className="my-6 flex items-center gap-3">
            <div className="h-px flex-1 bg-[#2a2d37]" />
            <span className="text-xs text-gray-500">or</span>
            <div className="h-px flex-1 bg-[#2a2d37]" />
          </div>

          {/* SSO */}
          <button
            type="button"
            onClick={() => void handleSSO()}
            disabled={loading || ssoLoading}
            className="flex w-full items-center justify-center gap-2 rounded-md border border-[#2a2d37] bg-[#0f1117] px-4 py-2.5 text-sm font-medium text-gray-300 transition hover:border-purple-500/50 hover:text-white disabled:cursor-not-allowed disabled:opacity-50"
            aria-label="Sign in with SSO"
          >
            {ssoLoading ? (
              <Loader2 size={16} className="animate-spin" />
            ) : (
              <KeyRound size={16} />
            )}
            Sign in with SSO
          </button>
        </form>

        {/* Footer */}
        <p className="mt-6 text-center text-xs text-gray-500">
          Protected by enterprise-grade security.
          <br />
          Contact your administrator for access.
        </p>
      </div>
    </div>
  );
}
