import os
import time
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from core import state, utils
from core.templates import templates
from hardware import controller

router = APIRouter()

@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    client_ip = request.client.host
    client_mac = utils.get_mac(client_ip)
    
    if client_mac:
        if client_mac not in state.users:
            state.users[client_mac] = {"time": 0, "status": "new", "balance": 0, "free_claimed": 0, "points": 0}
        state.users[client_mac]["ip"] = client_ip
        state.users[client_mac]["last_active"] = time.time()
    
    # Check for banners
    banner_dir = "static/banners/set"
    banners = []
    if os.path.exists(banner_dir):
        all_files = [f for f in os.listdir(banner_dir) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp'))]
        saved_order = state.config.get("banner_order", [])
        ordered_files = [f for f in saved_order if f in all_files] + [f for f in all_files if f not in saved_order]
        if ordered_files: banners = [f"/static/banners/set/{f}" for f in ordered_files]
    
    if not banners:
        banners = ["/static/banners/default/banner_default.jpg"]

    user_data = state.users.get(client_mac, {})
    is_claimed = (user_data.get("free_claimed", 0) == 1)
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
        "free_time_enabled": state.config.get("free_time_enabled", False),
        "free_claimed": is_claimed,
        "free_duration": state.config.get("free_time_duration", 5),
        "sound_insert_url": f"/static/sounds/{s_insert}",
        "sound_coin_url": f"/static/sounds/{s_coin}",
        "points": user_data.get("points", 0),
        "points_enabled": state.config.get("points_enabled", False),
        "coin_point_map": state.config.get("coin_point_map", {}) 
    })

@router.get("/status")
async def check_status(mac: str, request: Request):
    user = state.users.get(mac, {"time": 0, "status": "new", "balance": 0})
    if "balance" not in user: user["balance"] = 0
    if request.client.host: user["ip"] = request.client.host

    is_busy = (controller.current_slot_user is not None and controller.current_slot_user != mac)
    slot_seconds_left = int(max(0, state.config.get("slot_expiry_timestamp", 0) - time.time())) if controller.current_slot_user == mac else 0

    return {
        "time_remaining": user["time"], 
        "status": user["status"], 
        "balance": user["balance"], 
        "is_busy": is_busy,
        "slot_seconds": slot_seconds_left,
        "slot_max_seconds": state.config.get("slot_timeout", 30),
        "coin_rates": state.config.get("coin_rates", "1:10,5:60,10:180,20:300"),
        "banner_text": state.config.get("banner_text", ""),
        "banner_link": state.config.get("banner_link", ""),
        "points": user.get("points", 0),
        "points_enabled": state.config.get("points_enabled", False),
        "coin_point_map": state.config.get("coin_point_map", {})
    }