# core/utils.py
import os

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
    """Determines which banner image to display."""
    if os.path.exists("static/banner_custom.jpg"): 
        return "/static/banner_custom.jpg"
    if os.path.exists("static/banner_default.jpg"):
        return "/static/banner_default.jpg"
    return ""