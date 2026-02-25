import subprocess
import config
import shutil
import os
import re
from core import state 

IPSET_NAME = "authorized_users"

# --- FIX: Better Conntrack Detection ---
CONNTRACK_PATH = shutil.which("conntrack")
if not CONNTRACK_PATH:
    if os.path.exists("/usr/sbin/conntrack"):
        CONNTRACK_PATH = "/usr/sbin/conntrack"
    elif os.path.exists("/usr/bin/conntrack"):
        CONNTRACK_PATH = "/usr/bin/conntrack"

def run_cmd(args, check=False):
    """Helper to run commands safely."""
    try:
        if isinstance(args, str):
            args = args.split()
        subprocess.run(args, check=check, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        pass

def get_uid(ip):
    try:
        parts = ip.split(".")
        uid = (int(parts[2]) * 256) + int(parts[3])
        return uid
    except:
        return 0

def init_firewall():
    print("🔥 Initializing Firewall (IPSet + TC)...")

    # 1. Enable Forwarding
    run_cmd("sysctl -w net.ipv4.ip_forward=1")

    # 2. Hardware Offload Disable (Fixes some throttling issues)
    try:
        subprocess.run(f"ethtool -K {config.LAN_INTERFACE} tso off gso off gro off".split())
    except Exception:
        pass

    # 3. Initialize IPSet (The high-performance list)
    # We add 'counters' to track data usage per user automatically
    run_cmd(f"ipset create {IPSET_NAME} hash:mac hashsize 1024 maxelem 65535 counters -exist")
    run_cmd(f"ipset flush {IPSET_NAME}")

    # 4. Standard IPTables Rules
    cmds = [
        # Flush Old Rules
        "iptables -F", 
        "iptables -t nat -F",
        "iptables -t mangle -F", 
        
        # Policies
        "iptables -P FORWARD DROP", 
        "iptables -P INPUT ACCEPT",
        
        # Allow DHCP (Critical for connection)
        f"iptables -A INPUT -i {config.LAN_INTERFACE} -p udp --dport 67:68 --sport 67:68 -j ACCEPT",
        
        # --- [CRITICAL FIX] IPSET RULES MOVED TO TOP ---
        # These must be BEFORE the 'Established' rule.
        # This ensures every packet hits the counter before being accepted.
        f"iptables -A FORWARD -i {config.LAN_INTERFACE} -m set --match-set {IPSET_NAME} src -j ACCEPT",
        f"iptables -A FORWARD -o {config.LAN_INTERFACE} -m set --match-set {IPSET_NAME} dst -j ACCEPT",
        # -----------------------------------------------

        # Allow Established Connections (Fallback / Server traffic)
        "iptables -A INPUT -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT",
        "iptables -A FORWARD -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT",
        "iptables -A INPUT -i lo -j ACCEPT",

        # --- PORTAL REDIRECTS ---
        # Allow DNS for everyone
        f"iptables -A FORWARD -i {config.LAN_INTERFACE} -p udp --dport 53 -j ACCEPT",
        f"iptables -t nat -A PREROUTING -i {config.LAN_INTERFACE} -p udp --dport 53 -j DNAT --to-destination 10.0.0.1:53",
        f"iptables -t nat -A PREROUTING -i {config.LAN_INTERFACE} -p tcp --dport 53 -j DNAT --to-destination 10.0.0.1:53",

        # Redirect HTTP (80) to Portal if NOT in IPSet
        f"iptables -t nat -A PREROUTING -i {config.LAN_INTERFACE} -m set ! --match-set {IPSET_NAME} src -p tcp --dport 80 -j DNAT --to-destination 10.0.0.1:80",
        
        # Block HTTPS (443) for unauthorized (Forces phone to fallback to HTTP/Portal)
        f"iptables -A FORWARD -i {config.LAN_INTERFACE} -m set ! --match-set {IPSET_NAME} src -p tcp --dport 443 -j DROP",

        # --- THE HOTSPOT KILLER (TTL = 1) ---
        f"iptables -t mangle -A POSTROUTING -o {config.LAN_INTERFACE} -j TTL --ttl-set 1",
        
        # Enable NAT
        f"iptables -t nat -A POSTROUTING -o {config.WAN_INTERFACE} -j MASQUERADE"
    ]
    
    for cmd in cmds: 
        run_cmd(cmd)

    # 5. Initialize Traffic Control (Speed Limiter)
    try:
        run_cmd(f"tc qdisc del dev {config.LAN_INTERFACE} root")
        run_cmd(f"tc qdisc del dev {config.LAN_INTERFACE} ingress")
        run_cmd(f"tc qdisc add dev {config.LAN_INTERFACE} root handle 1: htb default 10")
        run_cmd(f"tc class add dev {config.LAN_INTERFACE} parent 1: classid 1:ffff htb rate 1000mbit")
        run_cmd(f"tc qdisc add dev {config.LAN_INTERFACE} ingress")
    except Exception:
        pass
    
    print("✅ Firewall Initialized.")

# --- SPEED LIMITER FUNCTIONS ---

def remove_speed_limit(ip):
    if not ip: return
    try:
        uid = get_uid(ip)
        if uid > 0:
            run_cmd(f"tc class del dev {config.LAN_INTERFACE} parent 1:ffff classid 1:{uid:x}")
            run_cmd(f"tc filter del dev {config.LAN_INTERFACE} protocol ip parent 1:0 prio {uid}")
            run_cmd(f"tc filter del dev {config.LAN_INTERFACE} protocol ip parent ffff: prio {uid}")
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
        uid = get_uid(ip)
        if uid == 0: return
        
        cmd_dl = f"tc class add dev {config.LAN_INTERFACE} parent 1:ffff classid 1:{uid:x} htb rate {speed_str} ceil {speed_str} burst 15k cburst 15k"
        subprocess.run(cmd_dl.split(), capture_output=True)

        if gaming_mode:
            # Prioritize gaming packets (UDP/Small packets)
            run_cmd(f"tc qdisc add dev {config.LAN_INTERFACE} parent 1:{uid:x} handle {uid:x}: prio bands 2 priomap 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1")
            run_cmd(f"tc filter add dev {config.LAN_INTERFACE} protocol ip parent {uid:x}: prio 1 u32 match ip protocol 17 0xff match u16 0 0xfe00 at 2 flowid {uid:x}:1")
            run_cmd(f"tc filter add dev {config.LAN_INTERFACE} protocol ip parent {uid:x}: prio 1 u32 match ip protocol 1 0xff flowid {uid:x}:1")

        run_cmd(f"tc filter add dev {config.LAN_INTERFACE} protocol ip parent 1:0 prio {uid} u32 match ip dst {ip} flowid 1:{uid:x}")
        cmd_ul = f"tc filter add dev {config.LAN_INTERFACE} parent ffff: protocol ip prio {uid} u32 match ip src {ip} police rate {upload_kbps}kbit burst 12k drop flowid :1"
        subprocess.run(cmd_ul.split(), capture_output=True)
    except Exception: pass

def refresh_all_limits(users_dict):
    try:
        run_cmd(f"tc qdisc del dev {config.LAN_INTERFACE} ingress")
        run_cmd(f"tc qdisc add dev {config.LAN_INTERFACE} ingress")
    except: pass
    for mac, data in users_dict.items():
        if data.get("status") == "connected" and data.get("ip"):
            remove_speed_limit(data["ip"])
            apply_speed_limit(data["ip"])

# --- BLOCKING LOGIC (OPTIMIZED) ---

def block_user(mac, ip=None):
    # 1. Remove from IPSet (Instant block)
    run_cmd(["ipset", "del", IPSET_NAME, mac, "-exist"])

    # 2. Cleanup Speed Limits & Conntrack
    try:
        user_ip = ip
        if not user_ip:
            # Try to find IP via ARP if not provided
            ip_cmd = f"arp -n | grep {mac} | awk '{{print $1}}'"
            try: user_ip = subprocess.check_output(ip_cmd, shell=True).decode().strip()
            except: user_ip = ""
        
        if user_ip:
            remove_speed_limit(user_ip)
            # Kill active connections so they are forced to re-authenticate/block immediately
            if CONNTRACK_PATH:
                run_cmd([CONNTRACK_PATH, "-D", "-s", user_ip])
                run_cmd([CONNTRACK_PATH, "-D", "-d", user_ip])
    except Exception: pass

def allow_user(mac, ip=None):
    # 1. Add to IPSet (Instant allow)
    run_cmd(["ipset", "add", IPSET_NAME, mac, "-exist"])
    
    # 2. Apply Speed Limit
    if ip: apply_speed_limit(ip)

def get_user_traffic(mac: str):
    """
    Parses 'ipset list' to get traffic stats.
    Returns: (download_bytes, upload_bytes)
    Note: IPSet counters are often aggregated.
    """
    try:
        # We search for the MAC in the ipset list
        res = subprocess.check_output(["ipset", "list", IPSET_NAME], text=True)
        for line in res.splitlines():
            if mac.upper() in line.upper():
                match = re.search(r'bytes\s+(\d+)', line)
                if match:
                    total_bytes = int(match.group(1))
                    return total_bytes, 0
    except Exception: 
        pass
    return 0, 0

def get_all_traffic():
    """
    Fetches traffic stats for ALL users in one go.
    Optimization for Auto-Pause.
    Returns a dict: { 'mac_address': (bytes, packets) }
    """
    traffic_data = {}
    try:
        # Get the full list from IPSet
        res = subprocess.check_output(["ipset", "list", IPSET_NAME], text=True)
        
        # Parse output line by line
        for line in res.splitlines():
            parts = line.split()
            
            # ROBUST PARSING:
            # We don't count length anymore. We look for keywords.
            if "packets" in parts and "bytes" in parts:
                try:
                    # 1. Get MAC (Always the first item)
                    mac = parts[0].lower()
                    
                    # 2. Find where the numbers are hiding
                    pkt_index = parts.index("packets") + 1
                    byte_index = parts.index("bytes") + 1
                    
                    # 3. Extract Values
                    total_pkts = int(parts[pkt_index])
                    total_bytes = int(parts[byte_index])
                    
                    traffic_data[mac] = (total_bytes, total_pkts)
                except (ValueError, IndexError):
                    continue
                    
    except Exception as e:
        print(f"Firewall Traffic Error: {e}")
        pass
        
    return traffic_data