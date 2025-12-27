import threading
import time
import os
import shutil
from fastapi import FastAPI, Request, Form, UploadFile, File, Depends, HTTPException, status
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import OAuth2PasswordBearer

# --- IMPORTS ---
import config
from network import firewall
from hardware import controller  
from core import database 

app = FastAPI()

# --- SETUP STATIC FILES ---
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# --- CONFIGURATION STATE ---
SLOT_TIMEOUT = 30         # Default: 30 Seconds to insert coin
slot_expiry_timestamp = 0 # Unix timestamp when slot closes

# --- DATABASE STARTUP ---
database.init_db()
users = database.load_users()
print(f"Loaded {len(users)} users.")

# --- BACKGROUND TASKS ---
firewall.init_firewall()

# Wrapper for coin listener to handle Timer Reset
def coin_callback_wrapper():
    """
    Runs continuously. Checks hardware for coins.
    If coin detected -> Adds time AND resets the slot timer.
    """
    global slot_expiry_timestamp
    while True:
        # This function inside controller blocks until a coin is seen
        # or we can check a queue. Assuming controller.wait_for_coin() pattern:
        coin_value = controller.wait_for_pulse() 
        if coin_value > 0:
            print(f"💰 Coin Detected! Value: {coin_value}")
            
            # 1. Reset the Slot Timer (User gets more time to insert next coin)
            slot_expiry_timestamp = time.time() + SLOT_TIMEOUT
            
            # 2. Add Time to current user
            if controller.current_slot_user and controller.current_slot_user in users:
                # Add time (Value * Minutes per coin * 60 seconds)
                minutes = config.PULSE_VALUE * coin_value 
                users[controller.current_slot_user]["time"] += (minutes * 60)
                
                # Save immediately
                database.sync_user(controller.current_slot_user, users[controller.current_slot_user])
                database.add_sale(controller.current_slot_user, config.PULSE_VALUE * coin_value)

# Start the coin listener thread
threading.Thread(target=coin_callback_wrapper, daemon=True).start()

def time_manager():
    ticks = 0
    while True:
        time.sleep(1) 
        ticks += 1
        
        # 1. Manage User Time
        for mac, data in list(users.items()):
            # Only decrement time if user is CONNECTED (not paused)
            if data["status"] == "connected" and data["time"] > 0:
                data["time"] -= 1
                if data["time"] <= 0:
                    data["time"] = 0
                    data["status"] = "expired"
                    firewall.block_user(mac)
                    database.sync_user(mac, data)
            
            # (Optional) Auto-save connected users every 60s
            if ticks >= 60 and data["status"] == "connected":
                database.sync_user(mac, data)

        # 2. Manage Slot Timer Auto-Close
        global slot_expiry_timestamp
        if controller.current_slot_user:
            time_left = slot_expiry_timestamp - time.time()
            if time_left <= 0:
                print("⏳ Slot Timeout. Closing drawer.")
                controller.turn_slot_off()
                controller.current_slot_user = None

        # 3. Database Sync (every 60s reset)
        if ticks >= 60:
            ticks = 0

threading.Thread(target=time_manager, daemon=True).start()

# --- UTILS ---
def get_mac(ip):
    try:
        with open('/proc/net/arp') as f:
            for line in f.readlines():
                parts = line.split()
                if len(parts) > 3 and parts[0] == ip: return parts[3]
    except: pass
    return "00:00:00:00:00:00"

def get_banner_image():
    # Priority 1: Custom Upload
    if os.path.exists("static/banner_custom.jpg"): 
        return "/static/banner_custom.jpg"
    
    # Priority 2: Default Image (The Fix)
    if os.path.exists("static/banner_default.jpg"):
        return "/static/banner_default.jpg"
        
    # Priority 3: Fallback (CSS Gradient)
    return ""

def is_admin(request: Request):
    token = request.cookies.get("admin_token")
    if token != "secret_logged_in_token":
        raise HTTPException(status_code=302, headers={"Location": "/login"})
    return True

# --- CAPTIVE PORTAL TRIGGERS ---
@app.get("/generate_204")
@app.get("/gen_204")
@app.get("/ncsi.txt")
@app.get("/hotspot-detect.html")
@app.get("/canonical.html")
async def captive_portal_trigger():
    return RedirectResponse("/")

# --- ROUTES ---
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    client_ip = request.client.host
    client_mac = get_mac(client_ip)
    
    if client_mac and client_mac not in users:
        users[client_mac] = {"time": 0, "status": "new"}
    
    return templates.TemplateResponse("index.html", {
        "request": request, 
        "mac": client_mac,
        "ip": client_ip,
        "banner_url": get_banner_image()
    })

@app.get("/status")
async def check_status(mac: str):
    global slot_expiry_timestamp
    user = users.get(mac, {"time": 0, "status": "new"})
    is_busy = (controller.current_slot_user is not None and controller.current_slot_user != mac)
    
    # Calculate slot countdown
    slot_seconds_left = 0
    if controller.current_slot_user == mac:
        slot_seconds_left = int(max(0, slot_expiry_timestamp - time.time()))

    return {
        "time_remaining": user["time"], 
        "status": user["status"], 
        "is_busy": is_busy,
        "slot_seconds": slot_seconds_left,   # Send current countdown
        "slot_max_seconds": SLOT_TIMEOUT     # Send max time for progress bar
    }

@app.get("/enable_slot")
async def enable_slot(mac: str):
    global slot_expiry_timestamp
    if controller.current_slot_user is None:
        controller.current_slot_user = mac
        controller.turn_slot_on()
        # Set initial timer
        slot_expiry_timestamp = time.time() + SLOT_TIMEOUT
        return {"result": "success"}
    elif controller.current_slot_user == mac:
        return {"result": "success"}
    return {"result": "busy"}

@app.post("/connect")
async def start_internet(mac: str):
    if users.get(mac) and users[mac]["time"] > 0:
        users[mac]["status"] = "connected"
        firewall.allow_user(mac)
        controller.turn_slot_off()
        controller.current_slot_user = None # Free the slot
        database.sync_user(mac, users[mac])
        return {"result": "success"}
    return {"result": "fail"}

# --- NEW PAUSE ROUTE ---
@app.post("/pause")
async def pause_internet(mac: str):
    if users.get(mac) and users[mac]["status"] == "connected":
        users[mac]["status"] = "paused"
        firewall.block_user(mac) # Cut connection
        database.sync_user(mac, users[mac])
        return {"result": "success"}
    return {"result": "fail"}

# --- ADMIN ROUTES ---
@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/auth")
async def login_action(username: str = Form(...), password: str = Form(...)):
    if database.verify_admin(username, password):
        response = RedirectResponse(url="/admin", status_code=303)
        response.set_cookie(key="admin_token", value="secret_logged_in_token")
        return response
    return RedirectResponse(url="/login?error=Invalid Credentials", status_code=303)

@app.get("/admin", response_class=HTMLResponse)
async def admin_panel(request: Request, authorized: bool = Depends(is_admin)):
    total = database.get_total_sales()
    return templates.TemplateResponse("admin.html", {
        "request": request, 
        "users": users, 
        "total_sales": total,
        "slot_timeout": SLOT_TIMEOUT # Pass current setting to HTML
    })

@app.post("/admin/upload_banner")
async def upload_banner(file: UploadFile = File(...), authorized: bool = Depends(is_admin)):
    # Save file as 'banner_custom.jpg' to overwrite the old one
    file_location = f"static/banner_custom.jpg"
    with open(file_location, "wb+") as file_object:
        shutil.copyfileobj(file.file, file_object)
    return RedirectResponse(url="/admin", status_code=303)

@app.post("/admin/update_settings")
async def update_settings(timeout: int = Form(...), authorized: bool = Depends(is_admin)):
    global SLOT_TIMEOUT
    SLOT_TIMEOUT = timeout
    return RedirectResponse(url="/admin", status_code=303)