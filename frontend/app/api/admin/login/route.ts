import { NextRequest, NextResponse } from "next/server";
import { backendAdminLogin } from "../../../../lib/api";

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const password = body.password;
    if (!password || typeof password !== "string") {
      return NextResponse.json({ error: "password required" }, { status: 400 });
    }
    const result = await backendAdminLogin(password);
    const response = NextResponse.json({ authenticated: result.authenticated });
    response.cookies.set("admin_session", result.session_token, {
      httpOnly: true,
      secure: process.env.COOKIE_SECURE !== "false",
      sameSite: "strict",
      maxAge: 28800,
      path: "/",
    });
    return response;
  } catch (error) {
    const message = error instanceof Error ? error.message : "login failed";
    const status = message.includes("401") ? 401 : message.includes("503") ? 503 : 500;
    return NextResponse.json({ error: message }, { status });
  }
}
