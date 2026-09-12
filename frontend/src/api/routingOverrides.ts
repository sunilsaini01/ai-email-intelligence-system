// client.ts only exports GET/POST helpers -- PUT/DELETE go through fetch
// directly here, same "no full HTTP client library needed for ~15
// endpoints" reasoning that file's own module docstring already states.
import { API_BASE_URL, ApiError, apiGet, apiPost, getAuthToken } from "./client";
import type { RoutingOverride, RoutingOverrideCreateRequest, RoutingOverrideListResponse } from "../types/routingOverrides";

async function apiPut<T>(path: string, body: unknown): Promise<T> {
  const token = getAuthToken();
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new ApiError(response.status, await response.json().catch(() => response.statusText));
  return response.json() as Promise<T>;
}

async function apiDelete(path: string): Promise<void> {
  const token = getAuthToken();
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "DELETE",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!response.ok) throw new ApiError(response.status, await response.text());
}

export const routingOverridesApi = {
  list: () => apiGet<RoutingOverrideListResponse>("/routing/overrides"),
  create: (request: RoutingOverrideCreateRequest) => apiPost<RoutingOverride>("/routing/overrides", request),
  update: (id: string, request: Partial<RoutingOverrideCreateRequest>) => apiPut<RoutingOverride>(`/routing/overrides/${id}`, request),
  remove: (id: string) => apiDelete(`/routing/overrides/${id}`),
};
