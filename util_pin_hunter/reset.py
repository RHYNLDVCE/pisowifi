import wiringpi

# Standard GPIO pins on Orange Pi 3 LTS
VALID_PINS = [3, 5, 7, 8, 10, 11, 12, 13, 15, 16, 18, 19, 21, 22, 23, 24, 26]

def reset_all():
    print("🧹 Cleaning up GPIO pins...")
    wiringpi.wiringPiSetupPhys()
    
    for pin in VALID_PINS:
        # Set to Output
        wiringpi.pinMode(pin, 1)
        # Turn OFF (Write 0)
        wiringpi.digitalWrite(pin, 0)
        
    print("✅ All pins are now OFF.")

if __name__ == "__main__":
    reset_all()