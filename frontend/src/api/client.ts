/**
 * Thin fetch wrapper. All requests go through /api (Vite dev proxy → :8000;
 * in docker the same prefix is nginx-routed). Throws ApiError on non-2xx so
 * TanStack Query lands in error state with a usable message.
 */

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

const BASE = "/api";

export async function apiGet<T>(path: string, params?: Record<string, string | number | undefined>): Promise<T> {
  const url = new URL(BASE + path, window.location.origin);
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== "") url.searchParams.set(k, String(v));
    }
  }
  const resp = await fetch(url);
  if (!resp.ok) throw new ApiError(resp.status, `${resp.status} ${resp.statusText} — GET ${path}`);
  return resp.json() as Promise<T>;
}

export async function apiSend<T>(method: "POST" | "PATCH", path: string, body: unknown): Promise<T> {
  const resp = await fetch(BASE + path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new ApiError(resp.status, `${resp.status} ${resp.statusText} — ${method} ${path}`);
  return resp.json() as Promise<T>;
}
