import { NextRequest, NextResponse } from "next/server";
import { backendConfirmPasskey } from "../../../../lib/api";
import { mapAuthRouteError } from "../../../../lib/auth-errors";
import { sessionCookieOptions } from "../../../../lib/session-cookies";

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const passkey = body.passkey;
    if (!passkey || typeof passkey !== "string") {
      return NextResponse.json({ error: "Passkey is required.", code: "BAD_REQUEST" }, { status: 400 });
    }
    const result = await backendConfirmPasskey(passkey);
    const response = NextResponse.json({
      creator_id: result.creator_id,
      creator_name: result.creator_name,
    });
    response.cookies.set("eros_session", result.session_token, sessionCookieOptions(request, 7200));
    return response;
  } catch (error) {
    const mapped = mapAuthRouteError(error, "creator_confirm");
    return NextResponse.json(mapped.payload, { status: mapped.status });
  }
}
