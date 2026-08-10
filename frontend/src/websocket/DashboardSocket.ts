// In-process WebSocket client for FR-54. Talks to the backend's
// single-process, in-memory broadcaster (see
// backend/app/services/dashboard_broadcaster.py) -- reconnects with a
// simple fixed backoff on drop. This is NOT the primary refresh
// mechanism: every dashboard query already polls every 30s via React
// Query's `refetchInterval` (see hooks/useDashboardWebSocket.ts) --
// this socket exists purely to make updates feel faster than the worst
// case 30s wait, and degrades to "just polling" gracefully if the
// connection never succeeds (e.g. a proxy that blocks WebSocket
// upgrades) -- see docs/dashboard_performance.md.

import { WS_BASE_URL } from "../api/client";

export type DashboardEvent = { event: string; payload: unknown };
type Listener = (event: DashboardEvent) => void;

const RECONNECT_DELAY_MS = 3000;

export class DashboardSocket {
  private socket: WebSocket | null = null;
  private listeners = new Set<Listener>();
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private closedByUser = false;

  connect(): void {
    this.closedByUser = false;
    this.open();
  }

  private open(): void {
    try {
      this.socket = new WebSocket(`${WS_BASE_URL}/dashboard/ws`);
    } catch {
      this.scheduleReconnect();
      return;
    }

    this.socket.onmessage = (event) => {
      try {
        const parsed = JSON.parse(event.data as string) as DashboardEvent;
        this.listeners.forEach((listener) => listener(parsed));
      } catch {
        // Malformed frame -- ignore, the 30s poll fallback covers this.
      }
    };

    this.socket.onclose = () => {
      if (!this.closedByUser) {
        this.scheduleReconnect();
      }
    };

    this.socket.onerror = () => {
      this.socket?.close();
    };
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer) return;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      if (!this.closedByUser) this.open();
    }, RECONNECT_DELAY_MS);
  }

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  disconnect(): void {
    this.closedByUser = true;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.socket?.close();
    this.socket = null;
  }
}

export const dashboardSocket = new DashboardSocket();
