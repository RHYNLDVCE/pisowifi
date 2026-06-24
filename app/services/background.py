import time
import threading
import asyncio
import ctypes

from core import state
from hardware import controller

# Import our new Clean Services
from services.coin_service import CoinService
from services.timer_service import TimerService
from services.network_monitor import NetworkMonitorService

# Import the centralized logger
from core.logger import system_log


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
        except Exception as e: 
            system_log(f"WS Error: {e}")

# Instantiate Services via Dependency Injection
coin_svc = CoinService(send_ws_update)
timer_svc = TimerService(send_ws_update)
monitor_svc = NetworkMonitorService(send_ws_update)


def _coin_listener():
    set_linux_thread_name("Piso-Coin")
    system_log("Coin Listener STARTED (Polling Mode).")
    
    while True:
        try:
            # Array used as a pointer to hold the user at the exact moment the coin drops
            active_user = [None]
            
            def on_first_pulse():
                # Lock in the user MAC address on the very first pulse
                active_user[0] = controller.current_slot_user
                coin_svc.notify_counting(active_user[0])

            # Block here and wait for a coin to drop
            coin_value = controller.wait_for_pulse(on_detected=on_first_pulse)
            
            if coin_value > 0:
                mac = active_user[0]
                user_log = mac if mac else "Unknown_Device"
                
                # Log exactly how the UI expects it
                system_log(f"[COIN_INSERT] {coin_value} pulse(s) by Device: {user_log}")
                
                if mac:
                    # Credit the user (even if they accidentally clicked cancel mid-count!)
                    coin_svc.process_coin(coin_value, mac)
                    
                    # Tell UI we are done counting so it can show the Cancel button again
                    coin_svc.notify_done_counting(mac)
                
            # Short sleep before waiting for the next customer
            time.sleep(0.1)
        except Exception as e:
            try: system_log(f"CRITICAL ERROR in Coin loop: {e}")
            except: pass
            time.sleep(1)
            
            
def _time_manager():
    set_linux_thread_name("Piso-Timer")
    system_log("Time Manager & Scheduler Started...")
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
            try: system_log(f"CRITICAL ERROR in Timer loop: {e}")
            except: pass
            time.sleep(1)

def _connectivity_monitor():
    set_linux_thread_name("Piso-Monitor")
    system_log("Connectivity Monitor STARTED.")
    while True:
        try:
            time.sleep(5)
            monitor_svc.evaluate_all_connections()
        except Exception as e:
            try: system_log(f"CRITICAL ERROR in Monitor loop: {e}")
            except: pass
            time.sleep(1)

def start_background_tasks():
    threading.Thread(target=_coin_listener, name="Piso-Coin", daemon=True).start()
    threading.Thread(target=_time_manager, name="Piso-Timer", daemon=True).start()
    threading.Thread(target=_connectivity_monitor, name="Piso-Monitor", daemon=True).start()