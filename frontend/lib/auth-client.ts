import type { AuthErrorCode, AuthErrorEnvelope } from "./auth-errors";

interface PostAuthJsonOptions {
  signal?: AbortSignal;
  fallbackMessage?: string;
}

function toRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object") {
    return null;
  }
  return value as Record<string, unknown>;
}

function isAuthErrorCode(value: unknown): value is AuthErrorCode {
  return value === "BAD_REQUEST" ||
    value === "INVALID_CREDENTIALS" ||
    value === "RATE_LIMITED" ||
    value === "SERVICE_UNAVAILABLE" ||
    value === "SERVER_ERROR";
}

function toAuthErrorEnvelope(value: unknown): AuthErrorEnvelope | null {
  const payload = toRecord(value);
  if (!payload) {
    return null;
  }
  const error = payload.error;
  if (typeof error !== "string" || !error.trim()) {
    return null;
  }
  const code = payload.code;
  return {
    error,
    code: isAuthErrorCode(code) ? code : undefined,
  };
}

export class AuthClientError extends Error {
  readonly code?: AuthErrorCode;

  constructor(message: string, code?: AuthErrorCode) {
    super(message);
    this.name = "AuthClientError";
    this.code = code;
  }
}

export function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

export async function postAuthJson<T>(
  endpoint: string,
  body: Record<string, unknown>,
  { signal, fallbackMessage = "Unable to continue right now. Please try again." }: PostAuthJsonOptions = {},
): Promise<T> {
  const response = await fetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });

  let parsedBody: unknown = null;
  try {
    parsedBody = await response.json();
  } catch {
    parsedBody = null;
  }

  if (!response.ok) {
    const envelope = toAuthErrorEnvelope(parsedBody);
    throw new AuthClientError(envelope?.error ?? fallbackMessage, envelope?.code);
  }

  const payload = toRecord(parsedBody);
  if (!payload) {
    throw new AuthClientError("Unexpected response from server.", "SERVER_ERROR");
  }

  return payload as T;
}
