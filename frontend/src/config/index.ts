/**
 * App-wide configuration. Values come from Vite env vars (VITE_*) with sane
 * defaults for local dev, where Vite proxies `/api` to the FastAPI backend.
 */

// Origin of the backend API. In production the API lives on its own subdomain
// (e.g. https://api.voocab.uz); locally it's left empty so requests hit the
// same origin and Vite's dev proxy forwards `/api` to the backend. Trailing
// slash trimmed so we can safely concatenate paths.
const apiBase = (import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");

export const config = {
  /** Backend origin ("" = same origin via the dev proxy). */
  apiBase,
  /** Base path for versioned API requests; feature clients build on top. */
  apiBaseUrl: `${apiBase}/api/v1`,
  appName: "voocab",
} as const;

/** Build an absolute (or same-origin) URL to a backend path like "/api/auth/me". */
export function apiUrl(path: string): string {
  return `${apiBase}${path.startsWith("/") ? path : `/${path}`}`;
}
