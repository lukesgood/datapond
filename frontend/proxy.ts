import { NextResponse } from "next/server"
import type { NextRequest } from "next/server"

const PUBLIC_PATHS = [
  "/login", "/forgot", "/reset",   // pre-auth pages (you're locked out of your account)
  "/api/auth/login", "/api/auth/forgot-password", "/api/auth/reset-password",
  "/api/auth/oidc", "/api/capabilities",
]

export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl

  // Allow public paths and static assets
  if (
    PUBLIC_PATHS.some(p => pathname.startsWith(p)) ||
    pathname.startsWith("/_next") ||
    pathname.startsWith("/favicon") ||
    pathname.startsWith("/icons") ||
    // Connector logos only. A bare startsWith("/connectors") let every Sources page
    // (/connectors/connections/<id>) render without a session.
    (pathname.startsWith("/connectors/") && pathname.endsWith(".svg"))
  ) {
    return NextResponse.next()
  }

  // Check for auth token in cookie or Authorization header
  const token =
    request.cookies.get("datapond_token")?.value ||
    request.headers.get("authorization")?.replace("Bearer ", "")

  // For page routes (not API), redirect to login if no token
  if (!token && !pathname.startsWith("/api/")) {
    // Back to this page after signing in. The query moves into ?next=; left on the
    // URL it landed on /login itself (/metrics?tab=joins -> /login?tab=joins).
    const url = request.nextUrl.clone()
    const here = pathname + request.nextUrl.search
    url.pathname = "/login"
    url.search = here === "/" ? "" : `?next=${encodeURIComponent(here)}`
    return NextResponse.redirect(url)
  }

  return NextResponse.next()
}

export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico).*)",
  ],
}
