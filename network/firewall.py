import subprocess
import config
import shutil
import os
from core import state 

# --- FIX: Better Conntrack Detection ---
CONNTRACK_PATH = shutil.which("conntrack")
if not CONNTRACK_PATH:
    # Common fallback paths for Linux/OrangePi
    if os.path.exists("/usr/sbin/conntrack"):
        CONNTRACK_PATH = "/usr/sbin/conntrack"
    elif os.path.exists("/usr/bin/conntrack"):
        CONNTRACK_PATH = "/usr/bin/conntrack"

def init_firewall():
    print("Initializing Firewall...")

    # --- FIX: Disable Offloading for Accurate Speed Limiting ---
    try:
        print(f"🔌 Disabling Offloading on {config.LAN_INTERFACE}...")
        subprocess.run(f"ethtool -K {config.LAN_INTERFACE} tso off gso off gro off".split())
    except Exception as e:
        print(f"⚠️ Could not disable offloading: {e}")
    # -----------------------------------------------------------
    
    # 1. Standard IPTables Rules
    cmds = [
        "iptables -F", 
        "iptables -t nat -F",
        "iptables -P FORWARD DROP", 
        "iptables -P INPUT ACCEPT",
        f"iptables -A INPUT -i {config.LAN_INTERFACE} -p udp --dport 67 -j ACCEPT",
        # NOTE: This established rule is what was allowing games to persist. 
        # Our new block_user function will override this by inserting DROP rules above it.
        "iptables -A FORWARD -m state --state RELATED,ESTABLISHED -j ACCEPT",
        f"iptables -t nat -A PREROUTING -i {config.LAN_INTERFACE} -p udp --dport 53 -j DNAT --to-destination 10.0.0.1:53",
        f"iptables -t nat -A PREROUTING -i {config.LAN_INTERFACE} -p tcp --dport 53 -j DNAT --to-destination 10.0.0.1:53",
        f"iptables -t nat -A PREROUTING -i {config.LAN_INTERFACE} -p tcp --dport 80 -j DNAT --to-destination 10.0.0.1:80",
        f"iptables -t nat -A POSTROUTING -o {config.WAN_INTERFACE} -j MASQUERADE"
    ]
    for cmd in cmds: 
        subprocess.run(cmd.split())

    # 2. Initialize Traffic Control (The Speed Limit System)
    try:
        print("Initializing Traffic Control (TC)...")
        
        # Clear existing limits
        subprocess.run(f"tc qdisc del dev {config.LAN_INTERFACE} root".split(), stderr=subprocess.DEVNULL)
        subprocess.run(f"tc qdisc del dev {config.LAN_INTERFACE} ingress".split(), stderr=subprocess.DEVNULL)
        
        # A. Create Root QDisc
        subprocess.run(f"tc qdisc add dev {config.LAN_INTERFACE} root handle 1: htb default 10".split())
        
        # B. Create Main Pipe (1Gbps)
        subprocess.run(f"tc class add dev {config.LAN_INTERFACE} parent 1: classid 1:9999 htb rate 1000mbit".split())

        # C. Enable Ingress (For Upload Limits)
        subprocess.run(f"tc qdisc add dev {config.LAN_INTERFACE} ingress".split(), stderr=subprocess.DEVNULL)
        
    except Exception as e:
        print(f"TC Init Error: {e}")

# --- SPEED LIMITER FUNCTIONS ---

def remove_speed_limit(ip):
    """
    Removes the speed limit class and filters for a specific IP.
    """
    if not ip: return
    try:
        uid = int(ip.split(".")[-1]) # Use IP end as unique ID
        
        # 1. Delete the Download Class (Traffic shaper)
        subprocess.run(f"tc class del dev {config.LAN_INTERFACE} parent 1:9999 classid 1:{uid}".split(), stderr=subprocess.DEVNULL)
        
        # 2. Delete the Download Filter (Targeting this IP)
        subprocess.run(f"tc filter del dev {config.LAN_INTERFACE} protocol ip parent 1:0 prio {uid}".split(), stderr=subprocess.DEVNULL)

        # 3. Delete the Upload Filter (Ingress)
        subprocess.run(f"tc filter del dev {config.LAN_INTERFACE} protocol ip parent ffff: prio {uid}".split(), stderr=subprocess.DEVNULL)
        
    except Exception:
        pass

def apply_speed_limit(ip):
    """
    Creates a dedicated "Branch" for this specific IP with the speed limit.
    """
    if not ip: return
    
    # --- STEP 1: CLEANUP FIRST ---
    remove_speed_limit(ip)
    # -----------------------------
    
    if not state.config.get("speed_limit_enabled", False):
        return 
        
    speed_val = state.config.get("global_speed_limit", 5)
    speed_str = f"{speed_val}mbit"
    upload_kbps = speed_val * 1024
    
    # Check if Gaming Mode is enabled
    gaming_mode = state.config.get("gaming_mode_enabled", False)

    try:
        uid = int(ip.split(".")[-1])
        
        # 1. DOWNLOAD LIMIT
        cmd_dl = f"tc class add dev {config.LAN_INTERFACE} parent 1:9999 classid 1:{uid} htb rate {speed_str} ceil {speed_str} burst 15k cburst 15k"
        res = subprocess.run(cmd_dl.split(), capture_output=True, text=True)

        # --- GAMING MODE LOGIC (PRIO QDisc) ---
        if gaming_mode:
            subprocess.run(
                f"tc qdisc add dev {config.LAN_INTERFACE} parent 1:{uid} handle {uid}: prio bands 2 priomap 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1".split(),
                stderr=subprocess.DEVNULL
            )
            
            # Small UDP Packets (< 512 bytes) -> Band 0 (High Priority)
            subprocess.run(
                f"tc filter add dev {config.LAN_INTERFACE} protocol ip parent {uid}: prio 1 u32 match ip protocol 17 0xff match u16 0 0xfe00 at 2 flowid {uid}:1".split(),
                stderr=subprocess.DEVNULL
            )
            
            # ICMP (Ping) -> Band 0 (High Priority)
            subprocess.run(
                f"tc filter add dev {config.LAN_INTERFACE} protocol ip parent {uid}: prio 1 u32 match ip protocol 1 0xff flowid {uid}:1".split(),
                stderr=subprocess.DEVNULL
            )
        # --------------------------------------

        # Filter: Send IP traffic to this user's branch
        subprocess.run(
            f"tc filter add dev {config.LAN_INTERFACE} protocol ip parent 1:0 prio {uid} u32 match ip dst {ip} flowid 1:{uid}".split(), 
            stderr=subprocess.DEVNULL
        )
        
        # 2. UPLOAD LIMIT
        cmd_ul = f"tc filter add dev {config.LAN_INTERFACE} parent ffff: protocol ip prio {uid} u32 match ip src {ip} police rate {upload_kbps}kbit burst 12k drop flowid :1"
        subprocess.run(cmd_ul.split(), capture_output=True, text=True)
        
        print(f"🚀 Speed Limit Applied: User {ip} -> {speed_str}")
        
    except Exception as e:
        print(f"Limit Error: {e}")

def refresh_all_limits(users_dict):
    print("🔄 Refreshing speed limits for all users...")
    try:
        subprocess.run(f"tc qdisc del dev {config.LAN_INTERFACE} ingress".split(), stderr=subprocess.DEVNULL)
        subprocess.run(f"tc qdisc add dev {config.LAN_INTERFACE} ingress".split(), stderr=subprocess.DEVNULL)
    except: pass

    for mac, data in users_dict.items():
        if data.get("status") == "connected" and data.get("ip"):
            remove_speed_limit(data["ip"])
            apply_speed_limit(data["ip"])

# --- CORE FUNCTIONS (Block/Allow) ---

def block_user(mac, ip=None):
    """
    STRICT BLOCKING:
    1. Removes any 'ACCEPT' rules for the MAC.
    2. Inserts a 'DROP' rule at the TOP of the chain.
    3. Tries to kill existing connections via Conntrack.
    """
    print(f"⛔ STRICT BLOCKING User: {mac}")
    
    # 1. Remove any existing "Allow" rules (Clean up)
    cmd_fwd = f"iptables -D FORWARD -m mac --mac-source {mac} -j ACCEPT"
    while subprocess.call(cmd_fwd.split(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0: pass
    
    cmd_nat = f"iptables -t nat -D PREROUTING -m mac --mac-source {mac} -j ACCEPT"
    while subprocess.call(cmd_nat.split(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0: pass 

    # 2. [IMPORTANT] Insert an explicit DROP rule at position 1.
    #    This overrides the "RELATED,ESTABLISHED" rule.
    #    First, ensure we don't duplicate it.
    cmd_drop = f"iptables -D FORWARD -m mac --mac-source {mac} -j DROP"
    while subprocess.call(cmd_drop.split(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0: pass
    
    #    Insert the DROP rule
    subprocess.run(f"iptables -I FORWARD 1 -m mac --mac-source {mac} -j DROP".split())

    # 3. Kill Active Connections (Conntrack)
    try:
        user_ip = ip
        if not user_ip:
            # Try to find IP if not provided
            ip_cmd = f"arp -n | grep {mac} | awk '{{print $1}}'"
            try:
                user_ip = subprocess.check_output(ip_cmd, shell=True).decode().strip()
            except:
                user_ip = ""
        
        if user_ip:
            remove_speed_limit(user_ip)
            if CONNTRACK_PATH:
                # Force delete all connections for this IP
                subprocess.run([CONNTRACK_PATH, "-D", "-s", user_ip], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                subprocess.run([CONNTRACK_PATH, "-D", "-d", user_ip], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                print(f"   🔪 Killed connections for {user_ip}")
            else:
                print("   ⚠️ Conntrack not found, relying on IPTables DROP.")
    except Exception as e:
        print(f"Error killing connection: {e}")

def allow_user(mac, ip=None):
    """
    Allows a user by removing the DROP rule and adding an ACCEPT rule.
    """
    # 1. Clean up potential old rules
    #    We DO NOT call block_user() here because it adds a DROP rule.
    #    Instead, we manually ensure the DROP rule is gone.
    
    print(f"✅ Allowing User: {mac} (IP: {ip})")
    
    # Remove Strict DROP rule if it exists
    cmd_drop = f"iptables -D FORWARD -m mac --mac-source {mac} -j DROP"
    while subprocess.call(cmd_drop.split(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0: pass

    # Remove old ACCEPT rules (just in case)
    cmd_fwd = f"iptables -D FORWARD -m mac --mac-source {mac} -j ACCEPT"
    while subprocess.call(cmd_fwd.split(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0: pass
    
    cmd_nat = f"iptables -t nat -D PREROUTING -m mac --mac-source {mac} -j ACCEPT"
    while subprocess.call(cmd_nat.split(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0: pass 

    # 2. Apply Speed Limits
    if ip:
        apply_speed_limit(ip)

    # 3. Add ACCEPT rules (Insert at top)
    subprocess.run(f"iptables -t nat -I PREROUTING 1 -m mac --mac-source {mac} -j ACCEPT".split())
    subprocess.run(f"iptables -I FORWARD 1 -m mac --mac-source {mac} -j ACCEPT".split())

# --- NEW FUNCTION FOR PACKET MONITORING ---
def get_user_traffic(mac: str):
    try:
        # We read the FORWARD chain to get traffic stats
        res = subprocess.check_output(
            ["iptables", "-L", "FORWARD", "-v", "-n", "-x"], 
            text=True
        )
        for line in res.splitlines():
            if mac.upper() in line.upper() and "ACCEPT" in line:
                parts = line.split()
                if len(parts) >= 2:
                    packets = int(parts[0])
                    bytes_val = int(parts[1])
                    return bytes_val, packets
    except Exception:
        pass
    return 0, 0