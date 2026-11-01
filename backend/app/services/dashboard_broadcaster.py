"""
In-process WebSocket fan-out for the Manager Dashboard (Module 11 / Phase
11, FR-54).

Deliberately NOT Redis/Kafka-backed -- a plain dict of open connections
guarded by an `asyncio.Lock`, matching the explicit "simplest architecture
consistent with the modular monolith" instruction and this project's
actual deployment (one FastAPI process, see docker-compose.yml). If this
API is ever run as multiple replicas, each process's broadcaster only
knows about its own clients -- a documented scaling limit (see
docs/dashboard_performance.md), not silently glossed over. The 30s
polling fallback on the frontend exists specifically so that limit
degrades gracefully instead of silently under-delivering updates.

Tenant scoping: every connection is registered under the organization of
the user who opened it (authenticated in app/api/v1/endpoints/dashboard.py),
and broadcast() only delivers to connections of the organization the
event belongs to. Before this, every event went to every connected
dashboard regardless of organization.
"""

import asyncio
import logging

from fastapi import WebSocket

logger = logging.getLogger("app.dashboard.ws")


class DashboardBroadcaster:
    def __init__(self) -> None:
        self._connections: dict[WebSocket, str] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, organization_id: str, subprotocol: str | None = None) -> None:
        await websocket.accept(subprotocol=subprotocol)
        async with self._lock:
            self._connections[websocket] = organization_id

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.pop(websocket, None)

    async def broadcast(self, event_type: str, payload: dict, organization_id: str) -> None:
        message = {"event": event_type, "payload": payload}
        async with self._lock:
            connections = [ws for ws, org in self._connections.items() if org == organization_id]
        for connection in connections:
            try:
                await connection.send_json(message)
            except Exception:
                logger.warning("dashboard_broadcast_send_failed", exc_info=True)
                await self.disconnect(connection)

    @property
    def connection_count(self) -> int:
        return len(self._connections)


_broadcaster = DashboardBroadcaster()


def get_dashboard_broadcaster() -> DashboardBroadcaster:
    return _broadcaster
