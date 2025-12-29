import subprocess
import config
import shutil
from core import state 

CONNTRACK_PATH = shutil.which("conntrack")

def init_firewall():
    print("Initializing Firewall...")
    
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
    # We create a "Hierarchy": 
    # ROOT (1Gbps) -> BRANCHES (User Limits)
    try:
        print("Initializing Traffic Control (TC)...")
        
        # Clear any existing limits to start fresh
        subprocess.run(f"tc qdisc del dev {config.LAN_INTERFACE} root".split(), stderr=subprocess.DEVNULL)
        
        # A. Create the ROOT QDisc (The Foundation)
        subprocess.run(f"tc qdisc add dev {config.LAN_INTERFACE} root handle 1: htb default 10".split())
        
        # B. Create the MAIN PIPE (Parent Class 1:9999)
        # We set this to 1000mbit (1 Gigabit) so the LAN itself is never throttled.
        # All user limits will be children of this huge pipe.
        subprocess.run(f"tc class add dev {config.LAN_INTERFACE} parent 1: classid 1:9999 htb rate 1000mbit".split())
        
    except Exception as e:
        print(f"TC Init Error: {e}")

# --- SPEED LIMITER FUNCTIONS ---

def apply_speed_limit(ip):
    """
    Creates a dedicated "Branch" for this specific IP with the speed limit.
    """
    if not ip: return
    
    # Check if Speed Limit feature is enabled in Admin
    if not state.config.get("speed_limit_enabled", False):
        return 
        
    # Get the limit set by Admin (e.g., 5 or 10)
    speed_val = state.config.get("global_speed_limit", 5)
    speed_str = f"{speed_val}mbit"

    try:
        # Use the last number of the IP as the unique Class ID
        # Example: IP 10.0.0.182 -> ID 182
        uid = ip.split(".")[-1]
        
        # 1. Create the User's Personal Class (Branch)
        # We attach it to Parent 1:9999 (The 1Gbps Pipe)
        # We limit THIS branch to 'speed_str' (e.g. 10mbit)
        subprocess.run(f"tc class add dev {config.LAN_INTERFACE} parent 1:9999 classid 1:{uid} htb rate {speed_str} ceil {speed_str}".split(), stderr=subprocess.DEVNULL)
        
        # 2. Filter Traffic: Direct ONLY this IP's traffic into that Class
        subprocess.run(f"tc filter add dev {config.LAN_INTERFACE} protocol ip parent 1:0 prio 1 u32 match ip dst {ip} flowid 1:{uid}".split(), stderr=subprocess.DEVNULL)
        
        print(f"🚀 Speed Limit Applied: User {ip} -> {speed_str} (Parent: 1Gbps)")
        
    except Exception as e:
        print(f"Limit Error: {e}")

def remove_speed_limit(ip):
    """Removes the personal branch for this IP."""
    if not ip: return
    try:
        uid = ip.split(".")[-1]
        # Deleting the class automatically deletes the filter associated with it
        subprocess.run(f"tc class del dev {config.LAN_INTERFACE} parent 1:9999 classid 1:{uid}".split(), stderr=subprocess.DEVNULL)
    except:
        pass

# --- CORE FUNCTIONS ---

def block_user(mac):
    print(f"Blocking User: {mac}")
    
    # 1. Remove Firewall Access
    cmd_fwd = f"iptables -D FORWARD -m mac --mac-source {mac} -j ACCEPT"
    while subprocess.call(cmd_fwd.split(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0: pass
    
    cmd_nat = f"iptables -t nat -D PREROUTING -m mac --mac-source {mac} -j ACCEPT"
    while subprocess.call(cmd_nat.split(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0: pass 

    # 2. Kill Connections & Remove Speed Limit
    try:
        ip_cmd = f"arp -n | grep {mac} | awk '{{print $1}}'"
        try:
            user_ip = subprocess.check_output(ip_cmd, shell=True).decode().strip()
        except:
            user_ip = ""
        
        if user_ip:
            # IMPORTANT: Clean up their speed limit rule when they are blocked
            remove_speed_limit(user_ip)
            
            if CONNTRACK_PATH:
                print(f"Cutting connections for {user_ip}...")
                subprocess.run([CONNTRACK_PATH, "-D", "-s", user_ip], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                subprocess.run([CONNTRACK_PATH, "-D", "-d", user_ip], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        print(f"Error killing connection: {e}")

def allow_user(mac, ip=None):
    # Ensure they are clean first
    block_user(mac)
    
    print(f"Allowing User: {mac} (IP: {ip})")
    
    # 1. Apply Speed Limit (Creates the 10Mbps branch for this user)
    if ip:
        apply_speed_limit(ip)

    # 2. Open Firewall
    subprocess.run(f"iptables -t nat -I PREROUTING 1 -m mac --mac-source {mac} -j ACCEPT".split())
    subprocess.run(f"iptables -I FORWARD 1 -m mac --mac-source {mac} -j ACCEPT".split())

def get_user_bytes(mac: str) -> int:
    try:
        res = subprocess.check_output(
            ["iptables", "-L", "FORWARD", "-v", "-n", "-x"], 
            text=True
        )
        for line in res.splitlines():
            if mac.upper() in line.upper() and "ACCEPT" in line:
                parts = line.split()
                if len(parts) >= 2 and parts[1].isdigit():
                    return int(parts[1])
    except Exception as e:
        print(f"Firewall Read Error: {e}")
    return 0