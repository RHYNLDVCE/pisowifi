import subprocess
import time

# These are all the available wPi pin numbers on Orange Pi 3 LTS
# We removed 1 and 8 because we know those are your RELAYS (Lights)
POSSIBLE_PINS = ["0", "2", "3", "4", "5", "6", "9", "10", "13", "14", "15", "16"]

print("--- ULTIMATE PIN HUNTER ---")
print("1. I am setting all pins to INPUT mode...")
for pin in POSSIBLE_PINS:
    subprocess.run(["gpio", "mode", pin, "in"], stdout=subprocess.DEVNULL)
    subprocess.run(["gpio", "mode", pin, "up"], stdout=subprocess.DEVNULL)

print("2. Scanning... PLEASE DROP A COIN NOW (or tap the signal wire).")
print("---------------------------------------------------------------")

# Read the initial state of all pins to establish a baseline
baseline = {}
for pin in POSSIBLE_PINS:
    try:
        res = subprocess.check_output(["gpio", "read", pin])
        baseline[pin] = int(res.strip())
    except:
        baseline[pin] = 1

# Start the infinite scan loop
try:
    while True:
        for pin in POSSIBLE_PINS:
            try:
                # Read the current state
                res = subprocess.check_output(["gpio", "read", pin])
                state = int(res.strip())
                
                # If state changed from baseline (e.g. went from 1 to 0)
                if state != baseline[pin]:
                    print(f"\n!!! SIGNAL DETECTED ON wPi PIN: {pin} !!!")
                    print(f"State changed from {baseline[pin]} to {state}")
                    
                    # Reset baseline so it doesn't spam
                    baseline[pin] = state 
                    time.sleep(0.1) 
            except:
                pass
except KeyboardInterrupt:
    print("\nStopping scan.")
