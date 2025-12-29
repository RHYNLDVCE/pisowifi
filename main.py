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
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

# 2. Register Routes
app.include_router(client.router)
# FIX: Removed 'prefix="/admin"' to prevent double-naming (e.g. /admin/admin)
app.include_router(admin.router)

# --- LIFECYCLE EVENTS ---

@app.on_event("startup")
async def startup_event():
    print("⏳ Initializing System...")

    # 3. Database & State Startup
    database.init_db()
    state.users = database.load_users()
    print(f"✅ Loaded {len(state.users)} users from DB.")

    # 4. Network Startup
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