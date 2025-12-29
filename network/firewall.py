import subprocess
import config
import os
import shutil

# Check if conntrack exists once at startup
CONNTRACK_PATH = shutil.which("conntrack")

def init_firewall():
    print("Initializing Firewall...")
    
    # 1. Base Policies & Cleanup
    cmds = [
        "iptables -F", 
        "iptables -t nat -F",
        "iptables -P FORWARD DROP", 
        "iptables -P INPUT ACCEPT",
        
        # 2. Allow DHCP (Crucial for connecting)
        f"iptables -A INPUT -i {config.LAN_INTERFACE} -p udp --dport 67 -j ACCEPT",
        
        # 3. Allow Traffic for Established Connections
        "iptables -A FORWARD -m state --state RELATED,ESTABLISHED -j ACCEPT",
        
        # 4. DNS TRAP (The Fix): Force ALL DNS to Orange Pi (10.0.0.1)
        f"iptables -t nat -A PREROUTING -i {config.LAN_INTERFACE} -p udp --dport 53 -j DNAT --to-destination 10.0.0.1:53",
        f"iptables -t nat -A PREROUTING -i {config.LAN_INTERFACE} -p tcp --dport 53 -j DNAT --to-destination 10.0.0.1:53",

        # 5. HTTP TRAP: Redirect unauthenticated web traffic to Portal
        f"iptables -t nat -A PREROUTING -i {config.LAN_INTERFACE} -p tcp --dport 80 -j DNAT --to-destination 10.0.0.1:80",
        
        # 6. Internet Sharing (NAT)
        f"iptables -t nat -A POSTROUTING -o {config.WAN_INTERFACE} -j MASQUERADE"
    ]
    
    for cmd in cmds: 
        subprocess.run(cmd.split())

def block_user(mac):
    print(f"Blocking User: {mac}")
    
    # 1. Remove Access Rules (Loop until all instances are gone)
    cmd_fwd = f"iptables -D FORWARD -m mac --mac-source {mac} -j ACCEPT"
    while subprocess.call(cmd_fwd.split(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0: pass
    
    cmd_nat = f"iptables -t nat -D PREROUTING -m mac --mac-source {mac} -j ACCEPT"
    while subprocess.call(cmd_nat.split(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0: pass 

    # 2. INSTANT KILL: Cut active connections
    try:
        # Find IP from ARP table (MAC -> IP)
        ip_cmd = f"arp -n | grep {mac} | awk '{{print $1}}'"
        try:
            user_ip = subprocess.check_output(ip_cmd, shell=True).decode().strip()
        except:
            user_ip = ""
        
        if user_ip and CONNTRACK_PATH:
            print(f"Cutting connections for {user_ip}...")
            subprocess.run([CONNTRACK_PATH, "-D", "-s", user_ip], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run([CONNTRACK_PATH, "-D", "-d", user_ip], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        print(f"Error killing connection: {e}")

def allow_user(mac):
    # Ensure they are clean first
    block_user(mac)
    
    print(f"Allowing User: {mac}")
    # 1. Insert ACCEPT at the TOP (-I 1) of PREROUTING
    subprocess.run(f"iptables -t nat -I PREROUTING 1 -m mac --mac-source {mac} -j ACCEPT".split())
    
    # 2. Insert ACCEPT at the TOP (-I 1) of FORWARD
    subprocess.run(f"iptables -I FORWARD 1 -m mac --mac-source {mac} -j ACCEPT".split())

# --- NEW FUNCTION FOR SMART AUTO-PAUSE ---
def get_user_bytes(mac: str) -> int:
    """
    Reads the data usage (in bytes) for a specific MAC address from iptables.
    Returns 0 if no rule found.
    """
    try:
        # List rules with exact byte counts (-x)
        res = subprocess.check_output(
            ["iptables", "-L", "FORWARD", "-v", "-n", "-x"], 
            text=True
        )
        
        for line in res.splitlines():
            # Find the rule corresponding to this MAC in the ACCEPT chain
            if mac.upper() in line.upper() and "ACCEPT" in line:
                parts = line.split()
                # IPTables output format: [pkts, bytes, target, prot, opt, in, out, source, dest]
                # The second column (index 1) is Bytes
                if len(parts) >= 2 and parts[1].isdigit():
                    return int(parts[1])
    except Exception as e:
        print(f"Firewall Read Error: {e}")
        
    return 0