import json
import os
from fastapi import WebSocket
from typing import List, Dict
import asyncio

CONFIG_FILE = "config.json"

users = {}

defaults = {
    "slot_timeout": 30,
    "slot_expiry_timestamp": 0,
    "inactive_timeout": 60,
    "auto_pause_enabled": True,
    "speed_limit_enabled": False,
    "global_speed_limit": 5,
    "gaming_mode_enabled": False,
    "inactive_packet_threshold": 100,
    "coin_rates": "1:10,5:60,10:180,20:300",
    "pulse_value": 1,
    "restart_schedule": {
        "enabled": False,
        "time": "03:00"  # Default to 3:00 AM
    },
    "points_enabled": True,
    "coin_point_map": {  # Default Point Values
        "1": 0.5,
        "5": 1,
        "10": 3,
        "20": 5
    },
    "point_promos": [    # Default Promo
        {"id": 1, "name": "3 Hours Free", "cost": 20, "minutes": 180}
    ]
}

# Start with defaults
config = defaults.copy()

def save_config():
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=4)
        print("✅ Configuration saved to file.")
    except Exception as e:
        print(f"❌ Error saving config: {e}")

def load_config():
    global config
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                saved_config = json.load(f)
                for key, value in saved_config.items():
                    config[key] = value
            print("✅ Configuration loaded from file.")
        except Exception as e:
            print(f"❌ Error loading config: {e}")

# Connection Manager
loop: asyncio.AbstractEventLoop = None 

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, mac: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[mac] = websocket

    def disconnect(self, mac: str, websocket: WebSocket):
        if mac in self.active_connections and self.active_connections[mac] == websocket:
            del self.active_connections[mac]

    async def send_personal_message(self, message: dict, mac: str):
        if mac in self.active_connections:
            ws = self.active_connections[mac]
            try:
                await ws.send_json(message)
            except:
                self.disconnect(mac, ws)

manager = ConnectionManager()
load_config()