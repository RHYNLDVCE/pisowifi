# main.py
import os
import asyncio
import subprocess
import uvicorn  # <--- Added for manual execution
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from core import database, state, utils
from network import firewall
from services import background
from routers import client, admin
from hardware import controller 

app = FastAPI()

# 1. Setup Resources
os.makedirs("static", exist_ok=True)
os.makedirs("static/banners/set", exist_ok=True)
os.makedirs("static/banners/default", exist_ok=True)
os.makedirs("static/sounds", exist_ok=True)

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
    
    # --- AUTO-PAUSE LOGIC ---
    print("🔌 Power Cycle Detected: Checking for active sessions...")
    count_paused = 0
    for mac, data in state.users.items():
        if data["status"] == "connected":
            # Force status to paused
            data["status"] = "paused"
            database.sync_user(mac, data)
            count_paused += 1
            print(f"   -> Auto-Paused User: {mac}")
    
    if count_paused > 0:
        print(f"✅ Auto-Paused {count_paused} users.")
    else:
        print("✅ No active users found to pause.")

    # 4. Network Startup
    # Initialize the firewall (flushes IPSet and IPTables)
    firewall.init_firewall()

    # --- FIX: FLUSH CONNECTIONS (Anti-Ghosting) ---
    # This kills all "ghost" connections (videos, games) that were active before reboot.
    print("🧹 Flushing connection tracking entries...")
    try:
        subprocess.run(["conntrack", "-F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        print("⚠️ Warning: Could not flush conntrack. Install via 'sudo apt install conntrack'")

    # 5. Capture the Main Loop
    state.loop = asyncio.get_running_loop()

    # 6. Initialize Hardware
    controller.setup()

    # 7. Start Background Services
    background.start_background_tasks()
    
    print("🚀 PisoWifi System Started Successfully! (All connections dropped)")

@app.on_event("shutdown")
def shutdown_event():
    print("🛑 System Shutting Down...")
    
    # 1. Turn off Coin Slot
    try:
        controller.turn_slot_off()
    except Exception as e:
        print(f"Hardware Cleanup Error: {e}")

    # 2. TRIGGER FAIL-SAFE (Redundancy)
    # Ensure internet is cut even if systemd script is delayed
    try:
        subprocess.run(["/home/reyes/pisowifi/fail_safe.sh"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("🔒 Fail-Safe Triggered internally.")
    except:
        pass

# --- STANDARD ENTRY POINT ---
# This allows you to run 'python3 main.py' manually if needed.
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=80, reload=False)