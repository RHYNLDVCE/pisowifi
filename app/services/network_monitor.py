import time
from core import database, state
from network import firewall

class NetworkMonitorService:
    def __init__(self, ws_sender):
        self.ws_sender = ws_sender

    def evaluate_all_connections(self):
        if not state.config.get("auto_pause_enabled", True): 
            return

        timeout_limit = int(state.config.get("inactive_timeout", 60))
        packet_limit = int(state.config.get("inactive_packet_threshold", 5))
        bytes_limit = int(state.config.get("inactive_bytes_threshold", 500))
        now = time.time()

        try: all_traffic_stats = firewall.get_all_traffic()
        except: all_traffic_stats = {}

        for mac, data in list(state.users.items()):
            if data.get("status") == "connected":
                curr_bytes, curr_packets = all_traffic_stats.get(mac, (0, 0))
                prev_bytes = data.get("last_byte_count", 0)
                prev_packets = data.get("last_packet_count", 0)
                
                # Baseline Init
                if prev_bytes == 0 and curr_bytes > 0:
                    data["last_byte_count"], data["last_packet_count"] = curr_bytes, curr_packets
                    data["last_active"] = now
                    continue

                diff_bytes = max(0, curr_bytes - prev_bytes)
                diff_packets = max(0, curr_packets - prev_packets)
                data["last_byte_count"], data["last_packet_count"] = curr_bytes, curr_packets

                is_active = (diff_bytes > bytes_limit) or (diff_packets >= packet_limit)
                
                if is_active:
                    data["last_active"] = now 
                else:
                    idle_time = int(now - data.get("last_active", now))
                    if idle_time > timeout_limit:
                        data["status"] = "paused"
                        try:
                            firewall.block_user(mac)
                            database.sync_user(mac, data)
                        except: pass
                        
                        self.ws_sender(mac, {
                            "type": "sync", 
                            "status": "paused", 
                            "time_remaining": data.get("time", 0)
                        })