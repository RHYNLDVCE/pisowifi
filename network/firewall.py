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
        # Even if user sets DNS to 8.8.8.8, we force it to us so we can spoof the portal
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
    # We remove the rules that allowed them to bypass the Trap
    cmd_fwd = f"iptables -D FORWARD -m mac --mac-source {mac} -j ACCEPT"
    while subprocess.call(cmd_fwd.split(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0: pass
    
    cmd_nat = f"iptables -t nat -D PREROUTING -m mac --mac-source {mac} -j ACCEPT"
    while subprocess.call(cmd_nat.split(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0: pass 

    # 2. INSTANT KILL: Cut active connections
    try:
        # Find IP from ARP table (MAC -> IP)
        ip_cmd = f"arp -n | grep {mac} | awk '{{print $1}}'"
        user_ip = subprocess.check_output(ip_cmd, shell=True).decode().strip()
        
        if user_ip and CONNTRACK_PATH:
            print(f"Cutting connections for {user_ip}...")
            # -D deletes the connection state, forcing the device to reconnect (and hit the firewall)
            subprocess.run([CONNTRACK_PATH, "-D", "-s", user_ip], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run([CONNTRACK_PATH, "-D", "-d", user_ip], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        print(f"Error killing connection: {e}")

def allow_user(mac):
    # Ensure they are clean first
    block_user(mac)
    
    print(f"Allowing User: {mac}")
    # 1. Insert ACCEPT at the TOP (-I 1) of PREROUTING
    # This bypasses the DNS Trap and HTTP Trap logic below it
    subprocess.run(f"iptables -t nat -I PREROUTING 1 -m mac --mac-source {mac} -j ACCEPT".split())
    
    # 2. Insert ACCEPT at the TOP (-I 1) of FORWARD
    # This bypasses the default DROP policy
    subprocess.run(f"iptables -I FORWARD 1 -m mac --mac-source {mac} -j ACCEPT".split())