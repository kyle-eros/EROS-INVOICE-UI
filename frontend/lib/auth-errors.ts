export type AuthErrorCode =
  | "BAD_REQUEST"
  | "INVALID_CREDENTIALS"
  | "RATE_LIMITED"
  | "SERVICE_UNAVAILABLE"
  | "SERVER_ERROR";

export interface AuthErrorEnvelope {
  error: string;
  code?: AuthErrorCode;
}

export type AuthRouteContext = "creator_lookup" | "creator_confirm" | "admin_login";

interface AuthRouteError {
  status: number;
  payload: AuthErrorEnvelope;
}

function toRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object") {
    return null;
  }
  return value as Record<string, unknown>;
}

function readErrorStatus(error: unknown): number | null {
  const candidate = toRecord(error);
  if (!candidate) {
    return null;
  }
  const status = candidate.status;
  return typeof status === "number" ? status : null;
}

function readErrorMessage(error: unknown): string | null {
  if (error instanceof Error && error.message.trim()) {
    return error.message;
  }
  const candidate = toRecord(error);
  if (!candidate) {
    return null;
  }
  const message = candidate.message;
  return typeof message === "string" && message.trim() ? message : null;
}

function mapAuthStatus(status: number): number {
  if (status === 502 || status === 504) {
    return 503;
  }
  return status;
}

function creatorCredentialMessage(rawMessage: string | null): string {
  const normalized = (rawMessage ?? "").toLowerCase();
  if (normalized.includes("revoked")) {
    return "This passkey has been revoked. Contact your agency.";
  }
  return "Invalid passkey.";
}

function contextMessage(context: AuthRouteContext, status: number, rawMessage: string | null): AuthRouteError {
  if (context === "admin_login") {
    if (status === 400) {
      return { status: 400, payload: { error: "Password is required.", code: "BAD_REQUEST" } };
    }
    if (status === 401) {
      return { status: 401, payload: { error: "Invalid password.", code: "INVALID_CREDENTIALS" } };
    }
    if (status === 429) {
      return { status: 429, payload: { error: "Too many login attempts. Please try again later.", code: "RATE_LIMITED" } };
    }
    if (status === 503) {
      return { status: 503, payload: { error: "Admin sign-in is temporarily unavailable. Please try again shortly.", code: "SERVICE_UNAVAILABLE" } };
    }
    return { status: 500, payload: { error: "Unable to complete admin sign-in right now. Please try again.", code: "SERVER_ERROR" } };
  }

  if (status === 400) {
    return { status: 400, payload: { error: "Passkey is required.", code: "BAD_REQUEST" } };
  }
  if (status === 401) {
    return { status: 401, payload: { error: creatorCredentialMessage(rawMessage), code: "INVALID_CREDENTIALS" } };
  }
  if (status === 429) {
    return { status: 429, payload: { error: "Too many login attempts. Please try again later.", code: "RATE_LIMITED" } };
  }
  if (status === 503) {
    return { status: 503, payload: { error: "Sign-in is temporarily unavailable. Please try again shortly.", code: "SERVICE_UNAVAILABLE" } };
  }
  return { status: 500, payload: { error: "Unable to sign in right now. Please try again.", code: "SERVER_ERROR" } };
}

export function mapAuthRouteError(error: unknown, context: AuthRouteContext): AuthRouteError {
  const rawStatus = readErrorStatus(error) ?? 500;
  const status = mapAuthStatus(rawStatus);
  const rawMessage = readErrorMessage(error);
  return contextMessage(context, status, rawMessage);
}

