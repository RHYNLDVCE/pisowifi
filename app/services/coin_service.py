import time
from core import database, state
import config

class CoinService:
    def __init__(self, ws_sender):
        self.ws_sender = ws_sender

    def notify_counting(self, current_user):
        if current_user and current_user in state.users:
            self.ws_sender(current_user, {"type": "coin_counting", "status": "counting"})

    def process_coin(self, coin_value: int, current_user: str):
        if coin_value <= 0 or not current_user or current_user not in state.users:
            return

        if state.users[current_user].get("status") == "blocked":
            return
        
        # Extend slot time
        state.config["slot_expiry_timestamp"] = time.time() + state.config.get("slot_timeout", 30)
        
        user = state.users[current_user]
        user["balance"] = user.get("balance", 0) + coin_value
        user["last_active"] = time.time()
        
        try:
            database.sync_user(current_user, user)
            database.add_sale(current_user, config.PULSE_VALUE * coin_value)
        except Exception:
            pass # Failsafe against broken DB pipes
        
        self.ws_sender(current_user, {
            "type": "coin_inserted",
            "balance": user["balance"],
            "points": user.get("points", 0),
            "slot_seconds": state.config.get("slot_timeout", 30),
            "pulse_value": state.config.get("pulse_value", 5)
        })