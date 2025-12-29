import subprocess
import config
import shutil
from core import state 

CONNTRACK_PATH = shutil.which("conntrack")

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
    Uses the IP last octet as the unique Priority ID for clean removal.
    """
    if not ip: return
    try:
        uid = int(ip.split(".")[-1]) # Use IP end as unique ID
        
        # 1. Delete the Download Class (Traffic shaper)
        subprocess.run(f"tc class del dev {config.LAN_INTERFACE} parent 1:9999 classid 1:{uid}".split(), stderr=subprocess.DEVNULL)
        
        # 2. Delete the Download Filter (Targeting this IP)
        # We delete by PRIO matching the UID
        subprocess.run(f"tc filter del dev {config.LAN_INTERFACE} protocol ip parent 1:0 prio {uid}".split(), stderr=subprocess.DEVNULL)

        # 3. Delete the Upload Filter (Ingress)
        subprocess.run(f"tc filter del dev {config.LAN_INTERFACE} protocol ip parent ffff: prio {uid}".split(), stderr=subprocess.DEVNULL)
        
    except Exception:
        pass

def apply_speed_limit(ip):
    """
    Creates a dedicated "Branch" for this specific IP with the speed limit.
    Includes Burst, Upload Limits, and optionally Gaming Priority.
    """
    if not ip: return
    
    # --- STEP 1: CLEANUP FIRST (Fixes 'File exists' error) ---
    remove_speed_limit(ip)
    # ---------------------------------------------------------
    
    if not state.config.get("speed_limit_enabled", False):
        return 
        
    speed_val = state.config.get("global_speed_limit", 5)
    speed_str = f"{speed_val}mbit"
    upload_kbps = speed_val * 1024
    
    # Check if Gaming Mode is enabled
    gaming_mode = state.config.get("gaming_mode_enabled", False)

    try:
        # Use last octet as ID (e.g., 182)
        uid = int(ip.split(".")[-1])
        
        # 1. DOWNLOAD LIMIT (Traffic leaving Pi -> User)
        # Create the user's class with a Burst
        cmd_dl = f"tc class add dev {config.LAN_INTERFACE} parent 1:9999 classid 1:{uid} htb rate {speed_str} ceil {speed_str} burst 15k cburst 15k"
        res = subprocess.run(cmd_dl.split(), capture_output=True, text=True)
        if res.returncode != 0:
            print(f"❌ TC Download Error: {res.stderr.strip()}")

        # --- GAMING MODE LOGIC (PRIO QDisc) ---
        if gaming_mode:
            # Attach a PRIO qdisc to the User's Class
            subprocess.run(
                f"tc qdisc add dev {config.LAN_INTERFACE} parent 1:{uid} handle {uid}: prio bands 2 priomap 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1".split(),
                stderr=subprocess.DEVNULL
            )
            
            # Filter 1: UDP (Gaming) -> Band 0 (High Priority)
            subprocess.run(
                f"tc filter add dev {config.LAN_INTERFACE} protocol ip parent {uid}: prio 1 u32 match ip protocol 17 0xff flowid {uid}:1".split(),
                stderr=subprocess.DEVNULL
            )
            
            # Filter 2: ICMP (Ping) -> Band 0 (High Priority)
            subprocess.run(
                f"tc filter add dev {config.LAN_INTERFACE} protocol ip parent {uid}: prio 1 u32 match ip protocol 1 0xff flowid {uid}:1".split(),
                stderr=subprocess.DEVNULL
            )
            print(f"   🎮 Gaming Mode: Prioritizing UDP/ICMP for .{uid}")

        # --------------------------------------

        # Filter: Send IP traffic to this user's branch
        # We use 'prio {uid}' to give it a unique ID we can delete later
        subprocess.run(
            f"tc filter add dev {config.LAN_INTERFACE} protocol ip parent 1:0 prio {uid} u32 match ip dst {ip} flowid 1:{uid}".split(), 
            stderr=subprocess.DEVNULL
        )
        
        # 2. UPLOAD LIMIT
        # We use 'prio {uid}' here too for clean removal
        cmd_ul = f"tc filter add dev {config.LAN_INTERFACE} parent ffff: protocol ip prio {uid} u32 match ip src {ip} police rate {upload_kbps}kbit burst 12k drop flowid :1"
        res = subprocess.run(cmd_ul.split(), capture_output=True, text=True)
        if res.returncode != 0:
            print(f"❌ TC Upload Error: {res.stderr.strip()}")
        
        print(f"🚀 Speed Limit Applied: User {ip} -> {speed_str}")
        
    except Exception as e:
        print(f"Limit Error: {e}")

def refresh_all_limits(users_dict):
    print("🔄 Refreshing speed limits for all users...")
    
    # Clear ingress to prevent duplicates
    try:
        subprocess.run(f"tc qdisc del dev {config.LAN_INTERFACE} ingress".split(), stderr=subprocess.DEVNULL)
        subprocess.run(f"tc qdisc add dev {config.LAN_INTERFACE} ingress".split(), stderr=subprocess.DEVNULL)
    except: pass

    for mac, data in users_dict.items():
        if data.get("status") == "connected" and data.get("ip"):
            remove_speed_limit(data["ip"])
            apply_speed_limit(data["ip"])

# --- CORE FUNCTIONS (Block/Allow) ---

def block_user(mac):
    print(f"Blocking User: {mac}")
    
    cmd_fwd = f"iptables -D FORWARD -m mac --mac-source {mac} -j ACCEPT"
    while subprocess.call(cmd_fwd.split(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0: pass
    
    cmd_nat = f"iptables -t nat -D PREROUTING -m mac --mac-source {mac} -j ACCEPT"
    while subprocess.call(cmd_nat.split(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0: pass 

    try:
        ip_cmd = f"arp -n | grep {mac} | awk '{{print $1}}'"
        try:
            user_ip = subprocess.check_output(ip_cmd, shell=True).decode().strip()
        except:
            user_ip = ""
        
        if user_ip:
            remove_speed_limit(user_ip)
            if CONNTRACK_PATH:
                subprocess.run([CONNTRACK_PATH, "-D", "-s", user_ip], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                subprocess.run([CONNTRACK_PATH, "-D", "-d", user_ip], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        print(f"Error killing connection: {e}")

def allow_user(mac, ip=None):
    block_user(mac)
    print(f"Allowing User: {mac} (IP: {ip})")
    
    if ip:
        apply_speed_limit(ip)

    subprocess.run(f"iptables -t nat -I PREROUTING 1 -m mac --mac-source {mac} -j ACCEPT".split())
    subprocess.run(f"iptables -I FORWARD 1 -m mac --mac-source {mac} -j ACCEPT".split())

# --- NEW FUNCTION FOR PACKET MONITORING ---
def get_user_traffic(mac: str):
    """
    Returns a tuple: (bytes_used, packets_used)
    Required for accurate "Gaming Mode" activity detection.
    """
    try:
        # We read the FORWARD chain to get traffic stats
        res = subprocess.check_output(
            ["iptables", "-L", "FORWARD", "-v", "-n", "-x"], 
            text=True
        )
        for line in res.splitlines():
            if mac.upper() in line.upper() and "ACCEPT" in line:
                parts = line.split()
                # iptables -v output format:
                # pkts (0)    bytes (1)    target     ...
                if len(parts) >= 2:
                    packets = int(parts[0])
                    bytes_val = int(parts[1])
                    return bytes_val, packets
    except Exception:
        pass
    return 0, 0