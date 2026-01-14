import subprocess
import time
import os

# --- CONFIGURATION ---
# Pins to scan (excluding your relay/light pins 1 and 8)
POSSIBLE_PINS = ["0", "2", "3", "4", "5", "6", "9", "10", "13", "14", "15", "16"]

def read_pin(pin):
    try:
        # Run 'gpio read <pin>'
        res = subprocess.check_output(["gpio", "read", pin])
        return int(res.strip())
    except:
        return 1

def setup_pins():
    # clear the screen for a fresh start
    os.system('clear') 
    print("--- SLOW & STEADY PIN HUNTER ---")
    print("1. Setting pins to INPUT + PULL UP...")
    for pin in POSSIBLE_PINS:
        subprocess.run(["gpio", "mode", pin, "in"], stdout=subprocess.DEVNULL)
        subprocess.run(["gpio", "mode", pin, "up"], stdout=subprocess.DEVNULL)
    print("2. Ready! Waiting for a coin...")
    print("--------------------------------")

def analyze_pulses(active_pin):
    print(f"\n\n!!! SIGNAL DETECTED ON PIN {active_pin} !!!")
    print(">> Counting pulses... (Please wait)")
    
    pulse_count = 0
    last_state = 0 # Signals usually start Low
    
    # We wait for silence (no signals) for 1.0 second to know the coin is done
    last_pulse_time = time.time()
    
    while (time.time() - last_pulse_time) < 1.0:
        current_state = read_pin(active_pin)
        
        # Count when signal goes from LOW (0) back to HIGH (1)
        if current_state == 1 and last_state == 0:
            pulse_count += 1
            last_pulse_time = time.time() # Reset silence timer
            print(f"   -> Pulse {pulse_count}")
            
        last_state = current_state
        # Fast read to catch the coin, but we won't print anything extra
        time.sleep(0.01) 

    # --- RESULT SECTION (PAUSES HERE) ---
    print("\n" + "="*40)
    print(f" FINAL RESULT: Pin {active_pin} sent {pulse_count} pulses")
    print("="*40)
    
    print(">> Pausing for 5 seconds so you can read this...")
    time.sleep(5)
    
    print("\n--------------------------------")
    print(">> Ready for the next coin...")
    print("--------------------------------")

# --- MAIN LOOP ---
if __name__ == "__main__":
    setup_pins()
    
    try:
        while True:
            for pin in POSSIBLE_PINS:
                # Check if pin is LOW (0) which means a coin signal is happening
                if read_pin(pin) == 0:
                    analyze_pulses(pin)
                    
                    # Double check to clear any stuck signals
                    while read_pin(pin) == 0:
                        time.sleep(0.1)
                        
                    break # Restart scan loop
            
            # Checks every 0.1s to save CPU
            time.sleep(0.1)

    except KeyboardInterrupt:
        print("\nStopping scan.")