# core/state.py
import json
import os
from fastapi import WebSocket
from typing import List, Dict
import asyncio

CONFIG_FILE = "config.json"

users = {}

# 1. Define Default Settings
defaults = {
    "slot_timeout": 30,
    "slot_expiry_timestamp": 0,
    "inactive_timeout": 60,
    "auto_pause_enabled": True,
    "speed_limit_enabled": False,
    "global_speed_limit": 5
}

# Start with defaults
config = defaults.copy()

# 2. Add Persistence Functions
def save_config():
    """Saves the current config to a file."""
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=4)
        print("✅ Configuration saved to file.")
    except Exception as e:
        print(f"❌ Error saving config: {e}")

def load_config():
    """Loads config from file, merging with defaults."""
    global config
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                saved_config = json.load(f)
                # Update our config with saved values
                for key, value in saved_config.items():
                    config[key] = value
            print("✅ Configuration loaded from file.")
        except Exception as e:
            print(f"❌ Error loading config: {e}")

# 3. Connection Manager (Keep existing code)
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

# 4. Load Config on Startup
load_config()