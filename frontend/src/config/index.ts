/**
 * App-wide configuration. Values come from Vite env vars (VITE_*).
 *
 * VITE_API_BASE is the backend origin:
 *   - dev  → http://localhost:8000 (see .env.development), a different origin
 *            than the Vite dev server, so the real CORS + cookie path is used.
 *   - prod → https://api.voocab.uz (set in the Cloudflare Pages build env).
 * Leaving it empty falls back to the same origin (requests hit "/api/..."),
 * which is handy behind a reverse proxy.
 */

// Trailing slash trimmed so we can safely concatenate paths.
const apiBase = (import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");

export const config = {
  /** Backend origin ("" = same origin). All API paths are built on top. */
  apiBase,
  appName: "voocab",
} as const;

/** Build an absolute (or same-origin) URL to a backend path like "/api/auth/me". */
export function apiUrl(path: string): string {
  return `${apiBase}${path.startsWith("/") ? path : `/${path}`}`;
}
