import time
import datetime
import subprocess
from core import database, state
from network import firewall
from hardware import controller

class TimerService:
    def __init__(self, ws_sender):
        self.ws_sender = ws_sender
        self.reboot_triggered = False

    def check_reboot_schedule(self):
        schedule = state.config.get("restart_schedule", {"enabled": False})
        if not schedule.get("enabled"): return
        
        current_time = datetime.datetime.now().strftime("%H:%M")
        target_time = schedule.get("time", "03:00")

        if current_time == target_time and not self.reboot_triggered:
            self.reboot_triggered = True 
            
            # 1. Notify UI
            for user_mac in list(state.users.keys()):
                self.ws_sender(user_mac, {"type": "system_message", "message": "System is restarting. Please wait..."})
            
            time.sleep(3) 
            
            # 2. Save Data
            for user_mac, user_data in list(state.users.items()):
                if user_data.get("status") != "new":
                    try: database.sync_user(user_mac, user_data)
                    except: pass
            
            # 3. Hardware Reboot
            try: subprocess.run(["sync"], check=True)
            except: pass
            time.sleep(2)
            try: subprocess.run(["sudo", "systemctl", "reboot"])
            except: pass

        if current_time != target_time:
            self.reboot_triggered = False
                
                
    def tick_users(self, ticks: int):
        users_to_sync = []
        now = time.time()

        for mac, data in list(state.users.items()):
            status = data.get("status")

            if status == "connected":
                expires_at = data.get("expires_at")

                if expires_at is None:
                    # Safety: user is connected but has no deadline (e.g. after a restart).
                    # Reconstruct the deadline from the stored remaining seconds.
                    data["expires_at"] = now + data.get("time", 0)
                    expires_at = data["expires_at"]

                # Compute true time left from the wall clock — always exact, never drifts
                time_left = expires_at - now
                data["time"] = max(0, int(time_left))  # keep "time" in sync for DB writes

                if time_left <= 0:
                    data["time"] = 0
                    data["status"] = "expired"
                    data.pop("expires_at", None)
                    try:
                        from core.logger import system_log
                        system_log(f"[TIMER] User {mac} (IP: {data.get('ip')}) out of time. Disconnecting...")
                        firewall.block_user(mac, data.get("ip"))
                        users_to_sync.append((mac, data))
                    except Exception as e:
                        import logging
                        logging.error(f"Firewall block error: {e}")

            # Queue DB sync every 30 seconds (data["time"] is already up-to-date above)
            if ticks >= 30 and data.get("status") == "connected":
                users_to_sync.append((mac, data))

            # Update UI every 5 seconds
            if ticks % 5 == 0:
                self.ws_sender(mac, {
                    "type": "sync",
                    "time_remaining": data.get("time", 0),
                    "status": data.get("status"),
                    "balance": data.get("balance", 0),
                    "points": data.get("points", 0)
                })

        # Execute single batch write
        if users_to_sync:
            try:
                database.sync_multiple_users(users_to_sync)
            except Exception as e:
                import logging
                logging.error(f"Batch sync error: {e}")

    def check_slot_expiry(self):
        if controller.current_slot_user:
            slot_time_left = state.config.get("slot_expiry_timestamp", 0) - time.time()
            if slot_time_left <= 0:
                self.ws_sender(controller.current_slot_user, {"type": "slot_closed"})
                try: controller.turn_slot_off()
                except: pass