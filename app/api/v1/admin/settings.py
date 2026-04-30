import os
import shutil
import json
from typing import List
from fastapi import APIRouter, Request, Form, UploadFile, File, Depends
from fastapi.responses import RedirectResponse

from core import database, state, security, utils
from network import firewall
from app.domain.models import RestartScheduleRequest, PointsConfigRequest
from app.api.dependencies import get_system_ops
from infrastructure.system_ops import SystemOps
from .helpers import audit_log

router = APIRouter()

@router.post("/admin/reboot")
async def reboot_device(
    request: Request, authorized: bool = Depends(security.is_admin),
    sys_ops: SystemOps = Depends(get_system_ops)
):
    client_ip = request.client.host
    client_mac = utils.get_mac(client_ip) or "Unknown-MAC"
    
    try:
        audit_log("SYSTEM_REBOOT", client_ip, client_mac, "Initiated manual system reboot")
        sys_ops.reboot_device()
        return {"status": "success", "message": "Rebooting now..."}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.post("/admin/clear_banners")
async def clear_banners(request: Request, authorized: bool = Depends(security.is_admin)):
    client_ip = request.client.host
    client_mac = utils.get_mac(client_ip) or "Unknown-MAC"

    folder = "static/banners/set"
    if os.path.exists(folder):
        for filename in os.listdir(folder):
            file_path = os.path.join(folder, filename)
            try:
                if os.path.isfile(file_path): os.unlink(file_path)
            except Exception as e: print(f"Error deleting {file_path}: {e}")
    if "banner_order" in state.config:
        state.config["banner_order"] = []
        state.save_config()
        
    audit_log("CONFIG_UPDATE", client_ip, client_mac, "Cleared all promotional banners")
    return RedirectResponse(url="/admin", status_code=303)

@router.post("/admin/upload_banners")
async def upload_banners(request: Request, files: List[UploadFile] = File(...), authorized: bool = Depends(security.is_admin)):
    client_ip = request.client.host
    client_mac = utils.get_mac(client_ip) or "Unknown-MAC"

    os.makedirs("static/banners/set", exist_ok=True)
    for file in files:
        if file.filename:
            file_location = f"static/banners/set/{file.filename}"
            with open(file_location, "wb+") as file_object:
                shutil.copyfileobj(file.file, file_object)
                
    audit_log("CONFIG_UPDATE", client_ip, client_mac, f"Uploaded {len(files)} new promotional banners")
    return RedirectResponse(url="/admin", status_code=303)

@router.post("/admin/save_banner_order")
async def save_banner_order(request: Request, order: str = Form(...), authorized: bool = Depends(security.is_admin)):
    try:
        file_list = json.loads(order)
        state.config["banner_order"] = file_list
        state.save_config()
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.post("/admin/delete_banner")
async def delete_banner(request: Request, filename: str = Form(...), authorized: bool = Depends(security.is_admin)):
    file_path = os.path.join("static/banners/set", filename)
    if os.path.exists(file_path):
        try: os.remove(file_path)
        except: pass
    if "banner_order" in state.config and filename in state.config["banner_order"]:
        state.config["banner_order"].remove(filename)
        state.save_config()
    return {"status": "success"}

@router.post("/admin/upload_sound")
async def upload_sound(request: Request, file: UploadFile = File(...), authorized: bool = Depends(security.is_admin)):
    client_ip = request.client.host
    client_mac = utils.get_mac(client_ip) or "Unknown-MAC"

    os.makedirs("static/sounds", exist_ok=True)
    if file.filename:
        file_location = f"static/sounds/{file.filename}"
        with open(file_location, "wb+") as file_object:
            shutil.copyfileobj(file.file, file_object)
            
    audit_log("CONFIG_UPDATE", client_ip, client_mac, f"Uploaded new sound file: {file.filename}")
    return RedirectResponse(url="/admin", status_code=303)

@router.post("/admin/update_settings")
async def update_settings(
    request: Request, timeout: int = Form(...), inactive_timeout: int = Form(...), 
    auto_pause: str = Form(None), speed_limit_val: int = Form(...),
    speed_limit_toggle: str = Form(None), gaming_mode: str = Form(None),
    coin_rates: str = Form(...), banner_text: str = Form(""),
    banner_link: str = Form(""), free_time_toggle: str = Form(None),
    free_time_duration: int = Form(5), sound_insert: str = Form("insert_coin_sound.mp3"),
    sound_coin: str = Form("coin-recieved.mp3"),
    authorized: bool = Depends(security.is_admin)
):
    client_ip = request.client.host
    client_mac = utils.get_mac(client_ip) or "Unknown-MAC"

    new_free_enabled = (free_time_toggle == "on")
    old_free_enabled = state.config.get("free_time_enabled", False)
    if new_free_enabled and not old_free_enabled:
        database.reset_all_free_claimed()
        for mac in state.users:
            state.users[mac]["free_claimed"] = 0

    state.config.update({
        "slot_timeout": timeout, "inactive_timeout": inactive_timeout,
        "auto_pause_enabled": (auto_pause == "on"), "global_speed_limit": speed_limit_val,
        "speed_limit_enabled": (speed_limit_toggle == "on"), "gaming_mode_enabled": (gaming_mode == "on"),
        "coin_rates": coin_rates, "banner_text": banner_text, "banner_link": banner_link,
        "sound_insert": sound_insert, "sound_coin": sound_coin,
        "free_time_enabled": new_free_enabled, "free_time_duration": free_time_duration
    })
    state.save_config()
    firewall.refresh_all_limits(state.users)
    
    audit_log("CONFIG_UPDATE", client_ip, client_mac, "Updated core system settings")
    return RedirectResponse(url="/admin", status_code=303)

@router.get("/admin/get_restart_schedule")
async def get_restart_schedule(authorized: bool = Depends(security.is_admin)):
    return state.config.get("restart_schedule", {"enabled": False, "time": "03:00"})

@router.post("/admin/set_restart_schedule")
async def set_restart_schedule(request: Request, data: RestartScheduleRequest, authorized: bool = Depends(security.is_admin)):
    client_ip = request.client.host
    client_mac = utils.get_mac(client_ip) or "Unknown-MAC"

    state.config["restart_schedule"] = {
        "enabled": data.enabled,
        "time": data.time
    }
    state.save_config()
    
    audit_log("CONFIG_UPDATE", client_ip, client_mac, f"Modified restart schedule to {data.time} (Enabled: {data.enabled})")
    return {"status": "success", "message": "Schedule updated"}

@router.get("/admin/get_points_config")
async def get_points_config(authorized: bool = Depends(security.is_admin)):
    return {
        "enabled": state.config.get("points_enabled", False),
        "coin_map": state.config.get("coin_point_map", {"1":0.5, "5":1, "10":3, "20":5}),
        "promos": state.config.get("point_promos", [])
    }

@router.post("/admin/save_points_config")
async def save_points_config(request: Request, data: PointsConfigRequest, authorized: bool = Depends(security.is_admin)):
    client_ip = request.client.host
    client_mac = utils.get_mac(client_ip) or "Unknown-MAC"

    state.config["points_enabled"] = data.enabled
    state.config["coin_point_map"] = data.coin_map
    state.config["point_promos"] = [p.dict() for p in data.promos]
    state.save_config()
    
    audit_log("CONFIG_UPDATE", client_ip, client_mac, "Modified global points configuration")
    return {"status": "success", "message": "Points configuration saved"}