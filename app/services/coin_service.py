import time
from core import database, state
from core.logger import system_log
import config

class CoinService:
    def __init__(self, ws_sender):
        self.ws_sender = ws_sender

    def notify_counting(self, mac: str):
        """Tells the UI the hardware is currently counting pulses."""
        if mac:
            self.ws_sender(mac, {"type": "coin_counting", "is_counting": True})

    def notify_done_counting(self, mac: str):
        """Tells the UI the hardware has completely finished counting."""
        if mac:
            self.ws_sender(mac, {"type": "coin_counting", "is_counting": False})

    def process_coin(self, pulses: int, mac: str):
        """Converts pulses to balance, saves to DB, and instantly updates the UI."""
        if pulses <= 0 or not mac or mac not in state.users:
            system_log("[WARNING] Coin processed but no valid MAC address found.")
            return

        if state.users[mac].get("status") == "blocked":
            return
        
        # Extend the portal slot timeout so it doesn't close while they are dropping coins
        state.config["slot_expiry_timestamp"] = time.time() + state.config.get("slot_timeout", 30)

        # 1. Calculate actual currency amount based on config
        pulse_value = int(state.config.get("pulse_value", 1))
        amount = pulses * pulse_value

        user = state.users[mac]
        current_balance = user.get("balance", 0)
        new_balance = current_balance + amount
        user["balance"] = new_balance
        user["last_active"] = time.time()
        
        try:
            # 2. Save the transaction permanently to the SQLite database
            database.sync_user(mac, user)
            database.add_sale(mac, amount)
        except Exception as e:
            system_log(f"[CRITICAL] Database write failed during coin process: {e}")
            
        system_log(f"[COIN_SUCCESS] Credited {amount} to {mac}. Balance: {new_balance}")

        # 3. Push Live WebSocket Updates to the UI
        # This triggers the coin insertion animation/sound
        self.ws_sender(mac, {
            "type": "coin_inserted",
            "inserted": amount,
            "balance": user["balance"],
            "points": user.get("points", 0),
            "slot_seconds": state.config.get("slot_timeout", 30),
            "pulse_value": pulse_value
        })
        
        # This forces the main UI text variables to refresh instantly
        self.ws_sender(mac, {
            "type": "sync",
            "balance": user["balance"],
            "time_remaining": user.get("time", 0),
            "points": user.get("points", 0),
            "status": user.get("status", "")
        })