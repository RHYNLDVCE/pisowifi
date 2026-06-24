import wiringpi
import time
import config

# Import the centralized logger and alias it as 'print' so we don't have to 
# change the rest of the code below.
from core.logger import system_log as print

# ---------------------------

# Global state
current_slot_user = None

def setup():
    """
    Initialize GPIO modes based on config using native WiringPi.
    """
    # 1. Initialize WiringPi (Uses Physical Pin Numbers 1-40)
    wiringpi.wiringPiSetupPhys()
    
    # 2. Setup Coin Pin (Input + Pull Up)
    coin_pin = int(config.COIN_PIN_WPI)
    wiringpi.pinMode(coin_pin, 0)         # 0 = INPUT
    wiringpi.pullUpDnControl(coin_pin, 2) # 2 = PULL_UP
    
    # 3. Setup Relay Pins (Output + Default OFF)
    for pin in config.RELAY_PINS:
        p = int(pin)
        wiringpi.pinMode(p, 1)        # 1 = OUTPUT
        wiringpi.digitalWrite(p, 0)   # 0 = OFF
    
    print(f"Hardware Ready (Coin Pin: {config.COIN_PIN_WPI})")

def turn_slot_on():
    for pin in config.RELAY_PINS:
        wiringpi.digitalWrite(int(pin), 1)

def turn_slot_off():
    global current_slot_user
    current_slot_user = None
    for pin in config.RELAY_PINS:
        wiringpi.digitalWrite(int(pin), 0)

def read_pin():
    return wiringpi.digitalRead(int(config.COIN_PIN_WPI))

def wait_for_pulse(on_detected=None):
    """
    Smart Pulse Counter (Native WiringPi + Anti-Stuck Logic + Instant Logs)
    """
    # SAFETY: If pin is stuck LOW (0), wait for it to clear.
    if read_pin() == 0:
        print("   [Warning] Signal Stuck LOW. Waiting for clear...") 
        timeout = time.time()
        while read_pin() == 0:
            if time.time() - timeout > 2.0: # 2 second escape hatch
                print("   [Error] Signal permanently stuck LOW. Resetting...")
                return 0
            time.sleep(0.01)
        print("   [OK] Signal Cleared. Ready.")
            
    last_state = 1
    
    # PHASE 1: Wait for coin
    while True:
        state = read_pin()
        if state == 0 and last_state == 1:
            # FIRST PULSE DETECTED!
            if on_detected:
                try:
                    on_detected()
                except Exception as e:
                    print(f"Callback Error: {e}")
            break 
        last_state = state
        time.sleep(0.001) 

    # PHASE 2: Count pulses
    total_pulses = 1
    last_pulse_time = time.time()
    last_state = 0 
    
    # Wait for the pulse to finish (go back HIGH) with Timeout
    timeout = time.time()
    while read_pin() == 0:
        if time.time() - timeout > 0.5: break
        time.sleep(0.001)
    last_state = 1

    # Keep listening until silence
    while (time.time() - last_pulse_time) < 0.6:
        state = read_pin()
        if state == 0 and last_state == 1:
            total_pulses += 1
            last_pulse_time = time.time()
            
            timeout = time.time()
            while read_pin() == 0:
                if time.time() - timeout > 0.5: break
                time.sleep(0.001)
            state = 1 
                
        last_state = state
        time.sleep(0.001)

    return total_pulses