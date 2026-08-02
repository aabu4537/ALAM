import type { NextConfig } from "next";

// In production these same path prefixes are handled by vercel.json's
// rewrites (one Vercel project, Next.js + api/index.py — see ADR-0018).
// Locally, the Next dev server and `uvicorn` are two separate processes
// on two separate ports, so the browser's own fetches to relative paths
// (`/auth/login`, `/books`, ...) need this proxy to reach the API at all.
// Keep this list in sync with vercel.json's `rewrites` by hand — there's
// no way to share it as code across a JSON file and a TS config.
//
// Every Next.js *page* route (see app/) deliberately avoids these same
// first path segments — /library, /profile, /recommended instead of
// /books, /preferences, /recommendations. A rewrite prefix that collides
// with a dynamic page route wins silently: this array form is applied
// "before dynamic routes" (Next's own rewrites.md), and vercel.json's
// rewrites run at an even earlier, platform-level layer with no such
// escape hatch. Found this the hard way against a real deploy-shaped
// local proxy — /books/[id] 404'd because /books/:path* below ate it
// first. Renaming the frontend's routes, not reordering the rewrites,
// is what actually makes the collision structurally impossible.
const BACKEND_PATH_PREFIXES = [
  "/health",
  "/auth/:path*",
  "/books",
  "/books/:path*",
  "/demo/:path*",
  "/internal/:path*",
  "/preferences/:path*",
  "/recommendations",
  "/imports/:path*",
];

const API_ORIGIN = process.env.API_BASE_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return BACKEND_PATH_PREFIXES.map((source) => ({
      source,
      destination: `${API_ORIGIN}${source}`,
    }));
  },
};

export default nextConfig;
