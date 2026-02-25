import wiringpi
import time
import os

# --- CONFIGURATION ---
# These are the safe PHYSICAL pins on Orange Pi 3 LTS (Pins 1-26 header)
# We exclude 5V (2,4), 3.3V (1,17), and GND (6,9,14,20,25)
# Based on your 'gpio readall' output:
VALID_PINS = [3, 5, 7, 8, 10, 11, 12, 13, 15, 16, 18, 19, 21, 22, 23, 24, 26]

def setup_all_pins():
    """Configure all valid pins as Input with Pull-Up Resistor"""
    print("⚙️  Initializing WiringPi (Physical Mode)...")
    wiringpi.wiringPiSetupPhys()
    
    print("🔌 Configuring pins as INPUT + PULL_UP...")
    for pin in VALID_PINS:
        try:
            # Set to INPUT
            wiringpi.pinMode(pin, 0) 
            # Enable PULL UP (Normal state = 1, Active state = 0)
            wiringpi.pullUpDnControl(pin, 2) 
        except Exception as e:
            print(f"   ⚠️ Could not setup Pin {pin}: {e}")
    print("✅ Ready to Hunt! (Pins are held HIGH, waiting for LOW pulse)")

def hunt():
    setup_all_pins()
    
    print("\n" + "="*40)
    print("   🎯 PIN HUNTER ACTIVE")
    print("   Please insert a coin now...")
    print("   (Press Ctrl+C to stop)")
    print("="*40 + "\n")

    # We track the last state to only print CHANGE (falling edge)
    # Initialize all states to 1 (HIGH)
    last_states = {pin: 1 for pin in VALID_PINS}

    try:
        while True:
            # Rapidly scan all pins
            for pin in VALID_PINS:
                current_state = wiringpi.digitalRead(pin)
                
                # Check for Falling Edge (1 -> 0)
                if current_state == 0 and last_states[pin] == 1:
                    print(f"💰 COIN DETECTED ON PHYSICAL PIN: {pin}  <--- FOUND IT!")
                    # Optional: Beep or flash if you have a buzzer attached
                
                # Check for Rising Edge (0 -> 1) - Pulse finishing
                elif current_state == 1 and last_states[pin] == 0:
                    # Just debug info, optional
                    pass

                last_states[pin] = current_state
        
            time.sleep(0.001)

    except KeyboardInterrupt:
        print("\n🛑 Hunter stopped.")

if __name__ == "__main__":
    hunt()