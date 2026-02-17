import { NextResponse } from "next/server";

export async function POST() {
  const response = NextResponse.json({ ok: true });
  response.cookies.set("eros_session", "", {
    httpOnly: true,
    secure: process.env.COOKIE_SECURE !== "false",
    sameSite: "strict",
    maxAge: 0,
    path: "/",
  });
  return response;
}
