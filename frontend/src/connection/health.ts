import { apiUrl } from "@/config";

/**
 * Probe the backend's public health endpoint. Returns true only on a 2xx.
 *
 * Deliberately a raw fetch (not the shared api client) so it never re-triggers
 * the backend-error handler and can't recurse. A 4xx here would still count as
 * "not healthy", but /health has no auth and shouldn't 4xx — the real signals
 * we care about are network failure / timeout / 5xx.
 */
export async function checkHealth(timeoutMs = 4000): Promise<boolean> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(apiUrl("/health"), {
      method: "GET",
      credentials: "omit",
      cache: "no-store",
      signal: controller.signal,
    });
    return res.ok;
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}
