# main.py
import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from core import database, state
from network import firewall
from services import background
from routers import client, admin

app = FastAPI()

# 1. Setup Resources
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

# 2. Database & State Startup
database.init_db()
state.users = database.load_users() # Load users from DB into shared state
print(f"Loaded {len(state.users)} users.")

# 3. Network Startup
firewall.init_firewall()

# 4. Start Background Services (Coins & Timer)
background.start_background_tasks()

# 5. Register Routes
app.include_router(client.router)
app.include_router(admin.router)