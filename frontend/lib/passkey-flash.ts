export const ADMIN_PASSKEY_FLASH_COOKIE = "admin_passkey_flash";

export interface AdminPasskeyFlashPayload {
  creator_name: string;
  passkey: string;
}

function parseSecureCookieEnv(value: string | undefined): boolean {
  if (!value) {
    return false;
  }
  const normalized = value.trim().toLowerCase();
  return normalized === "true" || normalized === "1" || normalized === "yes" || normalized === "on";
}

export function adminPasskeyFlashCookieOptions(maxAge: number) {
  return {
    httpOnly: true,
    secure: parseSecureCookieEnv(process.env.COOKIE_SECURE),
    sameSite: "strict" as const,
    maxAge,
    path: "/admin",
  };
}

export function encodeAdminPasskeyFlash(payload: AdminPasskeyFlashPayload): string {
  return Buffer.from(JSON.stringify(payload), "utf-8").toString("base64url");
}

export function decodeAdminPasskeyFlash(value: string): AdminPasskeyFlashPayload | null {
  try {
    const parsed = JSON.parse(Buffer.from(value, "base64url").toString("utf-8")) as Record<string, unknown>;
    const creator = parsed.creator_name;
    const passkey = parsed.passkey;
    if (typeof creator !== "string" || !creator.trim()) {
      return null;
    }
    if (typeof passkey !== "string" || !passkey.trim()) {
      return null;
    }
    return { creator_name: creator, passkey };
  } catch {
    return null;
  }
}
