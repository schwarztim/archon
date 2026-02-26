import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from "react";
import { useAuth } from "@/providers/auth-provider";
import { ShieldCheck, Loader2, AlertCircle, ArrowLeft } from "lucide-react";
import type { MFAMethod } from "@/types/auth";

const CODE_LENGTH = 6;

export function MFAChallengePage() {
  const { verifyMFA, mfaChallenge, loading, error, clearMFAChallenge } =
    useAuth();
  const [digits, setDigits] = useState<string[]>(Array(CODE_LENGTH).fill(""));
  const [method, setMethod] = useState<MFAMethod>("totp");
  const [rememberDevice, setRememberDevice] = useState(false);
  const [recoveryCode, setRecoveryCode] = useState("");
  const [timeRemaining, setTimeRemaining] = useState<number | null>(null);
  const inputRefs = useRef<(HTMLInputElement | null)[]>([]);

  const expiresAt = mfaChallenge?.expires_at;

  // ── Countdown timer ────────────────────────────────────────────────
  useEffect(() => {
    if (!expiresAt) return;

    function tick() {
      const remaining = Math.max(
        0,
        Math.floor((new Date(expiresAt!).getTime() - Date.now()) / 1000),
      );
      setTimeRemaining(remaining);
    }

    tick();
    const interval = setInterval(tick, 1000);
    return () => clearInterval(interval);
  }, [expiresAt]);

  // ── Auto-submit when all digits entered ────────────────────────────
  const submitCode = useCallback(
    async (code: string) => {
      await verifyMFA(code, "totp", rememberDevice);
    },
    [verifyMFA, rememberDevice],
  );

  // ── Handle digit input ─────────────────────────────────────────────
  function handleDigitChange(index: number, value: string) {
    if (!/^\d*$/.test(value)) return;

    const newDigits = [...digits];

    if (value.length > 1) {
      // Handle paste: distribute across inputs
      const chars = value.slice(0, CODE_LENGTH).split("");
      for (let i = 0; i < chars.length && index + i < CODE_LENGTH; i++) {
        newDigits[index + i] = chars[i] ?? "";
      }
      setDigits(newDigits);

      const nextIdx = Math.min(index + chars.length, CODE_LENGTH - 1);
      inputRefs.current[nextIdx]?.focus();

      if (newDigits.every((d) => d !== "")) {
        void submitCode(newDigits.join(""));
      }
      return;
    }

    newDigits[index] = value;
    setDigits(newDigits);

    if (value && index < CODE_LENGTH - 1) {
      inputRefs.current[index + 1]?.focus();
    }

    if (newDigits.every((d) => d !== "")) {
      void submitCode(newDigits.join(""));
    }
  }

  function handleKeyDown(index: number, e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Backspace" && !digits[index] && index > 0) {
      inputRefs.current[index - 1]?.focus();
    }
  }

  // ── Recovery code submit ───────────────────────────────────────────
  async function handleRecoverySubmit() {
    if (!recoveryCode.trim()) return;
    await verifyMFA(recoveryCode.trim(), "recovery_code", rememberDevice);
  }

  // ── Format time ────────────────────────────────────────────────────
  function formatTime(seconds: number): string {
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return `${m}:${String(s).padStart(2, "0")}`;
  }

  const expired = timeRemaining !== null && timeRemaining <= 0;

  return (
    <div className="flex min-h-screen items-center justify-center bg-surface-base px-4">
      <div className="w-full max-w-md">
        {/* Header */}
        <div className="mb-8 text-center">
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-xl bg-purple-600/20">
            <ShieldCheck size={28} className="text-purple-400" />
          </div>
          <h1 className="text-2xl font-bold text-white">
            {method === "totp"
              ? "Two-Factor Authentication"
              : "Recovery Code"}
          </h1>
          <p className="mt-1 text-sm text-gray-400">
            {method === "totp"
              ? "Enter the 6-digit code from your authenticator app."
              : "Enter one of your recovery codes."}
          </p>
        </div>

        {/* Error */}
        {error && (
          <div
            className="mb-4 flex items-start gap-3 rounded-lg border border-red-500/30 bg-red-500/10 p-3"
            role="alert"
          >
            <AlertCircle size={18} className="mt-0.5 shrink-0 text-red-400" />
            <p className="text-sm text-red-300">{error}</p>
          </div>
        )}

        {/* Expired */}
        {expired && (
          <div
            className="mb-4 flex items-start gap-3 rounded-lg border border-yellow-500/30 bg-yellow-500/10 p-3"
            role="alert"
          >
            <AlertCircle
              size={18}
              className="mt-0.5 shrink-0 text-yellow-400"
            />
            <p className="text-sm text-yellow-300">
              This challenge has expired. Please sign in again.
            </p>
          </div>
        )}

        <div className="rounded-lg border border-surface-border bg-surface-raised p-6">
          {method === "totp" ? (
            <>
              {/* TOTP Code Input */}
              <div
                className="mb-4 flex justify-center gap-2"
                role="group"
                aria-label="Verification code"
              >
                {digits.map((digit, i) => (
                  <input
                    key={i}
                    ref={(el) => {
                      inputRefs.current[i] = el;
                    }}
                    type="text"
                    inputMode="numeric"
                    maxLength={CODE_LENGTH}
                    value={digit}
                    onChange={(e) => handleDigitChange(i, e.target.value)}
                    onKeyDown={(e) => handleKeyDown(i, e)}
                    disabled={loading || expired}
                    className="h-12 w-10 rounded-md border border-surface-border bg-surface-base text-center text-lg font-mono text-white outline-none transition focus:border-purple-500 focus:ring-2 focus:ring-purple-500 disabled:opacity-50"
                    aria-label={`Digit ${i + 1}`}
                    autoFocus={i === 0}
                  />
                ))}
              </div>

              {/* Timer */}
              {timeRemaining !== null && !expired && (
                <p className="mb-4 text-center text-xs text-gray-500">
                  Code expires in{" "}
                  <span className="font-mono text-gray-400">
                    {formatTime(timeRemaining)}
                  </span>
                </p>
              )}

              {/* Loading */}
              {loading && (
                <div className="mb-4 flex items-center justify-center gap-2">
                  <Loader2 size={16} className="animate-spin text-purple-400" />
                  <span className="text-sm text-gray-400">Verifying…</span>
                </div>
              )}
            </>
          ) : (
            <>
              {/* Recovery Code Input */}
              <div className="mb-4">
                <label
                  htmlFor="recovery-code"
                  className="mb-1.5 block text-sm font-medium text-gray-300"
                >
                  Recovery Code
                </label>
                <input
                  id="recovery-code"
                  type="text"
                  value={recoveryCode}
                  onChange={(e) => setRecoveryCode(e.target.value)}
                  disabled={loading || expired}
                  className="w-full rounded-md border border-surface-border bg-surface-base px-3 py-2 font-mono text-sm text-white placeholder-gray-500 outline-none transition focus:ring-2 focus:ring-purple-500"
                  placeholder="xxxx-xxxx-xxxx"
                  autoFocus
                  aria-label="Recovery code"
                />
              </div>
              <button
                type="button"
                onClick={() => void handleRecoverySubmit()}
                disabled={loading || expired || !recoveryCode.trim()}
                className="flex w-full items-center justify-center gap-2 rounded-md bg-purple-600 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-purple-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {loading ? (
                  <Loader2 size={16} className="animate-spin" />
                ) : null}
                Verify Recovery Code
              </button>
            </>
          )}

          {/* Remember Device */}
          <div className="mt-4 border-t border-surface-border pt-4">
            <label className="flex items-center gap-2 text-sm text-gray-400">
              <input
                type="checkbox"
                checked={rememberDevice}
                onChange={(e) => setRememberDevice(e.target.checked)}
                className="h-4 w-4 rounded border-gray-600 bg-surface-base text-purple-600 focus:ring-purple-500"
                disabled={loading || expired}
              />
              Remember this device for 30 days
            </label>
          </div>

          {/* Toggle Method */}
          <div className="mt-4 text-center">
            {method === "totp" ? (
              <button
                type="button"
                onClick={() => setMethod("recovery_code")}
                className="text-sm text-purple-400 hover:text-purple-300"
                disabled={loading}
              >
                Use a recovery code instead
              </button>
            ) : (
              <button
                type="button"
                onClick={() => {
                  setMethod("totp");
                  setRecoveryCode("");
                }}
                className="text-sm text-purple-400 hover:text-purple-300"
                disabled={loading}
              >
                Use authenticator app
              </button>
            )}
          </div>
        </div>

        {/* Back to login */}
        <div className="mt-4 text-center">
          <button
            type="button"
            onClick={clearMFAChallenge}
            className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-300"
          >
            <ArrowLeft size={14} />
            Back to sign in
          </button>
        </div>
      </div>
    </div>
  );
}
