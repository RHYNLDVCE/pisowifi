import time
import threading
import asyncio
import config
import subprocess
import datetime
from core import database, state, utils
from hardware import controller
from network import firewall
import ctypes
# --- Global Flag for Restart Logic ---
reboot_triggered = False\
    
def set_linux_thread_name(name):
    """Bypasses Python to tell the Linux kernel the real thread name for htop"""
    try:
        libc = ctypes.cdll.LoadLibrary('libc.so.6')
        # PR_SET_NAME is 15. Linux strictly limits thread names to 15 characters!
        libc.prctl(15, name[:15].encode('utf-8'), 0, 0, 0)
    except Exception as e:
        pass
    
def start_background_tasks():
    threading.Thread(target=_coin_listener, name="Piso-Coin", daemon=True).start()
    threading.Thread(target=_time_manager, name="Piso-Timer", daemon=True).start()
    threading.Thread(target=_connectivity_monitor, name="Piso-Monitor", daemon=True).start()
    
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
    set_linux_thread_name("Piso-Coin")
    print("💰 Coin Listener STARTED. Waiting for pulses...")

    # --- CALLBACK: Runs immediately when coin drops ---
    def notify_counting():
        try:
            current_user = controller.current_slot_user
            if current_user and current_user in state.users:
                print(f"[DEBUG] ⚡ Activity detected for {current_user}. Sending 'Counting' status...")
                # Send immediate feedback to UI
                send_ws_update(current_user, {
                    "type": "coin_counting",
                    "status": "counting"
                })
        except Exception as e:
            print(f"❌ Error in coin UI notification: {e}")
    # ------------------------------------------------

    while True:
        try:
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
                    
                    state.users[current_user]["last_active"] = time.time()
                    
                    user_data = state.users[current_user]
                    
                    # --- PROTECTED DATABASE SAVES ---
                    try:
                        database.sync_user(current_user, user_data)
                        database.add_sale(current_user, config.PULSE_VALUE * coin_value)
                    except Exception as db_e:
                        print(f"❌ DB Error while saving coin: {db_e}")
                    # --------------------------------

                    payload = {
                        "type": "coin_inserted",
                        "balance": state.users[current_user]["balance"],
                        "points": state.users[current_user].get("points", 0),
                        "slot_seconds": state.config["slot_timeout"],
                        "pulse_value": state.config.get("pulse_value", 5)
                    }
                    send_ws_update(current_user, payload)
                else:
                    print(f"[DEBUG]    ⚠️  IGNORED: No user clicked 'Insert Coin' or user unknown.")
            else:
                print("[DEBUG]    Received 0 pulses (Noise?)")

        except Exception as main_e:
            # If a massive error happens, keep the thread alive and wait 1 second
            print(f"🔥 CRITICAL ERROR in Coin Listener loop: {main_e}")
            time.sleep(1)

def _time_manager():
    set_linux_thread_name("Piso-Timer")
    global reboot_triggered
    ticks = 0
    print("⏰ Time Manager & Scheduler Started...")

    while True:
        try:
            time.sleep(1) 
            ticks += 1
            
            # --- Scheduled Restart Logic ---
            if ticks % 5 == 0:
                schedule = state.config.get("restart_schedule", {"enabled": False})
                
                if schedule.get("enabled"):
                    now = datetime.datetime.now()
                    current_time = now.strftime("%H:%M")
                    target_time = schedule.get("time", "03:00")

                    if current_time == target_time and not reboot_triggered:
                        print(f"🔄 Scheduled Restart Triggered at {current_time}")
                        reboot_triggered = True 
                        
                        for mac in list(state.users.keys()):
                            send_ws_update(mac, {"type": "system_message", "message": "System is restarting for maintenance..."})
                        
                        time.sleep(3)
                        try:
                            subprocess.run(["sudo", "reboot"])
                        except Exception as e:
                            print(f"❌ Reboot failed: {e}")

                    if current_time != target_time:
                        reboot_triggered = False
            # ------------------------------------
            
            for mac, data in list(state.users.items()):
                # Use .get() to prevent KeyErrors if user data is missing fields
                status = data.get("status")
                time_left = data.get("time", 0)

                if status == "connected" and time_left > 0:
                    data["time"] -= 1
                    if data["time"] <= 0:
                        data["time"] = 0
                        data["status"] = "expired"
                        
                        # Protect firewall and DB from crashing the loop
                        try:
                            firewall.block_user(mac)
                            database.sync_user(mac, data)
                        except Exception as e:
                            print(f"❌ Error expiring user {mac}: {e}")
            
                # Save to DB every 30 seconds
                if ticks >= 30 and data.get("status") == "connected":
                    try:
                        database.sync_user(mac, data)
                    except Exception as e:
                        print(f"❌ Database sync error for {mac}: {e}")

                if ticks % 5 == 0 and hasattr(state, "manager"):
                    if mac in state.manager.active_connections:
                        payload = {
                            "type": "sync",
                            "time_remaining": data.get("time", 0),
                            "status": data.get("status"),
                            "balance": data.get("balance", 0),
                            "points": data.get("points", 0)
                        }
                        send_ws_update(mac, payload)

            if controller.current_slot_user:
                slot_time_left = state.config.get("slot_expiry_timestamp", 0) - time.time()
                if slot_time_left <= 0:
                    send_ws_update(controller.current_slot_user, {"type": "slot_closed"})
                    # Protect hardware controller from crashing the loop
                    try:
                        controller.turn_slot_off()
                    except Exception as e:
                        print(f"❌ Hardware controller error: {e}")
                
            if ticks >= 30: 
                ticks = 0

        except Exception as main_e:
            # If a massive unexpected error happens, catch it here, print it, 
            # and let the loop continue running on the next second.
            print(f"🔥 CRITICAL ERROR in Time Manager loop: {main_e}")
            
def _connectivity_monitor():
    """
    Monitors user traffic and pauses inactive users.
    OPTIMIZED: Uses bulk fetch to reduce CPU load.
    """
    set_linux_thread_name("Piso-Monitor")
    print("📡 Connectivity Monitor STARTED (Optimized).")
    
    while True:
        try:
            time.sleep(5)

            if not state.config.get("auto_pause_enabled", True): 
                continue

            timeout_limit = int(state.config.get("inactive_timeout", 60))
            packet_limit = int(state.config.get("inactive_packet_threshold", 5))
            bytes_limit = int(state.config.get("inactive_bytes_threshold", 500))
            now = time.time()

            # --- OPTIMIZATION: Fetch ALL traffic data ONCE ---
            try:
                all_traffic_stats = firewall.get_all_traffic()
            except Exception as e:
                print(f"Monitor Error: {e}")
                all_traffic_stats = {}
            # -------------------------------------------------

            for mac, data in list(state.users.items()):
                if data["status"] == "connected":
                    curr_bytes, curr_packets = all_traffic_stats.get(mac, (0, 0))
                    
                    prev_bytes = data.get("last_byte_count", 0)
                    prev_packets = data.get("last_packet_count", 0)
                    
                    # First run for this user? Just initialize baseline.
                    if prev_bytes == 0 and curr_bytes > 0:
                        data["last_byte_count"] = curr_bytes
                        data["last_packet_count"] = curr_packets
                        data["last_active"] = now
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
                            print(f"[AutoPause] 💤 Pausing {mac} due to inactivity ({idle_time}s)")
                            
                            data["status"] = "paused"
                            
                            try:
                                firewall.block_user(mac)
                                database.sync_user(mac, data)
                            except Exception as db_e:
                                print(f"❌ DB/Firewall Error while auto-pausing: {db_e}")
                            
                            send_ws_update(mac, {
                                "type": "sync", 
                                "status": "paused", 
                                "time_remaining": data["time"]
                            })
        
        except Exception as main_e:
            print(f"🔥 CRITICAL ERROR in Connectivity Monitor loop: {main_e}")