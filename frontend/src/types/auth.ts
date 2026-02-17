import type { UUID, ISODateString } from "./models";

// ─── User & Session ──────────────────────────────────────────────────

export interface User {
  id: UUID;
  email: string;
  name: string;
  roles: string[];
  permissions: string[];
  tenant_id: UUID;
  workspace_id: UUID;
  mfa_enabled: boolean;
}

export interface SessionInfo {
  user: User;
  access_token: string;
  expires_at: ISODateString;
  issued_at: ISODateString;
  refresh_token_expires_at: ISODateString;
}

// ─── Login ───────────────────────────────────────────────────────────

export interface LoginRequest {
  email: string;
  password: string;
  remember_me?: boolean;
}

export interface LoginResponse {
  data: SessionInfo | MFAChallenge;
  meta: {
    request_id: string;
    timestamp: string;
  };
}

// ─── MFA ─────────────────────────────────────────────────────────────

export interface MFAChallenge {
  mfa_required: true;
  mfa_token: string;
  mfa_methods: MFAMethod[];
  expires_at: ISODateString;
}

export type MFAMethod = "totp" | "recovery_code";

export interface MFAVerifyRequest {
  mfa_token: string;
  code: string;
  method: MFAMethod;
  remember_device?: boolean;
}

// ─── SSO ─────────────────────────────────────────────────────────────

export type SSOProvider = "saml" | "oidc";

export interface SSOLoginRequest {
  provider: SSOProvider;
  idp_hint?: string;
}

// ─── Auth Context ────────────────────────────────────────────────────

export interface AuthContextType {
  user: User | null;
  loading: boolean;
  error: string | null;
  mfaChallenge: MFAChallenge | null;
  login: (email: string, password: string, rememberMe?: boolean) => Promise<void>;
  loginSSO: (provider: SSOProvider, idpHint?: string) => Promise<void>;
  logout: () => Promise<void>;
  refreshSession: () => Promise<void>;
  hasPermission: (permission: string) => boolean;
  hasRole: (role: string) => boolean;
  verifyMFA: (code: string, method: MFAMethod, rememberDevice?: boolean) => Promise<void>;
  clearMFAChallenge: () => void;
}

// ─── API Error ───────────────────────────────────────────────────────

export interface AuthApiError {
  errors: Array<{
    code: string;
    message: string;
    field?: string;
    details?: Record<string, unknown>;
  }>;
  meta: {
    request_id: string;
    timestamp: string;
  };
}

/** Type guard: check if a login response requires MFA */
export function isMFAChallenge(
  data: SessionInfo | MFAChallenge,
): data is MFAChallenge {
  return "mfa_required" in data && data.mfa_required === true;
}
