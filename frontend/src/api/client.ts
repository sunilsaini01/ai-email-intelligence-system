// Base fetch wrapper for the dashboard API. Deliberately plain `fetch`,
// no axios/ky -- one small wrapper is enough surface area for ~12
// endpoints; a full HTTP client library would be over-engineering for
// this phase's actual needs.

// 127.0.0.1, NOT "localhost" -- on this project's dev machine, "localhost"
// resolves via IPv6 first and lands on an unrelated stray process that
// happens to also be listening on [::1]:8000, not this project's backend
// (which only binds IPv4). Using the literal IPv4 address sidesteps that
// resolution order entirely rather than depending on it.
export const API_BASE_URL = (
          import.meta.env.VITE_API_BASE_URL ??
          "http://127.0.0.1:8001/api/v1"
        ).replace(/\/$/, "");


export const WS_BASE_URL = (
          import.meta.env.VITE_WS_BASE_URL ??
          "ws://127.0.0.1:8001/api/v1"
        ).replace(/\/$/, "");

export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, detail: unknown) {
    super(`API error ${status}: ${JSON.stringify(detail)}`);
    this.status = status;
    this.detail = detail;
  }
}

// Phase 17 (real authentication): every business endpoint now requires a
// Bearer token (see backend app/api/v1/router.py's protected_router). The
// token lives in localStorage, not React state, so this module -- which
// has no React dependency -- can read it on every request without a
// circular import back to hooks/useAuth.tsx.
const TOKEN_STORAGE_KEY = "eis_auth_token";

export function getAuthToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_STORAGE_KEY);
  } catch {
    return null;
  }
}

export function setAuthToken(token: string | null): void {
  try {
    if (token) localStorage.setItem(TOKEN_STORAGE_KEY, token);
    else localStorage.removeItem(TOKEN_STORAGE_KEY);
  } catch {
    // Storage disabled (private browsing, etc.) -- the session just
    // won't survive a reload; not worth failing the request over.
  }
}

// A 401 here means the token is missing, expired, or was revoked
// server-side (e.g. is_active flipped false) -- broadcast it as a DOM
// event rather than importing useAuth directly, so this file stays a
// plain, React-free fetch wrapper. hooks/useAuth.tsx listens for this.
export const AUTH_UNAUTHORIZED_EVENT = "eis:auth-unauthorized";

function authHeaders(): Record<string, string> {
  const token = getAuthToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
      ...(init?.headers ?? {}),
    },
  });

  if (response.status === 401) {
    window.dispatchEvent(new Event(AUTH_UNAUTHORIZED_EVENT));
  }

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
  const response = await fetch(`${API_BASE_URL}${path}${query}`, { headers: authHeaders() });
  if (response.status === 401) {
    window.dispatchEvent(new Event(AUTH_UNAUTHORIZED_EVENT));
  }
  if (!response.ok) {
    throw new ApiError(response.status, await response.text());
  }
  return response.blob();
}
