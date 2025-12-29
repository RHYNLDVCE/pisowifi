# core/utils.py
import os
import subprocess

def get_mac(ip: str) -> str:
    """Retrieves MAC address from ARP table based on IP."""
    try:
        with open('/proc/net/arp') as f:
            for line in f.readlines():
                parts = line.split()
                if len(parts) > 3 and parts[0] == ip: 
                    return parts[3]
    except Exception: 
        pass
    return "00:00:00:00:00:00"

def get_banner_image() -> str:
    if os.path.exists("static/banner_custom.jpg"): 
        return "/static/banner_custom.jpg"
    if os.path.exists("static/banner_default.jpg"):
        return "/static/banner_default.jpg"
    return ""

def is_device_online(ip: str) -> bool:
    """Checks if a device is reachable via Ping."""
    if not ip: return False
    try:
        # Ping with 1 packet, 1 second timeout to be fast
        # Returns 0 (True) on success, non-zero (False) on failure
        subprocess.check_call(
            ["ping", "-c", "1", "-W", "1", ip],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        return True
    except:
        return False