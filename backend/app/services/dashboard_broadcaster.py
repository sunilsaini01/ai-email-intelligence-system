"""
In-process WebSocket fan-out for the Manager Dashboard (Module 11 / Phase
11, FR-54).

Deliberately NOT Redis/Kafka-backed -- a plain `set` of open connections
guarded by an `asyncio.Lock`, matching the explicit "simplest architecture
consistent with the modular monolith" instruction and this project's
actual deployment (one FastAPI process, see docker-compose.yml). If this
API is ever run as multiple replicas, each process's broadcaster only
knows about its own clients -- a documented scaling limit (see
docs/dashboard_performance.md), not silently glossed over. The 30s
polling fallback on the frontend exists specifically so that limit
degrades gracefully instead of silently under-delivering updates.
"""

import asyncio
import logging

from fastapi import WebSocket

logger = logging.getLogger("app.dashboard.ws")


class DashboardBroadcaster:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(websocket)

    async def broadcast(self, event_type: str, payload: dict) -> None:
        message = {"event": event_type, "payload": payload}
        async with self._lock:
            connections = list(self._connections)
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
