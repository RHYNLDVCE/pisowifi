# core/state.py
from fastapi import WebSocket
from typing import List, Dict
import asyncio

users = {}

config = {
    "slot_timeout": 30,
    "slot_expiry_timestamp": 0,
    "inactive_timeout": 60,      # Seconds before pausing
    "auto_pause_enabled": True   # <--- NEW: Master switch
}

loop: asyncio.AbstractEventLoop = None 

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, mac: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[mac] = websocket

    def disconnect(self, mac: str):
        if mac in self.active_connections:
            del self.active_connections[mac]

    async def send_personal_message(self, message: dict, mac: str):
        if mac in self.active_connections:
            try:
                await self.active_connections[mac].send_json(message)
            except:
                self.disconnect(mac)

manager = ConnectionManager()