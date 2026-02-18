import type { NextRequest } from "next/server";

function parseCookieSecureOverride(value: string | undefined): boolean | null {
  if (!value) {
    return null;
  }

  const normalized = value.trim().toLowerCase();
  if (normalized === "true" || normalized === "1" || normalized === "yes" || normalized === "on") {
    return true;
  }
  if (normalized === "false" || normalized === "0" || normalized === "no" || normalized === "off") {
    return false;
  }
  return null;
}

export function resolveSecureCookie(request: NextRequest): boolean {
  const override = parseCookieSecureOverride(process.env.COOKIE_SECURE);
  if (override !== null) {
    return override;
  }

  const forwardedProto = request.headers.get("x-forwarded-proto");
  if (forwardedProto) {
    const primaryProto = forwardedProto.split(",")[0]?.trim().toLowerCase();
    if (primaryProto === "https") {
      return true;
    }
    if (primaryProto === "http") {
      return false;
    }
  }

  return request.nextUrl.protocol === "https:";
}

export function sessionCookieOptions(request: NextRequest, maxAge: number) {
  return {
    httpOnly: true,
    secure: resolveSecureCookie(request),
    sameSite: "strict" as const,
    maxAge,
    path: "/",
  };
}
