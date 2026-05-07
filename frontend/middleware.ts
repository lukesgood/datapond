import { NextResponse } from "next/server"
import type { NextRequest } from "next/server"

const PUBLIC_PATHS = ["/login", "/api/auth/login"]

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl

  // Allow public paths and static assets
  if (
    PUBLIC_PATHS.some(p => pathname.startsWith(p)) ||
    pathname.startsWith("/_next") ||
    pathname.startsWith("/favicon") ||
    pathname.startsWith("/icons") ||
    pathname.startsWith("/connectors")  // connector SVG icons
  ) {
    return NextResponse.next()
  }

  // Check for auth token in cookie or Authorization header
  const token =
    request.cookies.get("datapond_token")?.value ||
    request.headers.get("authorization")?.replace("Bearer ", "")

  // For page routes (not API), redirect to login if no token
  if (!token && !pathname.startsWith("/api/")) {
    const url = request.nextUrl.clone()
    url.pathname = "/login"
    return NextResponse.redirect(url)
  }

  return NextResponse.next()
}

export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico).*)",
  ],
}
