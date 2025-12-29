import time
from fastapi import APIRouter, Request, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse

import config
from core import database, state, utils
from core.templates import templates
from hardware import controller
from network import firewall

router = APIRouter()

# --- WEBSOCKET ROUTE ---
@router.websocket("/ws/{mac}")
async def websocket_endpoint(websocket: WebSocket, mac: str):
    await state.manager.connect(mac, websocket)
    
    # 1. CAPTURE IP ON CONNECT
    if mac in state.users and websocket.client.host:
        state.users[mac]["ip"] = websocket.client.host
        state.users[mac]["last_active"] = time.time()
        
    try:
        while True:
            await websocket.receive_text()
            # 2. UPDATE ACTIVITY
            if mac in state.users:
                state.users[mac]["last_active"] = time.time()
    except WebSocketDisconnect:
        state.manager.disconnect(mac)

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
            state.users[client_mac] = {"time": 0, "status": "new"}
        
        # 3. CAPTURE IP ON LOGIN PAGE LOAD
        state.users[client_mac]["ip"] = client_ip
        state.users[client_mac]["last_active"] = time.time()
    
    return templates.TemplateResponse("index.html", {
        "request": request, 
        "mac": client_mac,
        "ip": client_ip,
        "banner_url": utils.get_banner_image()
    })

@router.post("/connect")
async def start_internet(mac: str):
    if state.users.get(mac) and state.users[mac]["time"] > 0:
        state.users[mac]["status"] = "connected"
        state.users[mac]["last_active"] = time.time()
        
        # --- PASS IP TO FIREWALL FOR SPEED LIMIT ---
        user_ip = state.users[mac].get("ip")
        firewall.allow_user(mac, user_ip)
        
        controller.turn_slot_off()
        database.sync_user(mac, state.users[mac])
        
        if mac in state.manager.active_connections:
            await state.manager.send_personal_message({
                "type": "sync",
                "status": "connected",
                "time_remaining": state.users[mac]["time"]
            }, mac)
            
        return {"result": "success"}
    return {"result": "fail"}

@router.get("/status")
async def check_status(mac: str, request: Request):
    user = state.users.get(mac, {"time": 0, "status": "new"})
    
    # 4. CAPTURE IP ON STATUS CHECK
    if request.client.host:
        user["ip"] = request.client.host

    is_busy = (controller.current_slot_user is not None and controller.current_slot_user != mac)
    
    slot_seconds_left = 0
    if controller.current_slot_user == mac:
        slot_seconds_left = int(max(0, state.config["slot_expiry_timestamp"] - time.time()))

    return {
        "time_remaining": user["time"], 
        "status": user["status"], 
        "is_busy": is_busy,
        "slot_seconds": slot_seconds_left,
        "slot_max_seconds": state.config["slot_timeout"]
    }

# --- ACTION ROUTES ---

@router.get("/enable_slot")
async def enable_slot(mac: str):
    if controller.current_slot_user is None:
        controller.current_slot_user = mac
        controller.turn_slot_on()
        state.config["slot_expiry_timestamp"] = time.time() + state.config["slot_timeout"]
        
        if mac in state.manager.active_connections:
            await state.manager.send_personal_message({
                "type": "slot_opened",
                "slot_seconds": state.config["slot_timeout"],
                "time_remaining": state.users.get(mac, {}).get("time", 0)
            }, mac)

        return {"result": "success"}
        
    elif controller.current_slot_user == mac:
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
    if state.users.get(mac) and state.users[mac]["time"] > 0:
        state.users[mac]["status"] = "connected"
        state.users[mac]["last_active"] = time.time()
        
        firewall.allow_user(mac)
        controller.turn_slot_off()
        database.sync_user(mac, state.users[mac])
        
        # --- FIX: NOTIFY UI IMMEDIATELY ---
        if mac in state.manager.active_connections:
            await state.manager.send_personal_message({
                "type": "sync",
                "status": "connected",
                "time_remaining": state.users[mac]["time"]
            }, mac)
            
        return {"result": "success"}
    return {"result": "fail"}

@router.post("/pause")
async def pause_internet(mac: str):
    if state.users.get(mac) and state.users[mac]["status"] == "connected":
        state.users[mac]["status"] = "paused"
        firewall.block_user(mac)
        database.sync_user(mac, state.users[mac])
        
        # --- FIX: NOTIFY UI IMMEDIATELY ---
        if mac in state.manager.active_connections:
            await state.manager.send_personal_message({
                "type": "sync",
                "status": "paused",
                "time_remaining": state.users[mac]["time"]
            }, mac)

        return {"result": "success"}
    return {"result": "fail"}