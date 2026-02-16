"""Shared WebSocket connection managers for channels and DMs."""

from collections import defaultdict
from fastapi import WebSocket


class ConnectionManager:
    """Manages WebSocket connections per channel/conversation."""

    def __init__(self):
        # key -> list of (websocket, user_id, username)
        self.channels: dict[int, list[tuple[WebSocket, int, str]]] = defaultdict(list)

    async def connect(self, ws: WebSocket, channel_id: int, user_id: int, username: str):
        await ws.accept()
        self.channels[channel_id].append((ws, user_id, username))

    def disconnect(self, ws: WebSocket, channel_id: int):
        self.channels[channel_id] = [
            (w, uid, uname) for w, uid, uname in self.channels[channel_id] if w != ws
        ]

    async def broadcast(self, channel_id: int, message: dict):
        dead = []
        for ws, uid, uname in self.channels[channel_id]:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws, channel_id)

    async def broadcast_except(self, channel_id: int, message: dict, exclude_user_id: int):
        """Broadcast to all clients in a channel EXCEPT the specified user."""
        dead = []
        for ws, uid, uname in self.channels[channel_id]:
            if uid == exclude_user_id:
                continue
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws, channel_id)


# Singleton instances — import these in route files and main.py
manager = ConnectionManager()
dm_manager = ConnectionManager()

# Track all connected user websockets globally (for status updates)
# user_id -> set of WebSocket objects
connected_users: dict[int, set[WebSocket]] = defaultdict(set)
