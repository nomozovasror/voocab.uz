import { apiUrl } from "@/config";

/**
 * Central API client. Every request goes through here so the wiring lives in
 * one place: credentials (the httpOnly session cookie, sent cross-origin to the
 * API subdomain), JSON (de)serialization, error normalization, network-failure
 * handling, and centralized 401 handling.
 *
 * Paths are given from the API root, e.g. `api.get("/api/auth/me")` or
 * `api.get("/api/v1/materials")` — no base path is hardcoded here.
 */

/** Thrown for network failures and non-2xx responses. `status` is 0 for a
 *  network error (request never reached the server). */
export class ApiError extends Error {
  readonly status: number;
  readonly body?: unknown;

  constructor(status: number, message: string, body?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

/** Best-effort human-readable message for any thrown value. */
export function getErrorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Something went wrong. Please try again.";
}

// --- Centralized 401 handling -------------------------------------------------
// The client can't import router/query state without a cycle, so the auth layer
// registers a handler (see AuthProvider) that clears state and redirects to
// login when the session is rejected.
type UnauthorizedHandler = () => void;
let unauthorizedHandler: UnauthorizedHandler | null = null;

export function setUnauthorizedHandler(handler: UnauthorizedHandler | null): void {
  unauthorizedHandler = handler;
}

// --- Backend-reachability signal --------------------------------------------
// A network failure (fetch throws) or a 5xx means the backend may be down — as
// opposed to a 4xx (401/403/404/422), which proves it's alive and answering.
// The connection layer registers a handler here to kick off a /health probe.
type BackendErrorHandler = () => void;
let backendErrorHandler: BackendErrorHandler | null = null;

export function setBackendErrorHandler(handler: BackendErrorHandler | null): void {
  backendErrorHandler = handler;
}

export interface RequestOptions extends Omit<RequestInit, "body"> {
  /** JSON-serializable request body; sets Content-Type automatically. */
  json?: unknown;
  /** Query params appended to the URL. */
  params?: Record<string, string | number | boolean | undefined>;
  /**
   * Treat 401 as an expected "not authenticated" result: return `null` instead
   * of firing the global session-expired handler and throwing. Used by the auth
   * probe (`/auth/me`), which is exactly how we detect a logged-out user.
   */
  expected401?: boolean;
  /**
   * Called with the response headers before the body is read, for the few
   * endpoints that answer out of band — the material editor reads the
   * material's new version back from `X-Material-Version` this way rather
   * than every authoring response having to carry it in its body.
   */
  onHeaders?: (headers: Headers) => void;
}

function buildUrl(path: string, params?: RequestOptions["params"]): string {
  const url = apiUrl(path);
  if (!params) return url;

  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) search.set(key, String(value));
  }
  const qs = search.toString();
  return qs ? `${url}?${qs}` : url;
}

async function request<T>(
  method: string,
  path: string,
  { json, params, headers, expected401, onHeaders, ...init }: RequestOptions = {},
): Promise<T> {
  let res: Response;
  try {
    res = await fetch(buildUrl(path, params), {
      method,
      // Send the httpOnly session cookie, including cross-origin to the API.
      credentials: "include",
      headers: {
        ...(json !== undefined ? { "Content-Type": "application/json" } : {}),
        ...headers,
      },
      body: json !== undefined ? JSON.stringify(json) : undefined,
      ...init,
    });
  } catch {
    // fetch only rejects on network-level failures (offline, DNS, CORS block).
    backendErrorHandler?.();
    throw new ApiError(0, "Network error. Check your connection and try again.");
  }

  onHeaders?.(res.headers);

  if (res.status === 401) {
    if (expected401) return null as T;
    unauthorizedHandler?.();
    throw new ApiError(401, "Your session has expired. Please sign in again.");
  }

  const isJson = res.headers
    .get("content-type")
    ?.includes("application/json");
  const data =
    res.status === 204
      ? undefined
      : isJson
        ? await res.json()
        : await res.text();

  if (!res.ok) {
    // 5xx → the backend is failing, not just this request. Nudge the health probe.
    if (res.status >= 500) backendErrorHandler?.();
    const message =
      (isJson && data && typeof data === "object" && "detail" in data
        ? String((data as { detail: unknown }).detail)
        : res.statusText) || "Request failed";
    throw new ApiError(res.status, message, data);
  }

  return data as T;
}

/** Typed fetch client for the backend. Paths start at the API root ("/api/..."). */
export const api = {
  get: <T>(path: string, opts?: RequestOptions) => request<T>("GET", path, opts),
  post: <T>(path: string, opts?: RequestOptions) =>
    request<T>("POST", path, opts),
  put: <T>(path: string, opts?: RequestOptions) => request<T>("PUT", path, opts),
  patch: <T>(path: string, opts?: RequestOptions) =>
    request<T>("PATCH", path, opts),
  delete: <T>(path: string, opts?: RequestOptions) =>
    request<T>("DELETE", path, opts),
};
