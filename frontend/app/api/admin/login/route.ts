import { NextRequest, NextResponse } from "next/server";
import { backendAdminLogin } from "../../../../lib/api";
import { mapAuthRouteError } from "../../../../lib/auth-errors";
import { sessionCookieOptions } from "../../../../lib/session-cookies";

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const password = body.password;
    if (!password || typeof password !== "string") {
      return NextResponse.json({ error: "Password is required.", code: "BAD_REQUEST" }, { status: 400 });
    }
    const result = await backendAdminLogin(password);
    const response = NextResponse.json({ authenticated: result.authenticated });
    response.cookies.set("admin_session", result.session_token, sessionCookieOptions(request, 28800));
    return response;
  } catch (error) {
    const mapped = mapAuthRouteError(error, "admin_login");
    return NextResponse.json(mapped.payload, { status: mapped.status });
  }
}
