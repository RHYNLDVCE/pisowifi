# services/background.py
import time
import threading
import asyncio
import config
import subprocess
import datetime
from core import database, state, utils
from hardware import controller
from network import firewall

# --- Global Flag for Restart Logic ---
reboot_triggered = False

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
    print("💰 Coin Listener STARTED. Waiting for pulses...")

    # --- CALLBACK: Runs immediately when coin drops ---
    def notify_counting():
        current_user = controller.current_slot_user
        if current_user and current_user in state.users:
            print(f"[DEBUG] ⚡ Activity detected for {current_user}. Sending 'Counting' status...")
            # Send immediate feedback to UI
            send_ws_update(current_user, {
                "type": "coin_counting",
                "status": "counting"
            })
    # ------------------------------------------------

    while True:
        # Pass the callback to the hardware controller
        coin_value = controller.wait_for_pulse(on_detected=notify_counting)
        
        if coin_value > 0:
            print(f"\n[DEBUG] 🪙  COIN DETECTED! Pulses: {coin_value}")
            current_user = controller.current_slot_user
            
            if current_user and current_user in state.users:
                # --- SAFETY CHECK: IGNORE BLOCKED USERS ---
                if state.users[current_user].get("status") == "blocked":
                    print(f"[DEBUG] 🚫 Blocked user {current_user} tried to insert coin. Ignoring.")
                    continue
                # ------------------------------------------

                print(f"[DEBUG]    -> Adding {coin_value} credits to BALANCE of {current_user}")
                state.config["slot_expiry_timestamp"] = time.time() + state.config["slot_timeout"]
                
                if "balance" not in state.users[current_user]:
                    state.users[current_user]["balance"] = 0
                
                state.users[current_user]["balance"] += coin_value
                
                # NOTE: We do NOT add points here anymore. 
                # Points are now calculated using the Greedy Algorithm in routers/client.py 
                # when the user clicks "Connect" to ensure the best rate for the total amount.

                state.users[current_user]["last_active"] = time.time()
                
                user_data = state.users[current_user]
                database.sync_user(current_user, user_data)
                database.add_sale(current_user, config.PULSE_VALUE * coin_value)

                payload = {
                    "type": "coin_inserted",
                    "balance": state.users[current_user]["balance"],
                    "points": state.users[current_user].get("points", 0), # Send current points (unchanged)
                    "slot_seconds": state.config["slot_timeout"],
                    "pulse_value": state.config.get("pulse_value", 5)
                }
                send_ws_update(current_user, payload)
            else:
                print(f"[DEBUG]    ⚠️  IGNORED: No user clicked 'Insert Coin' or user unknown.")
        else:
            print("[DEBUG]    Received 0 pulses (Noise?)")

def _time_manager():
    global reboot_triggered
    ticks = 0
    print("⏰ Time Manager & Scheduler Started...")

    while True:
        time.sleep(1) 
        ticks += 1
        
        # --- Scheduled Restart Logic ---
        # Check every 5 seconds
        if ticks % 5 == 0:
            schedule = state.config.get("restart_schedule", {"enabled": False})
            
            if schedule.get("enabled"):
                now = datetime.datetime.now()
                current_time = now.strftime("%H:%M")
                target_time = schedule.get("time", "03:00")

                # If times match and we haven't rebooted yet today
                if current_time == target_time and not reboot_triggered:
                    print(f"🔄 Scheduled Restart Triggered at {current_time}")
                    reboot_triggered = True # Lock it so we don't loop
                    
                    # Notify all active users
                    for mac in list(state.users.keys()):
                        send_ws_update(mac, {"type": "system_message", "message": "System is restarting for maintenance..."})
                    
                    # Wait 3 seconds then reboot
                    time.sleep(3)
                    try:
                        subprocess.run(["sudo", "reboot"])
                    except Exception as e:
                        print(f"❌ Reboot failed: {e}")

                # Reset the trigger once the minute passes (so it can work tomorrow)
                if current_time != target_time:
                    reboot_triggered = False
        # ------------------------------------
        
        for mac, data in list(state.users.items()):
            if data["status"] == "connected" and data["time"] > 0:
                data["time"] -= 1
                if data["time"] <= 0:
                    data["time"] = 0
                    data["status"] = "expired"
                    firewall.block_user(mac)
                    database.sync_user(mac, data)
            
            if ticks >= 30 and data["status"] == "connected":
                database.sync_user(mac, data)

            if ticks % 5 == 0 and hasattr(state, "manager"):
                if mac in state.manager.active_connections:
                    payload = {
                        "type": "sync",
                        "time_remaining": data["time"],
                        "status": data["status"],
                        "balance": data.get("balance", 0),
                        "points": data.get("points", 0)
                    }
                    send_ws_update(mac, payload)

        if controller.current_slot_user:
            time_left = state.config["slot_expiry_timestamp"] - time.time()
            if time_left <= 0:
                send_ws_update(controller.current_slot_user, {"type": "slot_closed"})
                controller.turn_slot_off()
                
        if ticks >= 30: ticks = 0

def _connectivity_monitor():
    print("📡 Connectivity Monitor STARTED.")
    
    while True:
        time.sleep(5)

        if not state.config.get("auto_pause_enabled", True): 
            continue

        timeout_limit = int(state.config.get("inactive_timeout", 60))
        packet_limit = int(state.config.get("inactive_packet_threshold", 5))
        bytes_limit = int(state.config.get("inactive_bytes_threshold", 500))
        now = time.time()

        for mac, data in list(state.users.items()):
            if data["status"] == "connected":
                curr_bytes, curr_packets = firewall.get_user_traffic(mac)
                prev_bytes = data.get("last_byte_count", 0)
                prev_packets = data.get("last_packet_count", 0)
                
                if prev_bytes == 0:
                    data["last_byte_count"] = curr_bytes
                    data["last_packet_count"] = curr_packets
                    continue

                diff_bytes = max(0, curr_bytes - prev_bytes)
                diff_packets = max(0, curr_packets - prev_packets)
                
                data["last_byte_count"] = curr_bytes
                data["last_packet_count"] = curr_packets

                is_active = (diff_bytes > bytes_limit) or (diff_packets >= packet_limit)
                
                last_seen = data.get("last_active", now)
                
                if is_active:
                    data["last_active"] = now 
                else:
                    idle_time = int(now - last_seen)
                    if idle_time > timeout_limit:
                        print(f"[AutoPause] Pausing user {mac} due to inactivity ({idle_time}s)")
                        data["status"] = "paused"
                        firewall.block_user(mac)
                        database.sync_user(mac, data)
                        send_ws_update(mac, {"type": "sync", "status": "paused", "time_remaining": data["time"]})