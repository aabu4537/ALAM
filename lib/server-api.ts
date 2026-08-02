// Server-side fetch helper for Server Components and Server Actions only —
// never import this from a "use client" file. Client code fetches relative
// paths directly (the browser already carries the session cookie for
// same-origin requests); server-side code has no browser cookie jar, so it
// must forward the incoming request's Cookie header itself.
import { cookies, headers } from "next/headers";

async function resolveBaseUrl(): Promise<string> {
  if (process.env.API_BASE_URL) return process.env.API_BASE_URL;
  if (process.env.NODE_ENV !== "production") return "http://localhost:8000";
  const h = await headers();
  const host = h.get("host");
  const proto = h.get("x-forwarded-proto") ?? "https";
  return `${proto}://${host}`;
}

export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const base = await resolveBaseUrl();
  const cookieStore = await cookies();
  return fetch(`${base}${path}`, {
    ...init,
    headers: {
      ...init.headers,
      cookie: cookieStore.toString(),
    },
    cache: "no-store",
  });
}

export async function apiGetJson<T>(path: string): Promise<T> {
  const response = await apiFetch(path);
  if (!response.ok) {
    throw new ApiError(response.status, path);
  }
  return (await response.json()) as T;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public path: string,
  ) {
    super(`${path} responded ${status}`);
  }
}
