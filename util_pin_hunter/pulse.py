#!/usr/bin/env python3
import time
import sys
import logging
import os

# Ensure the script can import config.py whether run from root or app folder
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Configure professional logging
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

try:
    import wiringpi
except ImportError:
    logger.error("wiringpi module is not installed or accessible. Run with sudo.")
    sys.exit(1)

# Safely extract pins from config
try:
    import config
    COIN_PIN = int(config.COIN_PIN_WPI)
    RELAY_PIN = int(config.RELAY_PINS[0])
except Exception as e:
    logger.warning(f"Failed to load config.py. Using default pins 3 and 5. Error: {e}")
    COIN_PIN = 3
    RELAY_PIN = 5

def setup_hardware():
    """Initialize GPIO pins and POWER ON the coin slot relay."""
    wiringpi.wiringPiSetupPhys()
    
    # 1. Setup Coin Data Pin (Listen for pulses)
    wiringpi.pinMode(COIN_PIN, 0)         # Set as INPUT
    wiringpi.pullUpDnControl(COIN_PIN, 2) # Enable internal PULL_UP resistor

    # 2. Setup and Enable Relay Pin (Give power to the coin slot)
    logger.info(f"Powering ON Relay on Physical Pin {RELAY_PIN}...")
    wiringpi.pinMode(RELAY_PIN, 1)       # Set as OUTPUT
    wiringpi.digitalWrite(RELAY_PIN, 1)  # Set HIGH (1) to turn ON (Active HIGH)

def cleanup_hardware():
    """Ensure no lingering state is left on the hardware and cut power."""
    try:
        # Turn off Relay (Cut power to coin slot)
        wiringpi.digitalWrite(RELAY_PIN, 0) # Set LOW (0) to turn OFF (Active HIGH)
        wiringpi.pinMode(RELAY_PIN, 0)      # Set to INPUT for safety
        
        # Disable pull-up resistor on the data pin
        wiringpi.pullUpDnControl(COIN_PIN, 0)
        wiringpi.pinMode(COIN_PIN, 0)
    except Exception as e:
        logger.error(f"Failed to clean up GPIO state: {e}")

def run_diagnostics():
    """Run the continuous pulse monitoring loop."""
    setup_hardware()
    logger.info(f"Coin Slot Data Pin initialized on Physical Pin {COIN_PIN}.")
    logger.info("Awaiting pulse signals. Press Ctrl+C to terminate.")
    print("-" * 75)

    last_state = 1
    pulse_start_time = 0
    total_pulses = 0

    try:
        while True:
            state = wiringpi.digitalRead(COIN_PIN)
            
            # Detect Falling Edge (HIGH to LOW) -> Pulse starts
            if state == 0 and last_state == 1:
                pulse_start_time = time.time()
                sys.stdout.write("[SIGNAL DROP] Pin LOW (0) ---> ")
                sys.stdout.flush()
            
            # Detect Rising Edge (LOW to HIGH) -> Pulse ends
            elif state == 1 and last_state == 0:
                duration_ms = int((time.time() - pulse_start_time) * 1000)
                total_pulses += 1
                print(f"[SIGNAL RESTORED] Pin HIGH (1) | Width: {duration_ms}ms | Total Pulses: {total_pulses}")
            
            last_state = state
            time.sleep(0.001)  # 1ms polling resolution for high accuracy

    except KeyboardInterrupt:
        print()
        logger.info("Keyboard interrupt received. Halting diagnostics.")
    finally:
        logger.info("Initiating hardware state cleanup...")
        cleanup_hardware()
        logger.info("Cleanup complete. Hardware is completely OFF and safe.")

if __name__ == "__main__":
    run_diagnostics()