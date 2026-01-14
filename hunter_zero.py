import subprocess
import time
import os

# --- TARGET PIN ---
# We are forcing this to 0 based on your wiring
TARGET_PIN = "0"

def read_pin(pin):
    try:
        res = subprocess.check_output(["gpio", "read", pin])
        return int(res.strip())
    except:
        return 1

def setup_pin():
    os.system('clear')
    print(f"--- PIN {TARGET_PIN} DEDICATED TESTER ---")
    print(f"1. Forcing Pin {TARGET_PIN} to INPUT + PULL UP...")
    
    # Configure ONLY Pin 0
    subprocess.run(["gpio", "mode", TARGET_PIN, "in"], stdout=subprocess.DEVNULL)
    subprocess.run(["gpio", "mode", TARGET_PIN, "up"], stdout=subprocess.DEVNULL)
    
    print(f"2. Monitoring Pin {TARGET_PIN}...")
    print("   (If it stays silent, check your wiring)")
    print("--------------------------------")

def monitor():
    setup_pin()
    
    pulse_count = 0
    last_state = 1 # Default HIGH
    
    try:
        while True:
            current_state = read_pin(TARGET_PIN)
            
            # --- STATUS DISPLAY ---
            # If the pin is stuck LOW (0), tell the user!
            if current_state == 0 and last_state == 0:
                # We only print this once to avoid spamming
                pass 
            
            # --- PULSE DETECTION (Falling Edge) ---
            # Signal goes HIGH (1) -> LOW (0) -> HIGH (1)
            # We count when it hits 0
            if current_state == 0 and last_state == 1:
                pulse_count += 1
                print(f"   [+] Pulse Detected! (Total: {pulse_count})")
                
                # Wait for the signal to release (Debounce)
                while read_pin(TARGET_PIN) == 0:
                    time.sleep(0.01)
            
            last_state = current_state
            time.sleep(0.01) # Fast sampling

    except KeyboardInterrupt:
        print("\nTest Stopped.")

if __name__ == "__main__":
    monitor()