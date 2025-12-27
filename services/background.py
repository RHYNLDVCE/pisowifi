# services/background.py
import time
import threading
import config
from core import database, state
from hardware import controller
from network import firewall

def start_background_tasks():
    threading.Thread(target=_coin_listener, daemon=True).start()
    threading.Thread(target=_time_manager, daemon=True).start()

def _coin_listener():
    """Waits for coins and updates user time."""
    while True:
        coin_value = controller.wait_for_pulse()
        if coin_value > 0:
            print(f"💰 Coin Detected! Value: {coin_value}")
            
            # Reset Slot Timer
            state.config["slot_expiry_timestamp"] = time.time() + state.config["slot_timeout"]
            
            # Add Time
            if controller.current_slot_user and controller.current_slot_user in state.users:
                minutes = config.PULSE_VALUE * coin_value 
                state.users[controller.current_slot_user]["time"] += (minutes * 60)
                
                # Sync DB
                user_data = state.users[controller.current_slot_user]
                database.sync_user(controller.current_slot_user, user_data)
                database.add_sale(controller.current_slot_user, config.PULSE_VALUE * coin_value)

def _time_manager():
    """Decrements user time every second."""
    ticks = 0
    while True:
        time.sleep(1) 
        ticks += 1
        
        # 1. Decrement User Time
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

        # 2. Manage Slot Auto-Close
        if controller.current_slot_user:
            time_left = state.config["slot_expiry_timestamp"] - time.time()
            if time_left <= 0:
                print("⏳ Slot Timeout. Closing drawer.")
                controller.turn_slot_off()
                
        if ticks >= 60: ticks = 0