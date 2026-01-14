import subprocess
import config
import shutil
import os
from core import state 

# --- FIX: Better Conntrack Detection ---
CONNTRACK_PATH = shutil.which("conntrack")
if not CONNTRACK_PATH:
    if os.path.exists("/usr/sbin/conntrack"):
        CONNTRACK_PATH = "/usr/sbin/conntrack"
    elif os.path.exists("/usr/bin/conntrack"):
        CONNTRACK_PATH = "/usr/bin/conntrack"

# --- HELPER: CALCULATE UNIQUE ID FOR BIG NETWORKS ---
def get_uid(ip):
    """
    Generates a unique ID (1-65535) from an IP address.
    Supports /16 or /22 networks (e.g., 10.0.0.50 and 10.0.1.50 get different IDs).
    """
    try:
        parts = ip.split(".")
        # Math: (3rd_Octet * 256) + 4th_Octet
        # Example: 10.0.1.50 -> (1 * 256) + 50 = 306
        uid = (int(parts[2]) * 256) + int(parts[3])
        return uid
    except:
        return 0

def init_firewall():
    print("Initializing Firewall...")

    # Disable Offloading (Critical for speed limits)
    try:
        subprocess.run(f"ethtool -K {config.LAN_INTERFACE} tso off gso off gro off".split())
    except Exception:
        pass
    
    # 1. Standard IPTables Rules
    cmds = [
        "iptables -F", 
        "iptables -t nat -F",
        "iptables -P FORWARD DROP", 
        "iptables -P INPUT ACCEPT",
        
        # Allow DHCP (Critical)
        f"iptables -A INPUT -i {config.LAN_INTERFACE} -p udp --dport 67 -j ACCEPT",
        
        # Allow Established Connections
        # (This will be overridden by block_user for specific users)
        "iptables -A FORWARD -m state --state RELATED,ESTABLISHED -j ACCEPT",
        
        # --- GENERIC TRAPS ---
        # Reject 443 (HTTPS) globally for unknown users to trigger portal
        f"iptables -A FORWARD -i {config.LAN_INTERFACE} -p tcp --dport 443 -j REJECT --reject-with tcp-reset",
        
        # Redirect DNS
        f"iptables -t nat -A PREROUTING -i {config.LAN_INTERFACE} -p udp --dport 53 -j DNAT --to-destination 10.0.0.1:53",
        f"iptables -t nat -A PREROUTING -i {config.LAN_INTERFACE} -p tcp --dport 53 -j DNAT --to-destination 10.0.0.1:53",
        
        # Redirect HTTP
        f"iptables -t nat -A PREROUTING -i {config.LAN_INTERFACE} -p tcp --dport 80 -j DNAT --to-destination 10.0.0.1:80",
        
        # Allow Internet for Allowed Users
        f"iptables -t nat -A POSTROUTING -o {config.WAN_INTERFACE} -j MASQUERADE"
    ]
    for cmd in cmds: 
        subprocess.run(cmd.split())

    # 2. Initialize Traffic Control
    try:
        subprocess.run(f"tc qdisc del dev {config.LAN_INTERFACE} root".split(), stderr=subprocess.DEVNULL)
        subprocess.run(f"tc qdisc del dev {config.LAN_INTERFACE} ingress".split(), stderr=subprocess.DEVNULL)
        subprocess.run(f"tc qdisc add dev {config.LAN_INTERFACE} root handle 1: htb default 10".split())
        # Changed to classid 1:ffff to ensure it doesn't conflict with user IDs
        subprocess.run(f"tc class add dev {config.LAN_INTERFACE} parent 1: classid 1:ffff htb rate 1000mbit".split())
        subprocess.run(f"tc qdisc add dev {config.LAN_INTERFACE} ingress".split(), stderr=subprocess.DEVNULL)
    except Exception:
        pass

# --- SPEED LIMITER FUNCTIONS ---

def remove_speed_limit(ip):
    if not ip: return
    try:
        uid = get_uid(ip) # Use new math
        if uid > 0:
            # Note: TC uses Hexadecimal for IDs (1:{uid:x})
            subprocess.run(f"tc class del dev {config.LAN_INTERFACE} parent 1:ffff classid 1:{uid:x}".split(), stderr=subprocess.DEVNULL)
            subprocess.run(f"tc filter del dev {config.LAN_INTERFACE} protocol ip parent 1:0 prio {uid}".split(), stderr=subprocess.DEVNULL)
            subprocess.run(f"tc filter del dev {config.LAN_INTERFACE} protocol ip parent ffff: prio {uid}".split(), stderr=subprocess.DEVNULL)
    except Exception: pass

def apply_speed_limit(ip):
    if not ip: return
    remove_speed_limit(ip)
    if not state.config.get("speed_limit_enabled", False): return 
    
    speed_val = state.config.get("global_speed_limit", 5)
    speed_str = f"{speed_val}mbit"
    upload_kbps = speed_val * 1024
    gaming_mode = state.config.get("gaming_mode_enabled", False)

    try:
        uid = get_uid(ip) # Use new math
        if uid == 0: return
        
        # Note: TC uses Hexadecimal for IDs (1:{uid:x})
        cmd_dl = f"tc class add dev {config.LAN_INTERFACE} parent 1:ffff classid 1:{uid:x} htb rate {speed_str} ceil {speed_str} burst 15k cburst 15k"
        subprocess.run(cmd_dl.split(), capture_output=True)

        if gaming_mode:
            subprocess.run(f"tc qdisc add dev {config.LAN_INTERFACE} parent 1:{uid:x} handle {uid:x}: prio bands 2 priomap 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1".split(), stderr=subprocess.DEVNULL)
            subprocess.run(f"tc filter add dev {config.LAN_INTERFACE} protocol ip parent {uid:x}: prio 1 u32 match ip protocol 17 0xff match u16 0 0xfe00 at 2 flowid {uid:x}:1".split(), stderr=subprocess.DEVNULL)
            subprocess.run(f"tc filter add dev {config.LAN_INTERFACE} protocol ip parent {uid:x}: prio 1 u32 match ip protocol 1 0xff flowid {uid:x}:1".split(), stderr=subprocess.DEVNULL)

        subprocess.run(f"tc filter add dev {config.LAN_INTERFACE} protocol ip parent 1:0 prio {uid} u32 match ip dst {ip} flowid 1:{uid:x}".split(), stderr=subprocess.DEVNULL)
        cmd_ul = f"tc filter add dev {config.LAN_INTERFACE} parent ffff: protocol ip prio {uid} u32 match ip src {ip} police rate {upload_kbps}kbit burst 12k drop flowid :1"
        subprocess.run(cmd_ul.split(), capture_output=True)
    except Exception: pass

def refresh_all_limits(users_dict):
    try:
        subprocess.run(f"tc qdisc del dev {config.LAN_INTERFACE} ingress".split(), stderr=subprocess.DEVNULL)
        subprocess.run(f"tc qdisc add dev {config.LAN_INTERFACE} ingress".split(), stderr=subprocess.DEVNULL)
    except: pass
    for mac, data in users_dict.items():
        if data.get("status") == "connected" and data.get("ip"):
            remove_speed_limit(data["ip"])
            apply_speed_limit(data["ip"])

# --- BLOCKING LOGIC ---

def block_user(mac, ip=None):
    """
    STRICT BLOCKING + POPUP FIX
    """
    # 1. Clean up old Allow/Drop rules
    cmd_fwd = f"iptables -D FORWARD -m mac --mac-source {mac} -j ACCEPT"
    while subprocess.call(cmd_fwd.split(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0: pass
    
    cmd_nat = f"iptables -t nat -D PREROUTING -m mac --mac-source {mac} -j ACCEPT"
    while subprocess.call(cmd_nat.split(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0: pass 

    cmd_drop = f"iptables -D FORWARD -m mac --mac-source {mac} -j DROP"
    while subprocess.call(cmd_drop.split(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0: pass

    cmd_reject = f"iptables -D FORWARD -m mac --mac-source {mac} -p tcp --dport 443 -j REJECT --reject-with tcp-reset"
    while subprocess.call(cmd_reject.split(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0: pass

    # 2. INSERT RULES IN SPECIFIC ORDER
    # We want REJECT (443) to be FIRST, and DROP (All) to be SECOND.
    # Since we use -I (Insert at Top), we add the last rule first.
    
    # A. Add DROP (Will be pushed to Position 2)
    subprocess.run(f"iptables -I FORWARD 1 -m mac --mac-source {mac} -j DROP".split())
    
    # B. Add REJECT HTTPS (Will be pushed to Position 1 - TOP PRIORITY)
    subprocess.run(f"iptables -I FORWARD 1 -m mac --mac-source {mac} -p tcp --dport 443 -j REJECT --reject-with tcp-reset".split())

    # 3. Kill Connections
    try:
        user_ip = ip
        if not user_ip:
            ip_cmd = f"arp -n | grep {mac} | awk '{{print $1}}'"
            try:
                user_ip = subprocess.check_output(ip_cmd, shell=True).decode().strip()
            except: user_ip = ""
        
        if user_ip:
            remove_speed_limit(user_ip)
            if CONNTRACK_PATH:
                subprocess.run([CONNTRACK_PATH, "-D", "-s", user_ip], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                subprocess.run([CONNTRACK_PATH, "-D", "-d", user_ip], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception: pass

def allow_user(mac, ip=None):
    # 1. Clean up Blocking Rules
    # Remove REJECT Rule
    cmd_reject = f"iptables -D FORWARD -m mac --mac-source {mac} -p tcp --dport 443 -j REJECT --reject-with tcp-reset"
    while subprocess.call(cmd_reject.split(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0: pass

    # Remove DROP Rule
    cmd_drop = f"iptables -D FORWARD -m mac --mac-source {mac} -j DROP"
    while subprocess.call(cmd_drop.split(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0: pass

    # Remove old ACCEPT rules
    cmd_fwd = f"iptables -D FORWARD -m mac --mac-source {mac} -j ACCEPT"
    while subprocess.call(cmd_fwd.split(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0: pass
    
    cmd_nat = f"iptables -t nat -D PREROUTING -m mac --mac-source {mac} -j ACCEPT"
    while subprocess.call(cmd_nat.split(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0: pass 

    # 2. Apply Speed Limits
    if ip: apply_speed_limit(ip)

    # 3. Add ACCEPT rules (Top Priority)
    subprocess.run(f"iptables -t nat -I PREROUTING 1 -m mac --mac-source {mac} -j ACCEPT".split())
    subprocess.run(f"iptables -I FORWARD 1 -m mac --mac-source {mac} -j ACCEPT".split())

def get_user_traffic(mac: str):
    try:
        res = subprocess.check_output(["iptables", "-L", "FORWARD", "-v", "-n", "-x"], text=True)
        for line in res.splitlines():
            if mac.upper() in line.upper() and "ACCEPT" in line:
                parts = line.split()
                if len(parts) >= 2:
                    return int(parts[1]), int(parts[0])
    except Exception: pass
    return 0, 0