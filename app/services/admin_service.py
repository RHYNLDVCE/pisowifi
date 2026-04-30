import math
from datetime import datetime, timedelta
from core import database, state
from network import firewall

class AdminService:
    def get_dashboard_stats(self) -> dict:
        now = datetime.now()
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        ts_day = start_of_day.timestamp()
        ts_week = (start_of_day - timedelta(days=now.weekday())).timestamp()
        ts_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()
        ts_year = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()
        ts_yesterday_start = (start_of_day - timedelta(days=1)).timestamp()

        return {
            "total": database.get_total_sales(),
            "yesterday": database.get_sales_range(ts_yesterday_start, ts_day),
            "daily": database.get_sales_since(ts_day),
            "weekly": database.get_sales_since(ts_week),
            "monthly": database.get_sales_since(ts_month),
            "yearly": database.get_sales_since(ts_year),
        }

    def manage_user_time(self, mac: str, amount: int, unit: str, action: str):
        if mac in state.users:
            amount = abs(int(amount))
            seconds = amount * 3600 if unit == "hours" else amount * 60
            
            if action == "subtract": state.users[mac]["time"] -= seconds
            elif action == "add": state.users[mac]["time"] += seconds
            
            if state.users[mac]["time"] < 0: state.users[mac]["time"] = 0
            
            if state.users[mac]["time"] == 0 and state.users[mac]["status"] == "connected":
                state.users[mac]["status"] = "expired"
                firewall.block_user(mac)
            
            if action == "add" and state.users[mac]["time"] > 0 and state.users[mac]["status"] == "expired":
                 state.users[mac]["status"] = "connected"
                 firewall.allow_user(mac, state.users[mac].get("ip"))

            database.sync_user(mac, state.users[mac])

    def update_user_status(self, mac: str, new_status: str):
        if mac in state.users:
            state.users[mac]["status"] = new_status
            if new_status == "blocked": firewall.block_user(mac)
            database.sync_user(mac, state.users[mac])

    def delete_user(self, mac: str):
        if mac in state.users:
            firewall.block_user(mac)
            del state.users[mac]
            database.delete_user(mac)