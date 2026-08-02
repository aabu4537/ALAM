// Next.js 16 renamed Middleware to Proxy (same file convention as
// `middleware.ts` in earlier versions — see next/dist/docs/01-app/
// 01-getting-started/16-proxy.md).
//
// This is a UX convenience only, not the security boundary: it checks that
// `alam_session` is *present*, never verifies the HMAC signature (the
// signing key is a backend secret this file never sees). The real
// enforcement is `require_owner_session` on every owner-scoped FastAPI
// route (ADR-0017) — a forged or expired cookie still 401s there. This
// only exists so a logged-out visitor lands on /login instead of a page
// full of failed fetches.
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const SESSION_COOKIE = "alam_session";
const PUBLIC_PATHS = new Set(["/login"]);

export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;

  if (PUBLIC_PATHS.has(pathname) || pathname.startsWith("/_next")) {
    return NextResponse.next();
  }

  const hasSession = request.cookies.has(SESSION_COOKIE);
  if (!hasSession) {
    const loginUrl = new URL("/login", request.url);
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
}

export const config = {
  // Only the Next.js pages this proxy actually governs. Every backend
  // path (auth, books, demo, internal, preferences, recommendations,
  // imports, health) is proxied straight to api/index.py by vercel.json
  // and enforces its own session check server-side; running this proxy
  // against them too would just add a redundant cookie-presence check.
  //
  // Deliberately distinct first path segments from every backend router
  // prefix (see next.config.ts) — /library, /profile, and /recommended,
  // not /books, /preferences, or /recommendations. A shared prefix with a
  // dynamic Next.js route (e.g. /books/[id]) gets silently swallowed by
  // the backend rewrite before Next's own router ever sees it, found the
  // hard way this session against a real deploy-shaped local proxy.
  matcher: ["/", "/import", "/library/:path*", "/profile", "/recommended"],
};
