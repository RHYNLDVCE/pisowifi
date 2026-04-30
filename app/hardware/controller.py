import wiringpi
import time
import config
import datetime
import builtins

# --- SAFE PRINT OVERRIDE ---
def safe_print(*args, **kwargs):
    """A bulletproof print function that survives logrotate broken pipes and logs to file."""
    try:
        builtins.print(*args, **kwargs)
        msg = " ".join(map(str, args))
        with open("system.log", "a") as f:
            dt = datetime.datetime.now().strftime("%Y-%m-%d %I:%M:%S %p")
            f.write(f"[{dt}] {msg}\n")
    except OSError:
        pass

print = safe_print

# --- GLOBAL STATE ---
current_slot_user = None

# Interrupt State
_pulse_count = 0
_last_pulse_time = 0
_is_counting = False
_on_coin_detected = None

def _coin_interrupt_handler():
    """Fired automatically by the OS when the pin drops to 0 (coin inserted)."""
    global _pulse_count, _last_pulse_time, _is_counting
    
    now = time.time()
    # Debounce: Ignore electrical noise faster than 30ms
    if now - _last_pulse_time < 0.03:
        return
        
    _last_pulse_time = now
    _pulse_count += 1
    
    if not _is_counting:
        _is_counting = True
        if _on_coin_detected:
            try:
                _on_coin_detected()
            except Exception as e:
                print(f"Callback Error: {e}")

def setup(on_detected_cb=None):
    """
    Initialize GPIO modes based on config using native WiringPi.
    """
    global _on_coin_detected
    _on_coin_detected = on_detected_cb

    wiringpi.wiringPiSetupPhys()
    
    coin_pin = int(config.COIN_PIN_WPI)
    wiringpi.pinMode(coin_pin, 0)
    wiringpi.pullUpDnControl(coin_pin, 2)
    
    # Enable Hardware Interrupts
    wiringpi.wiringPiISR(coin_pin, wiringpi.INT_EDGE_FALLING, _coin_interrupt_handler)
    
    for pin in config.RELAY_PINS:
        p = int(pin)
        wiringpi.pinMode(p, 1)
        wiringpi.digitalWrite(p, 0)
        
    print(f"Hardware Ready, Interrupts Enabled (Coin Pin: {config.COIN_PIN_WPI})")

def turn_slot_on():
    for pin in config.RELAY_PINS:
        wiringpi.digitalWrite(int(pin), 1)

def turn_slot_off():
    global current_slot_user
    current_slot_user = None
    for pin in config.RELAY_PINS:
        wiringpi.digitalWrite(int(pin), 0)

def check_pulse_timeout():
    """
    Called by the background thread to see if coins have finished dropping.
    Returns the total count if finished, otherwise 0.
    """
    global _pulse_count, _last_pulse_time, _is_counting
    
    # Silence for >0.6s means the user stopped dropping coins
    if _is_counting and (time.time() - _last_pulse_time) > 0.6:
        final_count = _pulse_count
        _pulse_count = 0
        _is_counting = False
        return final_count
        
    return 0