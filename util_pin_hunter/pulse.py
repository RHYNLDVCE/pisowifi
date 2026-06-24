#!/usr/bin/env python3
import time
import sys
import logging

# Configure professional logging
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

try:
    import wiringpi
except ImportError:
    logger.error("wiringpi module is not installed or accessible.")
    sys.exit(1)

# Attempt to load the physical pin from the centralized configuration
try:
    import config
    PIN = int(config.COIN_PIN_WPI)
except Exception:
    PIN = 11  # Fallback physical pin

def setup_hardware():
    """Initialize GPIO pin for reading."""
    wiringpi.wiringPiSetupPhys()
    wiringpi.pinMode(PIN, 0)         # Set as INPUT
    wiringpi.pullUpDnControl(PIN, 2) # Enable internal PULL_UP resistor

def cleanup_hardware():
    """Ensure no lingering state is left on the hardware."""
    try:
        # Disable pull-up resistor and ensure input mode to prevent leakage/shorts
        wiringpi.pullUpDnControl(PIN, 0)
        wiringpi.pinMode(PIN, 0)
    except Exception as e:
        logger.error(f"Failed to clean up GPIO state: {e}")

def run_diagnostics():
    """Run the continuous pulse monitoring loop."""
    setup_hardware()
    logger.info(f"Coin Slot Pulse Visualizer initialized on Physical Pin {PIN}.")
    logger.info("Awaiting pulse signals. Press Ctrl+C to terminate.")
    print("-" * 75)

    last_state = 1
    pulse_start_time = 0
    total_pulses = 0

    try:
        while True:
            state = wiringpi.digitalRead(PIN)
            
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
        logger.info("Cleanup complete. Exiting gracefully.")

if __name__ == "__main__":
    run_diagnostics()