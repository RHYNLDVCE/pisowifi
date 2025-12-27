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
        # Based on your previous code, '0' was OFF
        subprocess.run(["gpio", "write", pin, "0"]) 
    
    print(f"✅ Hardware Ready (Coin: {config.COIN_PIN_WPI}, Relays: {config.RELAY_PINS})")

def turn_slot_on():
    """
    Energize the relay (Turn Light/Slot ON).
    """
    for pin in config.RELAY_PINS:
        # Based on your code, '1' turns it ON
        subprocess.run(["gpio", "write", pin, "1"])

def turn_slot_off():
    """
    De-energize the relay (Turn Light/Slot OFF).
    """
    global current_slot_user
    current_slot_user = None # Clear the active user
    for pin in config.RELAY_PINS:
        subprocess.run(["gpio", "write", pin, "0"])

def wait_for_pulse():
    """
    Blocking function: sits here and waits until a coin drops.
    Returns 1 when a coin is detected.
    Used by the main.py loop.
    """
    last_state = 1
    
    while True:
        try:
            # Read the pin using the 'gpio' command
            res = subprocess.check_output(["gpio", "read", config.COIN_PIN_WPI])
            state = int(res.strip())
            
            # Detect Falling Edge (High -> Low transition)
            # This happens when the coin mechanism sends a pulse
            if state == 0 and last_state == 1:
                # Small debounce delay to ensure it's a real coin
                time.sleep(0.02) 
                
                # Wait for signal to reset to 1 (prevent double counting)
                while int(subprocess.check_output(["gpio", "read", config.COIN_PIN_WPI]).strip()) == 0:
                    time.sleep(0.01)
                
                return 1 # Return success to main.py
            
            last_state = state
            time.sleep(0.05) # Save CPU usage
            
        except Exception as e:
            print(f"GPIO Error: {e}")
            time.sleep(1)

# Run setup once when imported
setup()