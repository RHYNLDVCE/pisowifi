import subprocess
import time
import config

# Global state to track who is using the slot
current_slot_user = None

def setup():
    """
    Initialize GPIO modes based on config.
    """
    # 1. Setup Coin Pin (Input + Pull Up)
    subprocess.run(["gpio", "mode", config.COIN_PIN_WPI, "in"])
    subprocess.run(["gpio", "mode", config.COIN_PIN_WPI, "up"])
    
    # 2. Setup Relay Pins (Output + Default OFF)
    for pin in config.RELAY_PINS:
        subprocess.run(["gpio", "mode", pin, "out"])
        subprocess.run(["gpio", "write", pin, "0"]) 
    
    print(f"✅ Hardware Ready (Coin Pin: {config.COIN_PIN_WPI})")

def turn_slot_on():
    for pin in config.RELAY_PINS:
        subprocess.run(["gpio", "write", pin, "1"])

def turn_slot_off():
    global current_slot_user
    current_slot_user = None
    for pin in config.RELAY_PINS:
        subprocess.run(["gpio", "write", pin, "0"])

def read_pin():
    try:
        res = subprocess.check_output(["gpio", "read", config.COIN_PIN_WPI])
        return int(res.strip())
    except:
        return 1

def wait_for_pulse(on_detected=None):
    """
    Smart Pulse Counter (Real-Time Feedback Version)
    Args:
        on_detected (function): Optional callback to run IMMEDIATELY when first pulse is found.
    """
    last_state = 1
    
    # --- PHASE 1: Wait for the FIRST pulse ---
    while True:
        state = read_pin()
        if state == 0 and last_state == 1:
            # 🎉 FIRST PULSE DETECTED!
            # Notify the system immediately so UI can show "Counting..."
            if on_detected:
                try:
                    on_detected()
                except Exception as e:
                    print(f"Callback Error: {e}")
            break 
        last_state = state
        time.sleep(0.01)

    # --- PHASE 2: Collect the "Pulse Train" ---
    total_pulses = 1
    last_pulse_time = time.time()
    
    # We are currently LOW (0). 
    last_state = 0 
    
    print("   -> Pulse 1 detected... Listening for train...")

    # Keep listening until silence for 0.6 seconds
    while (time.time() - last_pulse_time) < 0.6:
        state = read_pin()
        
        # Detect Falling Edge (1 -> 0)
        if state == 0 and last_state == 1:
            total_pulses += 1
            last_pulse_time = time.time()
            print(f"   -> Pulse {total_pulses}")
            
            # Debounce: Wait for signal to go High again
            while read_pin() == 0:
                time.sleep(0.01)
                
        last_state = state
        time.sleep(0.01)
    
    print(f"✅ Batch Complete: {total_pulses} Pulses collected.")
    return total_pulses