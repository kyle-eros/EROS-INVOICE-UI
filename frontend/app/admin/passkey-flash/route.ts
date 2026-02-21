import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import {
  ADMIN_PASSKEY_FLASH_COOKIE,
  adminPasskeyFlashCookieOptions,
  decodeAdminPasskeyFlash,
} from "../../../lib/passkey-flash";

export async function GET() {
  const cookieStore = await cookies();
  const hasAdminSession = Boolean(cookieStore.get("admin_session")?.value);
  const raw = cookieStore.get(ADMIN_PASSKEY_FLASH_COOKIE)?.value;
  const decoded = hasAdminSession && raw ? decodeAdminPasskeyFlash(raw) : null;

  const response = NextResponse.json(
    decoded
      ? { creator_id: decoded.creator_id, creator_name: decoded.creator_name, passkey: decoded.passkey }
      : { creator_id: null, creator_name: null, passkey: null },
    { status: 200 },
  );

  response.cookies.set(
    ADMIN_PASSKEY_FLASH_COOKIE,
    "",
    {
      ...adminPasskeyFlashCookieOptions(0),
      maxAge: 0,
    },
  );
  return response;
}
