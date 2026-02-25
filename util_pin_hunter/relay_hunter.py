import wiringpi
import time

# --- CONFIGURATION ---
# Safe PHYSICAL pins on Orange Pi 3 LTS (Excluding power & ground)
VALID_PINS = [3, 5, 7, 8, 10, 11, 12, 13, 15, 16, 18, 19, 21, 22, 23, 24, 26]

def setup_wiringpi():
    print("⚙️  Initializing WiringPi (Physical Mode)...")
    wiringpi.wiringPiSetupPhys()

def hunt_relay():
    setup_wiringpi()
    
    print("\n" + "="*40)
    print("   🔌 RELAY HUNTER ACTIVE")
    print("   I will turn each pin ON for 2 seconds.")
    print("   Watch your Coin Slot lights or listen for a CLICK.")
    print("   (Press Ctrl+C to stop)")
    print("="*40 + "\n")

    try:
        for pin in VALID_PINS:
            print(f"👉 Testing Physical PIN: {pin} ...", end="", flush=True)
            
            # 1. Set Mode to OUTPUT
            wiringpi.pinMode(pin, 1) 
            
            # 2. Turn ON (High)
            wiringpi.digitalWrite(pin, 1)
            print(" [ ON ] ", end="", flush=True)
            
            # Wait 2 seconds so you can see/hear it
            time.sleep(2)
            
            # 3. Turn OFF (Low)
            wiringpi.digitalWrite(pin, 0)
            print(" [ OFF ]")
            
            # 4. Reset to Input (Safety)
            wiringpi.pinMode(pin, 0)
            
            time.sleep(0.5)

        print("\n✅ Scan Complete. Did you find it?")

    except KeyboardInterrupt:
        print("\n\n🛑 Hunter stopped. Turning off last pin...")
        # Safety cleanup
        for pin in VALID_PINS:
            wiringpi.pinMode(pin, 1)
            wiringpi.digitalWrite(pin, 0)
            wiringpi.pinMode(pin, 0)

if __name__ == "__main__":
    hunt_relay()