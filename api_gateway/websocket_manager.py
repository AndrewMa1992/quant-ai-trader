"""api_gateway/websocket_manager.py – WebSocket connection manager.

Manages real-time WebSocket connections for:
- Live market data streaming
- Alert broadcasting
- Order status updates
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Set

from fastapi import WebSocket, WebSocketDisconnect
from loguru import logger


class WebSocketManager:
    """Manages active WebSocket connections with room-based grouping.

    Supports broadcasting to:
    - All connected clients
    - Clients in a specific room (market, alert type, etc.)
    - Individual authenticated users

    Attributes:
        active_connections: Set of all active WebSocket connections.
        rooms: Mapping of room_name -> set of WebSocket connections.
    """

    def __init__(self) -> None:
        self.active_connections: Set[WebSocket] = set()
        self.rooms: Dict[str, Set[WebSocket]] = {}
        self._lock: asyncio.Lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        """Accept a new WebSocket connection and register it.

        Args:
            websocket: The WebSocket connection to register.
        """
        await websocket.accept()
        async with self._lock:
            self.active_connections.add(websocket)
        logger.info(f"WebSocket connected (total: {len(self.active_connections)})")

    async def disconnect(self, websocket: WebSocket) -> None:
        """Remove a WebSocket connection from all rooms and the active set.

        Args:
            websocket: The WebSocket connection to remove.
        """
        async with self._lock:
            self.active_connections.discard(websocket)
            for room_members in self.rooms.values():
                room_members.discard(websocket)
            # Clean up empty rooms
            empty_rooms = [name for name, members in self.rooms.items() if not members]
            for name in empty_rooms:
                del self.rooms[name]
        logger.info(f"WebSocket disconnected (total: {len(self.active_connections)})")

    async def join_room(self, websocket: WebSocket, room: str) -> None:
        """Add a WebSocket connection to a named room.

        Args:
            websocket: The WebSocket connection.
            room: Room name to join.
        """
        async with self._lock:
            if room not in self.rooms:
                self.rooms[room] = set()
            self.rooms[room].add(websocket)
        logger.debug(f"WebSocket joined room '{room}'")

    async def leave_room(self, websocket: WebSocket, room: str) -> None:
        """Remove a WebSocket connection from a named room.

        Args:
            websocket: The WebSocket connection.
            room: Room name to leave.
        """
        async with self._lock:
            if room in self.rooms:
                self.rooms[room].discard(websocket)
                if not self.rooms[room]:
                    del self.rooms[room]
        logger.debug(f"WebSocket left room '{room}'")

    async def broadcast(self, message: Any) -> None:
        """Send a message to all connected WebSocket clients.

        Args:
            message: The message to broadcast (will be JSON-serialized).
        """
        payload = json.dumps(message, default=str) if not isinstance(message, str) else message
        stale: List[WebSocket] = []
        for websocket in self.active_connections:
            try:
                await websocket.send_text(payload)
            except Exception:
                stale.append(websocket)

        # Clean stale connections
        async with self._lock:
            for ws in stale:
                self.active_connections.discard(ws)

    async def broadcast_to_room(self, room: str, message: Any) -> None:
        """Send a message to all WebSocket clients in a specific room.

        Args:
            room: The target room name.
            message: The message to broadcast.
        """
        payload = json.dumps(message, default=str) if not isinstance(message, str) else message
        if room not in self.rooms:
            return
        stale: List[WebSocket] = []
        for websocket in self.rooms.get(room, set()):
            try:
                await websocket.send_text(payload)
            except Exception:
                stale.append(websocket)

        async with self._lock:
            for ws in stale:
                self.rooms[room].discard(ws)
                self.active_connections.discard(ws)

    async def send_personal(self, websocket: WebSocket, message: Any) -> None:
        """Send a message to a specific WebSocket connection.

        Args:
            websocket: Target WebSocket connection.
            message: The message to send.
        """
        payload = json.dumps(message, default=str) if not isinstance(message, str) else message
        try:
            await websocket.send_text(payload)
        except Exception:
            await self.disconnect(websocket)

    async def push_cycle_data(self, data: dict) -> None:
        """Broadcast cycle data to the 'market-data' room.

        Args:
            data: Cycle data dict to broadcast.
        """
        await self.broadcast_to_room("market-data", data)

    async def push_tiger_snapshot(self, data: dict) -> None:
        """Broadcast Tiger snapshot to the 'tiger' room.

        Args:
            data: Tiger snapshot data dict to broadcast.
        """
        await self.broadcast_to_room("tiger", data)

    def room_size(self, room: str) -> int:
        """Return the number of connections in a specific room.

        Args:
            room: Room name.

        Returns:
            Number of WebSocket connections in the room.
        """
        return len(self.rooms.get(room, set()))

    @property
    def connection_count(self) -> int:
        """Return the number of active WebSocket connections."""
        return len(self.active_connections)

    @property
    def room_count(self) -> int:
        """Return the number of active rooms."""
        return len(self.rooms)


# Singleton instance
websocket_manager = WebSocketManager()
