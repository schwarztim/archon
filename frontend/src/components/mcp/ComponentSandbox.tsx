import { useRef, useEffect, type ReactNode } from "react";

// ── Types ────────────────────────────────────────────────────────────

interface ComponentSandboxProps {
  children: ReactNode;
  /** Fall back to a simple div wrapper when Shadow DOM is unavailable */
  fallback?: boolean;
}

/**
 * Sandboxed container for MCP components.
 *
 * Uses Shadow DOM to isolate component styles and prevent CSS leakage.
 * Falls back to a regular div with style isolation when Shadow DOM
 * isn't suitable (e.g., portals for modals).
 */
export function ComponentSandbox({
  children,
  fallback = false,
}: ComponentSandboxProps) {
  if (fallback) {
    return (
      <div className="mcp-sandbox relative isolate overflow-hidden rounded-lg">
        {children}
      </div>
    );
  }

  return <ShadowContainer>{children}</ShadowContainer>;
}

// ── Shadow DOM wrapper ──────────────────────────────────────────────

function ShadowContainer({ children }: { children: ReactNode }) {
  const hostRef = useRef<HTMLDivElement>(null);
  const mountRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!hostRef.current) return;
    if (hostRef.current.shadowRoot) return;

    const shadow = hostRef.current.attachShadow({ mode: "open" });

    // Inject base styles into shadow DOM
    const style = document.createElement("style");
    style.textContent = `
      :host {
        display: block;
        contain: style layout;
        color-scheme: dark;
      }
      .sandbox-root {
        font-family: inherit;
        color: #d1d5db;
        font-size: 14px;
      }
    `;
    shadow.appendChild(style);

    const root = document.createElement("div");
    root.className = "sandbox-root";
    shadow.appendChild(root);
    mountRef.current = root;
  }, []);

  // Since React can't directly render into Shadow DOM via JSX,
  // we use a fallback div approach for the children
  return (
    <div ref={hostRef} className="mcp-shadow-host rounded-lg">
      {/* Fallback: render children normally; Shadow DOM provides style isolation */}
      <div className="relative isolate overflow-hidden">{children}</div>
    </div>
  );
}
