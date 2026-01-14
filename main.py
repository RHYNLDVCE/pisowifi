# main.py
import os
import asyncio
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from core import database, state, utils
from network import firewall
from services import background
from routers import client, admin
from hardware import controller 

app = FastAPI()

# 1. Setup Resources
# Ensure base static folder exists
os.makedirs("static", exist_ok=True)

# Ensure Banner Subdirectories exist
os.makedirs("static/banners/set", exist_ok=True)      # For Admin Uploads
os.makedirs("static/banners/default", exist_ok=True)  # For Default Fallbacks

# Ensure Sound folder exists
os.makedirs("static/sounds", exist_ok=True)

# Mount the static directory
app.mount("/static", StaticFiles(directory="static"), name="static")

# 2. Register Routes
app.include_router(admin.router)
app.include_router(client.router)

# --- LIFECYCLE EVENTS ---

@app.on_event("startup")
async def startup_event():
    print("⏳ Initializing System...")

    # 3. Database & State Startup
    database.init_db()
    state.users = database.load_users()
    
    # --- NEW FEATURE: Auto-Pause on Power Outage/Reboot ---
    # This loop checks if anyone was "connected" when the power died.
    # We force them to "paused" so their time stops and the Portal pops up.
    print("🔌 Power Cycle Detected: Checking for active sessions...")
    count_paused = 0
    for mac, data in state.users.items():
        if data["status"] == "connected":
            data["status"] = "paused"
            database.sync_user(mac, data)  # Save the 'paused' state to DB immediately
            count_paused += 1
            print(f"   -> Auto-Paused User: {mac}")
    
    if count_paused > 0:
        print(f"✅ Auto-Paused {count_paused} users. They must click 'Resume' to reconnect.")
    else:
        print("✅ No active users found to pause.")
    # ------------------------------------------------------

    print(f"✅ Loaded {len(state.users)} users from DB.")

    # 4. Network Startup
    # Since everyone is now "paused" or "expired", the firewall starts clean (Blocking everyone).
    firewall.init_firewall()

    # 5. Capture the Main Loop (For WebSockets)
    state.loop = asyncio.get_running_loop()

    # 6. Initialize Hardware (GPIO)
    controller.setup()

    # 7. Start Background Services (Coins & Timer)
    background.start_background_tasks()
    
    print("🚀 PisoWifi System Started Successfully!")

@app.on_event("shutdown")
def shutdown_event():
    print("🛑 System Shutting Down...")
    try:
        controller.turn_slot_off()
    except Exception as e:
        print(f"Cleanup Error: {e}")