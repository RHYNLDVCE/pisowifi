import time
import threading
import asyncio
import config
from core import database, state, utils
from hardware import controller
from network import firewall

def start_background_tasks():
    threading.Thread(target=_coin_listener, daemon=True).start()
    threading.Thread(target=_time_manager, daemon=True).start()
    threading.Thread(target=_connectivity_monitor, daemon=True).start()

def send_ws_update(mac, data):
    if hasattr(state, "loop") and state.loop and hasattr(state, "manager"):
        try:
            asyncio.run_coroutine_threadsafe(
                state.manager.send_personal_message(data, mac), 
                state.loop
            )
        except Exception as e:
            print(f"WS Error: {e}")

def _coin_listener():
    while True:
        coin_value = controller.wait_for_pulse()
        if coin_value > 0:
            state.config["slot_expiry_timestamp"] = time.time() + state.config["slot_timeout"]
            
            if controller.current_slot_user and controller.current_slot_user in state.users:
                minutes = config.PULSE_VALUE * coin_value 
                state.users[controller.current_slot_user]["time"] += (minutes * 60)
                state.users[controller.current_slot_user]["last_active"] = time.time()
                
                user_data = state.users[controller.current_slot_user]
                database.sync_user(controller.current_slot_user, user_data)
                database.add_sale(controller.current_slot_user, config.PULSE_VALUE * coin_value)

                payload = {
                    "type": "coin_inserted",
                    "time_remaining": state.users[controller.current_slot_user]["time"],
                    "slot_seconds": state.config["slot_timeout"],
                    "added_time": minutes * 60
                }
                send_ws_update(controller.current_slot_user, payload)

def _time_manager():
    ticks = 0
    while True:
        time.sleep(1) 
        ticks += 1
        
        for mac, data in list(state.users.items()):
            if data["status"] == "connected" and data["time"] > 0:
                data["time"] -= 1
                if data["time"] <= 0:
                    data["time"] = 0
                    data["status"] = "expired"
                    firewall.block_user(mac)
                    database.sync_user(mac, data)
            
            if ticks >= 60 and data["status"] == "connected":
                database.sync_user(mac, data)

            if ticks % 5 == 0 and hasattr(state, "manager"):
                if mac in state.manager.active_connections:
                    payload = {
                        "type": "sync",
                        "time_remaining": data["time"],
                        "status": data["status"]
                    }
                    send_ws_update(mac, payload)

        if controller.current_slot_user:
            time_left = state.config["slot_expiry_timestamp"] - time.time()
            if time_left <= 0:
                send_ws_update(controller.current_slot_user, {"type": "slot_closed"})
                controller.turn_slot_off()
                
        if ticks >= 60: ticks = 0


def _connectivity_monitor():
    """
    Smarter Activity Monitor with Admin Toggle
    """
    TRAFFIC_THRESHOLD = 50000 # 50KB

    while True:
        time.sleep(5) 
        
        # 1. CHECK MASTER SWITCH
        if not state.config.get("auto_pause_enabled", True):
            continue # Feature is OFF, do nothing
            
        timeout_limit = int(state.config.get("inactive_timeout", 60))
        now = time.time()

        for mac, data in list(state.users.items()):
            if data["status"] == "connected":
                
                # Get Traffic Stats
                current_bytes = firewall.get_user_bytes(mac)
                previous_bytes = data.get("last_byte_count", 0)
                
                if previous_bytes == 0:
                    data["last_byte_count"] = current_bytes
                    continue

                diff = current_bytes - previous_bytes
                if diff < 0: diff = 0 
                
                data["last_byte_count"] = current_bytes

                # Check Activity
                if diff > TRAFFIC_THRESHOLD:
                    data["last_active"] = now 
                else:
                    last_seen = data.get("last_active", now)
                    idle_time = int(now - last_seen)
                    
                    if idle_time > timeout_limit:
                        print(f"💤 Auto-Pausing User {mac} (Idle for {idle_time}s)")
                        
                        data["status"] = "paused"
                        firewall.block_user(mac)
                        database.sync_user(mac, data)
                        
                        # Notify Frontend
                        send_ws_update(mac, {
                            "type": "sync",
                            "status": "paused",
                            "time_remaining": data["time"]
                        })