import { NextRequest, NextResponse } from "next/server";
import { sessionCookieOptions } from "../../../../lib/session-cookies";

export async function POST(request: NextRequest) {
  const response = NextResponse.json({ ok: true });
  response.cookies.set("admin_session", "", sessionCookieOptions(request, 0));
  return response;
}
