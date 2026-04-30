import time
import threading
import asyncio
import ctypes
import builtins

from core import state
from hardware import controller

# Import our new Clean Services
from services.coin_service import CoinService
from services.timer_service import TimerService
from services.network_monitor import NetworkMonitorService

def safe_print(*args, **kwargs):
    """A bulletproof print function that survives logrotate broken pipes."""
    try: builtins.print(*args, **kwargs)
    except OSError: pass 

print = safe_print

def set_linux_thread_name(name):
    try:
        libc = ctypes.cdll.LoadLibrary('libc.so.6')
        libc.prctl(15, name[:15].encode('utf-8'), 0, 0, 0)
    except Exception: pass

def send_ws_update(mac, data):
    """Helper to send WebSocket messages safely from background threads."""
    if hasattr(state, "loop") and state.loop and hasattr(state, "manager"):
        try:
            asyncio.run_coroutine_threadsafe(
                state.manager.send_personal_message(data, mac), 
                state.loop
            )
        except Exception as e: print(f"WS Error: {e}")

# Instantiate Services via Dependency Injection
coin_svc = CoinService(send_ws_update)
timer_svc = TimerService(send_ws_update)
monitor_svc = NetworkMonitorService(send_ws_update)

def _coin_listener():
    set_linux_thread_name("Piso-Coin")
    print("Coin Listener STARTED (Interrupt Driven).")
    
    # Pass the UI callback directly to the hardware setup
    controller.setup(on_detected_cb=lambda: coin_svc.notify_counting(controller.current_slot_user))
    
    while True:
        try:
            # Check if the interrupt handler finished counting pulses
            coin_value = controller.check_pulse_timeout()
            
            if coin_value > 0:
                print(f"\n[DEBUG] COIN DETECTED! Pulses: {coin_value}")
                coin_svc.process_coin(coin_value, controller.current_slot_user)
                
            # Sleep gently. 0.1s uses ~0% CPU.
            time.sleep(0.1)
        except Exception as e:
            try: print(f"CRITICAL ERROR in Coin loop: {e}")
            except: pass
            time.sleep(1)

def _time_manager():
    set_linux_thread_name("Piso-Timer")
    print("Time Manager & Scheduler Started...")
    ticks = 0
    while True:
        try:
            time.sleep(1)
            ticks += 1
            
            if ticks % 5 == 0: timer_svc.check_reboot_schedule()
            
            timer_svc.tick_users(ticks)
            timer_svc.check_slot_expiry()

            if ticks >= 30: ticks = 0
        except Exception as e:
            try: print(f"CRITICAL ERROR in Timer loop: {e}")
            except: pass
            time.sleep(1)

def _connectivity_monitor():
    set_linux_thread_name("Piso-Monitor")
    print("Connectivity Monitor STARTED.")
    while True:
        try:
            time.sleep(5)
            monitor_svc.evaluate_all_connections()
        except Exception as e:
            try: print(f"CRITICAL ERROR in Monitor loop: {e}")
            except: pass
            time.sleep(1)

def start_background_tasks():
    threading.Thread(target=_coin_listener, name="Piso-Coin", daemon=True).start()
    threading.Thread(target=_time_manager, name="Piso-Timer", daemon=True).start()
    threading.Thread(target=_connectivity_monitor, name="Piso-Monitor", daemon=True).start()