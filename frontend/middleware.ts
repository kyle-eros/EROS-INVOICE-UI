import { NextRequest, NextResponse } from "next/server";

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  if (pathname.startsWith("/admin") && !pathname.startsWith("/admin/gate")) {
    if (!request.cookies.get("admin_session")?.value) {
      return NextResponse.redirect(new URL("/admin/gate", request.url));
    }
  }

  if (pathname.startsWith("/portal")) {
    if (!request.cookies.get("eros_session")?.value) {
      return NextResponse.redirect(new URL("/login", request.url));
    }
  }

  return NextResponse.next();
}

export const config = { matcher: ["/admin/:path*", "/portal/:path*"] };
