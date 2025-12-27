# routers/client.py
import time
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
# from fastapi.templating import Jinja2Templates # <-- Removed this

import config
from core import database, state, utils
from core.templates import templates  # <-- NEW: Import the shared instance
from hardware import controller
from network import firewall

router = APIRouter()

# REMOVED: templates = Jinja2Templates(directory="templates") 
# We now use the imported 'templates' object directly.

# Captive Portal Triggers
@router.get("/generate_204")
@router.get("/ncsi.txt")
async def captive_portal_trigger():
    return RedirectResponse("/")

@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    client_ip = request.client.host
    client_mac = utils.get_mac(client_ip)
    
    if client_mac and client_mac not in state.users:
        state.users[client_mac] = {"time": 0, "status": "new"}
    
    return templates.TemplateResponse("index.html", {
        "request": request, 
        "mac": client_mac,
        "ip": client_ip,
        "banner_url": utils.get_banner_image()
    })

@router.get("/status")
async def check_status(mac: str):
    user = state.users.get(mac, {"time": 0, "status": "new"})
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

@router.get("/enable_slot")
async def enable_slot(mac: str):
    if controller.current_slot_user is None:
        controller.current_slot_user = mac
        controller.turn_slot_on()
        state.config["slot_expiry_timestamp"] = time.time() + state.config["slot_timeout"]
        return {"result": "success"}
    elif controller.current_slot_user == mac:
        return {"result": "success"}
    return {"result": "busy"}

@router.post("/connect")
async def start_internet(mac: str):
    if state.users.get(mac) and state.users[mac]["time"] > 0:
        state.users[mac]["status"] = "connected"
        firewall.allow_user(mac)
        controller.turn_slot_off()
        database.sync_user(mac, state.users[mac])
        return {"result": "success"}
    return {"result": "fail"}

@router.post("/pause")
async def pause_internet(mac: str):
    if state.users.get(mac) and state.users[mac]["status"] == "connected":
        state.users[mac]["status"] = "paused"
        firewall.block_user(mac)
        database.sync_user(mac, state.users[mac])
        return {"result": "success"}
    return {"result": "fail"}