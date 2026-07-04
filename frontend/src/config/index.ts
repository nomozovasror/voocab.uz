/**
 * App-wide configuration. Values come from Vite env vars (VITE_*) with sane
 * defaults for local dev, where Vite proxies `/api` to the FastAPI backend.
 */
export const config = {
  /** Base path for all API requests; feature clients build on top of this. */
  apiBaseUrl: import.meta.env.VITE_API_BASE_URL ?? "/api/v1",
  appName: "voocab",
} as const;
