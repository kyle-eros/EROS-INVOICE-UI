import { NextRequest, NextResponse } from "next/server";
import { backendConfirmPasskey } from "../../../../lib/api";

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const passkey = body.passkey;
    if (!passkey || typeof passkey !== "string") {
      return NextResponse.json({ error: "passkey required" }, { status: 400 });
    }
    const result = await backendConfirmPasskey(passkey);
    const response = NextResponse.json({
      creator_id: result.creator_id,
      creator_name: result.creator_name,
    });
    response.cookies.set("eros_session", result.session_token, {
      httpOnly: true,
      secure: process.env.COOKIE_SECURE !== "false",
      sameSite: "strict",
      maxAge: 7200,
      path: "/",
    });
    return response;
  } catch (error) {
    const message = error instanceof Error ? error.message : "confirm failed";
    const status = message.includes("401") ? 401 : message.includes("429") ? 429 : 500;
    return NextResponse.json({ error: message }, { status });
  }
}
