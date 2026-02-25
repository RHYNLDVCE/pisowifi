import subprocess
import time
import os

# --- SETTINGS ---
# This matches your config.json settings
PACKET_THRESHOLD = 2   
BYTES_THRESHOLD = 100
# ----------------

def get_stats():
    data = {}
    try:
        # Run ipset list
        res = subprocess.check_output("ipset list authorized_users", shell=True, text=True)
        for line in res.splitlines():
            parts = line.split()
            if "packets" in parts and "bytes" in parts:
                try:
                    mac = parts[0].upper() # Show in Upper for readability
                    
                    # Find the numbers flexibly
                    pkt_idx = parts.index("packets") + 1
                    byte_idx = parts.index("bytes") + 1
                    
                    packets = int(parts[pkt_idx])
                    bytes_val = int(parts[byte_idx])
                    
                    data[mac] = (packets, bytes_val)
                except:
                    continue
    except:
        pass
    return data

# --- MAIN LOOP ---
os.system('clear')
print("🚀 STARTING REAL-TIME MONITOR...")

prev_data = get_stats()

while True:
    time.sleep(2) # Check every 2 seconds
    curr_data = get_stats()
    
    os.system('clear')
    print(f"📡 LIVE TRAFFIC DASHBOARD ({time.strftime('%H:%M:%S')})")
    print(f"🎯 Threshold to stay active: >{PACKET_THRESHOLD} pkts OR >{BYTES_THRESHOLD} bytes")
    print("-" * 70)
    print(f"{'MAC ADDRESS':<18} | {'TOTAL PKTS':<12} | {'DIFF (2s)':<12} | {'STATUS'}")
    print("-" * 70)
    
    active_users = 0
    
    for mac, (curr_pkts, curr_bytes) in curr_data.items():
        active_users += 1
        
        # Get previous values (default to 0 if new)
        prev_pkts, prev_bytes = prev_data.get(mac, (0, 0))
        
        # Calculate the Difference (Activity)
        diff_pkts = curr_pkts - prev_pkts
        diff_bytes = curr_bytes - prev_bytes
        
        # Determine Status
        is_active = (diff_pkts >= PACKET_THRESHOLD) or (diff_bytes > BYTES_THRESHOLD)
        status_icon = "✅ ACTIVE" if is_active else "💤 IDLE"
        
        # Colorize output (if supported) or just text
        if is_active:
            row = f"\033[92m{mac:<18} | {curr_pkts:<12} | +{diff_pkts:<11} | {status_icon}\033[0m"
        else:
            row = f"{mac:<18} | {curr_pkts:<12} | +{diff_pkts:<11} | {status_icon}"
            
        print(row)
        
    if active_users == 0:
        print("⚠️  No users connected to Firewall.")
        
    print("-" * 70)
    print("Press CTRL+C to stop")
    
    # Update previous data for next loop
    prev_data = curr_data