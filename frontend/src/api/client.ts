// Base fetch wrapper for the dashboard API. Deliberately plain `fetch`,
// no axios/ky -- one small wrapper is enough surface area for ~12
// endpoints; a full HTTP client library would be over-engineering for
// this phase's actual needs.

// 127.0.0.1, NOT "localhost" -- on this project's dev machine, "localhost"
// resolves via IPv6 first and lands on an unrelated stray process that
// happens to also be listening on [::1]:8000, not this project's backend
// (which only binds IPv4). Using the literal IPv4 address sidesteps that
// resolution order entirely rather than depending on it.
export const API_BASE_URL: string =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "http://127.0.0.1:8000/api/v1";

export const WS_BASE_URL: string =
  (import.meta.env.VITE_WS_BASE_URL as string | undefined) ?? "ws://127.0.0.1:8000/api/v1";

export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, detail: unknown) {
    super(`API error ${status}: ${JSON.stringify(detail)}`);
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });

  if (!response.ok) {
    let detail: unknown;
    try {
      detail = await response.json();
    } catch {
      detail = await response.text();
    }
    throw new ApiError(response.status, detail);
  }

  return response.json() as Promise<T>;
}

export function apiGet<T>(path: string, params?: Record<string, string | number | undefined>): Promise<T> {
  const query = params
    ? "?" +
      new URLSearchParams(
        Object.entries(params)
          .filter(([, v]) => v !== undefined)
          .map(([k, v]) => [k, String(v)]),
      ).toString()
    : "";
  return request<T>(`${path}${query}`, { method: "GET" });
}

export function apiPost<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, { method: "POST", body: JSON.stringify(body) });
}

export async function apiGetBlob(path: string, params?: Record<string, string>): Promise<Blob> {
  const query = params ? "?" + new URLSearchParams(params).toString() : "";
  const response = await fetch(`${API_BASE_URL}${path}${query}`);
  if (!response.ok) {
    throw new ApiError(response.status, await response.text());
  }
  return response.blob();
}
