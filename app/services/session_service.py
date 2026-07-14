import time
import datetime
import asyncio # <-- Add this

from core import database, state
from network import firewall
from hardware import controller
from services.billing_service import BillingService
from services import background 

class SessionService:
    def __init__(self, billing_service: BillingService):
        self.billing = billing_service

    # Change to async def
    async def connect_user(self, mac: str) -> dict: 
        user = state.users.get(mac)
        if user and user.get("status") == "blocked": 
            return {"result": "blocked"}

        if user:
            balance = user.get("balance", 0)
            if balance > 0:
                added_minutes = self.billing.calculate_time_from_balance(balance)
                user["time"] += (added_minutes * 60)
                
                if state.config.get("points_enabled", False):
                    earned_points = self.billing.calculate_points_from_balance(balance)
                    if "points" not in user: user["points"] = 0
                    user["points"] = round(user["points"] + earned_points, 2)
                
                user["balance"] = 0
                database.sync_user(mac, user)
            
            if user["time"] > 0:
                user["status"] = "connected"
                user["last_active"] = time.time()
                # Set the deadline timestamp — this is the single source of truth
                # for the timer while the user is connected.
                user["expires_at"] = time.time() + user["time"]
                firewall.allow_user(mac, user.get("ip"))
                
                if controller.current_slot_user == mac:
                    controller.turn_slot_off()
                
                database.sync_user(mac, user)
                
                # Use non-blocking async sleep
                await asyncio.sleep(1.0) 
                
                if mac in state.manager.active_connections:
                    background.send_ws_update(mac, {
                        "type": "sync", "status": "connected",
                        "time_remaining": user["time"], "balance": 0,
                        "points": user.get("points", 0) 
                    })
                return {"result": "success"}
        return {"result": "fail"}

    def pause_user(self, mac: str) -> dict:
        if state.users.get(mac, {}).get("status") == "blocked": return {"result": "fail"}
        if state.users.get(mac) and state.users[mac]["status"] == "connected":
            user = state.users[mac]
            # Snapshot true remaining seconds from deadline before clearing it
            if "expires_at" in user:
                user["time"] = max(0, int(user["expires_at"] - time.time()))
                del user["expires_at"]
            user["status"] = "paused"
            firewall.block_user(mac)
            database.sync_user(mac, user)
            
            if mac in state.manager.active_connections:
                background.send_ws_update(mac, {
                    "type": "sync", "status": "paused",
                    "time_remaining": user["time"],
                    "balance": user.get("balance", 0),
                    "points": user.get("points", 0)
                })
            return {"result": "success"}
        return {"result": "fail"}