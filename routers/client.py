# routers/client.py
import os
import time
from fastapi import APIRouter, Request, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse

import config
from core import database, state, utils
from core.templates import templates
from hardware import controller
from network import firewall

router = APIRouter()

# --- HELPER: GREEDY TIME CALCULATION ---
def calculate_time_from_balance(balance):
    """
    Converts balance to minutes using the greedy approach based on configured rates.
    """
    rates_str = state.config.get("coin_rates", "1:10,5:60,10:180,20:300")
    rates = []
    try:
        for part in rates_str.split(','):
            amt, mins = part.strip().split(':')
            rates.append((int(amt), int(mins)))
    except:
        rates = [(1, 5)] 
    
    rates.sort(key=lambda x: x[0], reverse=True)
    
    total_minutes = 0
    remaining_balance = int(balance)
    
    for amt, mins in rates:
        if amt <= 0: continue
        count = remaining_balance // amt
        if count > 0:
            total_minutes += count * mins
            remaining_balance %= amt
            
    if remaining_balance > 0:
        total_minutes += remaining_balance * 5 

    return total_minutes

# --- WEBSOCKET ROUTE ---
@router.websocket("/ws/{mac}")
async def websocket_endpoint(websocket: WebSocket, mac: str):
    await state.manager.connect(mac, websocket)
    if mac in state.users and websocket.client.host:
        state.users[mac]["ip"] = websocket.client.host
        state.users[mac]["last_active"] = time.time()
    try:
        while True:
            await websocket.receive_text()
            if mac in state.users:
                state.users[mac]["last_active"] = time.time()
    except WebSocketDisconnect:
        state.manager.disconnect(mac, websocket)
        
# --- CAPTIVE PORTAL ---
@router.get("/generate_204")
@router.get("/ncsi.txt")
@router.get("/connecttest.txt")
@router.get("/redirect")
async def captive_portal_trigger():
    return RedirectResponse("/")

@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    client_ip = request.client.host
    client_mac = utils.get_mac(client_ip)
    
    if client_mac:
        if client_mac not in state.users:
            # Init new user
            state.users[client_mac] = {"time": 0, "status": "new", "balance": 0, "free_claimed": 0}
        
        state.users[client_mac]["ip"] = client_ip
        state.users[client_mac]["last_active"] = time.time()
    
    # Check for banners (WITH ORDERING LOGIC)
    # Updated to look in 'static/banners/set'
    banner_dir = "static/banners/set"
    banners = []
    
    if os.path.exists(banner_dir):
        all_files = [f for f in os.listdir(banner_dir) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif'))]
        saved_order = state.config.get("banner_order", [])
        ordered_files = []
        
        # 1. Add saved ones first
        for f in saved_order:
            if f in all_files:
                ordered_files.append(f)
        # 2. Add remaining
        for f in all_files:
            if f not in ordered_files:
                ordered_files.append(f)
                
        if ordered_files:
            # FIXED PATH: /static/banners/set/{filename}
            banners = [f"/static/banners/set/{f}" for f in ordered_files]
    
    # Fallback only if totally empty
    if not banners:
        # Check if we have a default banner in the new default location
        default_dir = "static/banners/default"
        if os.path.exists(default_dir):
             defaults = [f for f in os.listdir(default_dir) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif'))]
             if defaults:
                 # Use the first valid image found in the default folder
                 banners = [f"/static/banners/default/{defaults[0]}"]
             else:
                 # Last resort fallback if folder exists but is empty
                 banners = ["/static/banners/default/banner_default.jpg"]
        else:
             # Fallback if folder doesn't exist at all
             banners = ["/static/banner_default.jpg"]

    # Check Free Time Status
    user_data = state.users.get(client_mac, {})
    is_claimed = (user_data.get("free_claimed", 0) == 1)

    # SOUND SETTINGS
    s_insert = state.config.get("sound_insert", "insert_coin_sound.mp3")
    s_coin = state.config.get("sound_coin", "coin-recieved.mp3")

    return templates.TemplateResponse("index.html", {
        "request": request, 
        "mac": client_mac,
        "ip": client_ip,
        "banners": banners,
        "banner_text": state.config.get("banner_text", ""),
        "banner_link": state.config.get("banner_link", ""),
        "coin_rates": state.config.get("coin_rates", "1:10,5:60,10:180,20:300"),
        # PASS FREE TIME FLAGS
        "free_time_enabled": state.config.get("free_time_enabled", False),
        "free_claimed": is_claimed,
        "free_duration": state.config.get("free_time_duration", 5),
        # SOUND URLs
        "sound_insert_url": f"/static/sounds/{s_insert}",
        "sound_coin_url": f"/static/sounds/{s_coin}"
    })

@router.get("/status")
async def check_status(mac: str, request: Request):
    user = state.users.get(mac, {"time": 0, "status": "new", "balance": 0})
    if "balance" not in user: user["balance"] = 0
    if request.client.host: user["ip"] = request.client.host

    is_busy = (controller.current_slot_user is not None and controller.current_slot_user != mac)
    
    slot_seconds_left = 0
    if controller.current_slot_user == mac:
        slot_seconds_left = int(max(0, state.config["slot_expiry_timestamp"] - time.time()))

    return {
        "time_remaining": user["time"], 
        "status": user["status"], 
        "balance": user["balance"], 
        "is_busy": is_busy,
        "slot_seconds": slot_seconds_left,
        "slot_max_seconds": state.config["slot_timeout"],
        "coin_rates": state.config.get("coin_rates", "1:10,5:60,10:180,20:300"),
        "banner_text": state.config.get("banner_text", ""),
        "banner_link": state.config.get("banner_link", "")
    }

# --- ACTION ROUTES ---

@router.get("/enable_slot")
async def enable_slot(mac: str):
    user = state.users.get(mac, {})
    if user.get("status") == "blocked": return {"result": "blocked"}

    if controller.current_slot_user is None or controller.current_slot_user == mac:
        controller.current_slot_user = mac
        controller.turn_slot_on()
        state.config["slot_expiry_timestamp"] = time.time() + state.config["slot_timeout"]
        
        current_balance = user.get("balance", 0)

        if mac in state.manager.active_connections:
            await state.manager.send_personal_message({
                "type": "slot_opened",
                "slot_seconds": state.config["slot_timeout"],
                "balance": current_balance,
                "coin_rates": state.config.get("coin_rates", "1:10,5:60,10:180,20:300"),
                "time_remaining": user.get("time", 0)
            }, mac)
        return {"result": "success"}
    return {"result": "busy"}

@router.post("/cancel_slot")
async def cancel_slot(mac: str):
    if controller.current_slot_user == mac:
        controller.turn_slot_off()
        state.config["slot_expiry_timestamp"] = 0
        return {"result": "success"}
    return {"result": "fail"}

@router.post("/connect")
async def start_internet(mac: str):
    user = state.users.get(mac)
    if user and user.get("status") == "blocked": return {"result": "blocked"}

    if user:
        balance = user.get("balance", 0)
        
        if balance > 0:
            added_minutes = calculate_time_from_balance(balance)
            user["time"] += (added_minutes * 60)
            user["balance"] = 0 
            database.sync_user(mac, user)
        
        if user["time"] > 0:
            user["status"] = "connected"
            user["last_active"] = time.time()
            user_ip = user.get("ip")
            firewall.allow_user(mac, user_ip)
            controller.turn_slot_off()
            database.sync_user(mac, user)
            
            # DELAY FOR FIREWALL
            time.sleep(1.0) 
            
            if mac in state.manager.active_connections:
                await state.manager.send_personal_message({
                    "type": "sync",
                    "status": "connected",
                    "time_remaining": user["time"],
                    "balance": 0
                }, mac)
                
            return {"result": "success"}

    return {"result": "fail"}

@router.post("/pause")
async def pause_internet(mac: str):
    if state.users.get(mac, {}).get("status") == "blocked": return {"result": "fail"}

    if state.users.get(mac) and state.users[mac]["status"] == "connected":
        state.users[mac]["status"] = "paused"
        firewall.block_user(mac)
        database.sync_user(mac, state.users[mac])
        
        if mac in state.manager.active_connections:
            await state.manager.send_personal_message({
                "type": "sync",
                "status": "paused",
                "time_remaining": state.users[mac]["time"],
                "balance": state.users[mac].get("balance", 0)
            }, mac)
        return {"result": "success"}
    return {"result": "fail"}

# --- NEW: CLAIM FREE TIME ENDPOINT ---
@router.post("/claim_free_time")
async def claim_free_time(mac: str):
    # 1. Validation
    if not state.config.get("free_time_enabled", False):
         return {"result": "disabled"}
    
    user = state.users.get(mac)
    if not user: return {"result": "error"} 
    
    if user.get("free_claimed", 0) == 1:
        return {"result": "already_claimed"}

    # 2. Apply Free Time
    duration = state.config.get("free_time_duration", 5) 
    user["time"] += (duration * 60)
    user["free_claimed"] = 1
    
    # 3. Auto-Connect User
    user["status"] = "connected"
    user["last_active"] = time.time()
    firewall.allow_user(mac, user.get("ip"))
    controller.turn_slot_off() # Ensure slot is off
    
    database.sync_user(mac, user)
    
    # 4. Notify Frontend
    if mac in state.manager.active_connections:
        await state.manager.send_personal_message({
            "type": "sync",
            "status": "connected",
            "time_remaining": user["time"],
            "balance": 0
        }, mac)

    return {"result": "success"}