import subprocess
import config
import shutil
import os
import re
from core import state 

# The name of the IPSet list where authorized users are stored
IPSET_NAME = "authorized_users"

# --- FIX: Better Conntrack Detection ---
CONNTRACK_PATH = shutil.which("conntrack")
if not CONNTRACK_PATH:
    if os.path.exists("/usr/sbin/conntrack"):
        CONNTRACK_PATH = "/usr/sbin/conntrack"
    elif os.path.exists("/usr/bin/conntrack"):
        CONNTRACK_PATH = "/usr/bin/conntrack"

def run_cmd(args, check=False):
    """Helper to run commands safely with OS lock protection."""
    try:
        if isinstance(args, str):
            args = args.split()
        # Timeout=2 to prevent OS deadlocks at midnight/log rotation
        subprocess.run(args, check=check, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
    except subprocess.TimeoutExpired:
        print(f"[Firewall Timeout] OS locked command: {' '.join(args)}", flush=True)
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
    print("Initializing Starlink-Optimized Firewall (IPSet + TC + Cloudflare DNS)...")

    # Enable BBR TCP Congestion Control for better throughput and lower latency
    run_cmd("sysctl -w net.core.default_qdisc=fq")
    run_cmd("sysctl -w net.ipv4.tcp_congestion_control=bbr")

    # 1. Enable IPv4 Forwarding & Disable IPv6 (Forces all traffic into our IPv4 rules)
    run_cmd("sysctl -w net.ipv4.ip_forward=1")
    run_cmd("sysctl -w net.ipv6.conf.all.disable_ipv6=1")
    run_cmd("sysctl -w net.ipv6.conf.default.disable_ipv6=1")
    
    # 2. Disable ECN - Helps with some CDN (Lazada) handshake stalls over Starlink
    run_cmd("sysctl -w net.ipv4.tcp_ecn=0")

    # 3. Hardware Offload Disable (Fixes some throttling/corruption issues on USB adapters)
    try:
        subprocess.run(f"ethtool -K {config.LAN_INTERFACE} tso off gso off gro off sg off".split())
    except Exception:
        pass

    # 4. Initialize IPSet
    run_cmd(f"ipset create {IPSET_NAME} hash:mac hashsize 1024 maxelem 65535 counters -exist")
    run_cmd(f"ipset flush {IPSET_NAME}")

    # 5. Standard IPTables Rules
    cmds = [
        # Flush Old Rules
        "iptables -F", 
        "iptables -t nat -F",
        "iptables -t mangle -F", 
        
        # [CRITICAL OPTIMIZATION] Accept Established Connections First
        "iptables -I INPUT 1 -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT",
        "iptables -I FORWARD 1 -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT",

        "iptables -t mangle -A PREROUTING -p udp -m multiport --sports 5000:5500,7074:7750,10000:10009,30000:30300 -j MARK --set-mark 99",
        "iptables -t mangle -A PREROUTING -p udp -m multiport --dports 5000:5500,7074:7750,10000:10009,30000:30300 -j MARK --set-mark 99",
        
        # Default Policies
        "iptables -P FORWARD DROP", 
        "iptables -P INPUT ACCEPT",
        
        # Allow DHCP
        f"iptables -A INPUT -i {config.LAN_INTERFACE} -p udp --dport 67:68 --sport 67:68 -j ACCEPT",
        
        # --- [CRITICAL] AUTHORIZED USER ACCESS ---
        f"iptables -A FORWARD -i {config.LAN_INTERFACE} -m set --match-set {IPSET_NAME} src -j ACCEPT",
        f"iptables -A FORWARD -o {config.LAN_INTERFACE} -m set --match-set {IPSET_NAME} dst -j ACCEPT",

        "iptables -A INPUT -i lo -j ACCEPT",

        # --- DNS & PORTAL REDIRECTS ---
        # Allow DNS forwarding generally
        f"iptables -A FORWARD -i {config.LAN_INTERFACE} -p udp --dport 53 -j ACCEPT",
        f"iptables -A FORWARD -i {config.LAN_INTERFACE} -p tcp --dport 53 -j ACCEPT",
        
        # [STARLINK DNS FIX] Force Authorized users to Cloudflare DNS (1.1.1.1) to fix Geo-IP CDNs
        f"iptables -t nat -A PREROUTING -m set --match-set {IPSET_NAME} src -p udp --dport 53 -j DNAT --to-destination 1.1.1.1:53",
        f"iptables -t nat -A PREROUTING -m set --match-set {IPSET_NAME} src -p tcp --dport 53 -j DNAT --to-destination 1.1.1.1:53",

        # Redirect Unauthorized DNS to local portal (10.0.0.1)
        f"iptables -t nat -A PREROUTING -i {config.LAN_INTERFACE} -m set ! --match-set {IPSET_NAME} src -p udp --dport 53 -j DNAT --to-destination 10.0.0.1:53",
        f"iptables -t nat -A PREROUTING -i {config.LAN_INTERFACE} -m set ! --match-set {IPSET_NAME} src -p tcp --dport 53 -j DNAT --to-destination 10.0.0.1:53",

        # Redirect Unauthorized HTTP (80) to Portal
        f"iptables -t nat -A PREROUTING -i {config.LAN_INTERFACE} -m set ! --match-set {IPSET_NAME} src -p tcp --dport 80 -j DNAT --to-destination 10.0.0.1:80",
        
        # Block Unauthorized HTTPS (443) with DROP (iPhone Compatibility)
        f"iptables -A FORWARD -i {config.LAN_INTERFACE} -m set ! --match-set {IPSET_NAME} src -p tcp --dport 443 -j DROP",

        # --- STARLINK MSS CLAMPING (Hardcoded to 1300 to survive satellite CGNAT overhead) ---
        "iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --set-mss 1300",

        # --- THE HOTSPOT KILLER (TTL=1) ---
        f"iptables -t mangle -A POSTROUTING -o {config.LAN_INTERFACE} -j TTL --ttl-set 1",
        
        # Enable NAT (MASQUERADE is required for Starlink dynamic CGNAT IPs)
        f"iptables -t nat -A POSTROUTING -o {config.WAN_INTERFACE} -j MASQUERADE"
    ]
    
    for cmd in cmds: 
        run_cmd(cmd)

    # 6. Initialize Traffic Control (Speed Limiter)
    try:
        run_cmd(f"tc qdisc del dev {config.LAN_INTERFACE} root")
        run_cmd(f"tc qdisc del dev {config.LAN_INTERFACE} ingress")
        run_cmd(f"tc qdisc add dev {config.LAN_INTERFACE} root handle 1: htb default 10")
        run_cmd(f"tc class add dev {config.LAN_INTERFACE} parent 1: classid 1:ffff htb rate 1000mbit")
        run_cmd(f"tc qdisc add dev {config.LAN_INTERFACE} ingress")
    except Exception:
        pass
    
    print("Firewall Initialized.")

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
        
        # Create user class
        cmd_dl = f"tc class add dev {config.LAN_INTERFACE} parent 1:ffff classid 1:{uid:x} htb rate {speed_str} ceil {speed_str} burst 15k cburst 15k"
        subprocess.run(cmd_dl.split(), capture_output=True)

        if gaming_mode:
            # Replace the manual 'prio' bands with fq_codel. 
            # FQ_CoDel is far superior at natively interleaving gaming UDP packets ahead of TCP streams.
            run_cmd(f"tc qdisc add dev {config.LAN_INTERFACE} parent 1:{uid:x} handle {uid:x}: fq_codel quantum 300 limit 1000")
        else:
            # Standard fq_codel for non-gaming mode
            run_cmd(f"tc qdisc add dev {config.LAN_INTERFACE} parent 1:{uid:x} handle {uid:x}: fq_codel")

        # Map user's traffic to the class
        run_cmd(f"tc filter add dev {config.LAN_INTERFACE} protocol ip parent 1:0 prio {uid} u32 match ip dst {ip} flowid 1:{uid:x}")
        
        # Upload Limit (Policing)
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

# --- BLOCKING & AUTHORIZATION LOGIC ---

def block_user(mac, ip=None):
    # 1. Remove from IPSet (Instant block)
    run_cmd(["ipset", "del", IPSET_NAME, mac, "-exist"])

    # 2. Cleanup Speed Limits & Conntrack
    try:
        user_ip = ip
        if not user_ip:
            ip_cmd = f"arp -n | grep {mac} | awk '{{print $1}}'"
            try: user_ip = subprocess.check_output(ip_cmd, shell=True).decode().strip()
            except: user_ip = ""
        
        if user_ip:
            remove_speed_limit(user_ip)
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
    try:
        res = subprocess.check_output(["ipset", "list", IPSET_NAME], text=True)
        for line in res.splitlines():
            if mac.upper() in line.upper():
                match = re.search(r'bytes\s+(\d+)', line)
                if match:
                    total_bytes = int(match.group(1))
                    return total_bytes, 0
    except Exception: pass
    return 0, 0

def get_all_traffic():
    traffic_data = {}
    try:
        res = subprocess.check_output(["ipset", "list", IPSET_NAME], text=True)
        for line in res.splitlines():
            parts = line.split()
            if "packets" in parts and "bytes" in parts:
                try:
                    mac = parts[0].lower()
                    pkt_index = parts.index("packets") + 1
                    byte_index = parts.index("bytes") + 1
                    traffic_data[mac] = (int(parts[byte_index]), int(parts[pkt_index]))
                except (ValueError, IndexError): continue
    except Exception: pass
    return traffic_data