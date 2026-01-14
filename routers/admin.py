# routers/admin.py
import os
import shutil
import time
import json 
import psutil 
import socket 
import subprocess
from datetime import datetime, timedelta
from typing import List
from fastapi import APIRouter, Request, Form, UploadFile, File, Depends
from fastapi.responses import HTMLResponse, RedirectResponse

import config
from core import database, state, security
from core.templates import templates
from network import firewall

router = APIRouter()

# --- LOGIN / AUTH ROUTES ---

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@router.post("/auth")
async def login_action(username: str = Form(...), password: str = Form(...)):
    if database.verify_admin(username, password):
        response = RedirectResponse(url="/admin", status_code=303)
        response.set_cookie(key="admin_token", value="secret_logged_in_token")
        return response
    return RedirectResponse(url="/login?error=Invalid Credentials", status_code=303)

@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("admin_token")
    return response

# --- SYSTEM STATUS API (UPDATED FOR NETWORK SPEED) ---

@router.get("/admin/system_stats")
async def get_system_stats(authorized: bool = Depends(security.is_admin)):
    """API endpoint to fetch real-time hardware metrics including Network Speed."""
    
    # 1. CPU Temp
    cpu_temp = "N/A"
    try:
        # Try finding Orange Pi specific thermal zone
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            cpu_temp = round(int(f.read()) / 1000, 1)
    except:
        # Fallback to psutil sensors
        try:
            temps = psutil.sensors_temperatures()
            if 'cpu_thermal' in temps: 
                cpu_temp = temps['cpu_thermal'][0].current
            elif 'coretemp' in temps: 
                cpu_temp = temps['coretemp'][0].current
        except: pass

    # 2. Memory & Disk
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage('/')

    # 3. Network Speed Calculation (WAN Interface)
    # We send total bytes; Frontend JS calculates the speed difference.
    net_stats = psutil.net_io_counters(pernic=True)
    wan_stats = net_stats.get(config.WAN_INTERFACE)
    
    rx_bytes = wan_stats.bytes_recv if wan_stats else 0
    tx_bytes = wan_stats.bytes_sent if wan_stats else 0

    # 4. Uptime Calculation
    try:
        boot_time = psutil.boot_time()
        seconds = time.time() - boot_time
        m, s = divmod(seconds, 60)
        h, m = divmod(m, 60)
        d, h = divmod(h, 24)
        
        if d > 0:
            uptime_str = f"{int(d)}d {int(h)}h {int(m)}m"
        elif h > 0:
            uptime_str = f"{int(h)}h {int(m)}m"
        else:
            uptime_str = f"{int(m)} min"
    except:
        uptime_str = "Unknown"

    # 5. IP Addresses
    ip_list = []
    try:
        interfaces = psutil.net_if_addrs()
        for iface_name, iface_addrs in interfaces.items():
            for addr in iface_addrs:
                if addr.family == socket.AF_INET and not iface_name.startswith("lo"):
                    ip_list.append(addr.address)
    except:
        ip_list = ["Error"]

    return {
        "cpu": psutil.cpu_percent(interval=None),
        "temp": cpu_temp,
        "ram": mem.percent,
        "ram_used": round(mem.used / (1024**3), 2),
        "ram_total": round(mem.total / (1024**3), 2),
        "disk": disk.percent,
        "disk_free": round(disk.free / (1024**3), 2),
        "uptime": uptime_str,
        "ips": " ".join(ip_list),
        "wan_rx_total": rx_bytes, # <--- Used for Download Speed
        "wan_tx_total": tx_bytes  # <--- Used for Upload Speed
    }

# --- ADMIN PANEL ---

@router.get("/admin", response_class=HTMLResponse)
async def admin_panel(
    request: Request, 
    search: str = "", 
    page: int = 1, 
    authorized: bool = Depends(security.is_admin)
):
    # Pagination Settings
    ITEMS_PER_PAGE = 10
    
    # --- SALES CALCULATIONS ---
    now = datetime.now()
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    ts_day = start_of_day.timestamp()
    start_of_week = start_of_day - timedelta(days=now.weekday())
    ts_week = start_of_week.timestamp()
    start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    ts_month = start_of_month.timestamp()
    start_of_year = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    ts_year = start_of_year.timestamp()

    stats = {
        "total": database.get_total_sales(),
        "daily": database.get_sales_since(ts_day),
        "weekly": database.get_sales_since(ts_week),
        "monthly": database.get_sales_since(ts_month),
        "yearly": database.get_sales_since(ts_year),
    }

    # --- USER COUNTS ---
    total_users_count = len(state.users)
    active_users_count = sum(1 for u in state.users.values() if u.get("status") == "connected")

    # --- FILTER, SORT & PAGINATION LOGIC ---
    all_users = list(state.users.items())

    if search:
        search_lower = search.lower()
        all_users = [(mac, data) for mac, data in all_users if search_lower in mac.lower()]

    def user_sort_key(item):
        mac, user_data = item
        status = user_data.get("status", "")
        time_left = user_data.get("time", 0)
        rank = 1 if status == "connected" else 3 if status == "expired" else 2
        return (rank, -time_left)

    all_users.sort(key=user_sort_key)

    import math
    total_filtered = len(all_users)
    total_pages = math.ceil(total_filtered / ITEMS_PER_PAGE) if total_filtered > 0 else 1
    
    if page < 1: page = 1
    if page > total_pages: page = total_pages

    start_idx = (page - 1) * ITEMS_PER_PAGE
    end_idx = start_idx + ITEMS_PER_PAGE
    paginated_users = dict(all_users[start_idx:end_idx])

    # --- BANNERS LOGIC ---
    banner_files = []
    if os.path.exists("static/banners/set"):
        actual_files = os.listdir("static/banners/set")
        saved_order = state.config.get("banner_order", [])
        for f in saved_order:
            if f in actual_files: banner_files.append(f)
        for f in actual_files:
            if f not in banner_files: banner_files.append(f)

    # --- SOUND FILES LOGIC ---
    sound_files = []
    if os.path.exists("static/sounds"):
        sound_files = [f for f in os.listdir("static/sounds") if f.lower().endswith(('.mp3', '.wav', '.ogg'))]

    return templates.TemplateResponse("admin.html", {
        "request": request, 
        "users": paginated_users, 
        "current_page": page,
        "total_pages": total_pages,
        "search_query": search,
        "active_users": active_users_count,
        "total_users": total_users_count,
        "stats": stats,
        # SETTINGS
        "slot_timeout": state.config.get("slot_timeout", 30),
        "inactive_timeout": state.config.get("inactive_timeout", 60),
        "auto_pause_enabled": state.config.get("auto_pause_enabled", True),
        "speed_limit_enabled": state.config.get("speed_limit_enabled", False),
        "global_speed_limit": state.config.get("global_speed_limit", 5),
        "gaming_mode_enabled": state.config.get("gaming_mode_enabled", False),
        "coin_rates": state.config.get("coin_rates", "1:10,5:60,10:180,20:300"),
        "banner_text": state.config.get("banner_text", ""),
        "banner_link": state.config.get("banner_link", ""),
        "banner_files": banner_files,
        "free_time_enabled": state.config.get("free_time_enabled", False),
        "free_time_duration": state.config.get("free_time_duration", 5),
        "sound_files": sound_files,
        "sound_insert_selected": state.config.get("sound_insert", "insert_coin_sound.mp3"),
        "sound_coin_selected": state.config.get("sound_coin", "coin-recieved.mp3")
    })

# --- CONFIGURATION ROUTES ---

@router.post("/admin/clear_banners")
async def clear_banners(authorized: bool = Depends(security.is_admin)):
    folder = "static/banners/set"
    if os.path.exists(folder):
        for filename in os.listdir(folder):
            file_path = os.path.join(folder, filename)
            try:
                if os.path.isfile(file_path):
                    os.unlink(file_path)
            except Exception as e:
                print(f"Error deleting {file_path}: {e}")
    if "banner_order" in state.config:
        state.config["banner_order"] = []
        state.save_config()
    return RedirectResponse(url="/admin", status_code=303)

@router.post("/admin/upload_banners")
async def upload_banners(files: List[UploadFile] = File(...), authorized: bool = Depends(security.is_admin)):
    os.makedirs("static/banners/set", exist_ok=True)
    for file in files:
        if file.filename:
            file_location = f"static/banners/set/{file.filename}"
            with open(file_location, "wb+") as file_object:
                shutil.copyfileobj(file.file, file_object)
    return RedirectResponse(url="/admin", status_code=303)

@router.post("/admin/save_banner_order")
async def save_banner_order(order: str = Form(...), authorized: bool = Depends(security.is_admin)):
    try:
        file_list = json.loads(order)
        state.config["banner_order"] = file_list
        state.save_config()
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.post("/admin/delete_banner")
async def delete_banner(filename: str = Form(...), authorized: bool = Depends(security.is_admin)):
    file_path = os.path.join("static/banners/set", filename)
    if os.path.exists(file_path):
        try: os.remove(file_path)
        except: pass
    if "banner_order" in state.config and filename in state.config["banner_order"]:
        state.config["banner_order"].remove(filename)
        state.save_config()
    return {"status": "success"}

@router.post("/admin/upload_sound")
async def upload_sound(file: UploadFile = File(...), authorized: bool = Depends(security.is_admin)):
    os.makedirs("static/sounds", exist_ok=True)
    if file.filename:
        file_location = f"static/sounds/{file.filename}"
        with open(file_location, "wb+") as file_object:
            shutil.copyfileobj(file.file, file_object)
    return RedirectResponse(url="/admin", status_code=303)

@router.post("/admin/update_settings")
async def update_settings(
    timeout: int = Form(...), inactive_timeout: int = Form(...), 
    auto_pause: str = Form(None), speed_limit_val: int = Form(...),
    speed_limit_toggle: str = Form(None), gaming_mode: str = Form(None),
    coin_rates: str = Form(...), banner_text: str = Form(""),
    banner_link: str = Form(""), free_time_toggle: str = Form(None),
    free_time_duration: int = Form(5), sound_insert: str = Form("insert_coin_sound.mp3"),
    sound_coin: str = Form("coin-recieved.mp3"),
    authorized: bool = Depends(security.is_admin)
):
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
    return RedirectResponse(url="/admin", status_code=303)

# --- MANAGE TIME & USERS ---

@router.post("/admin/manage_time")
async def admin_manage_time(
    mac: str = Form(...), amount: int = Form(...), unit: str = Form(...),
    action: str = Form(...), authorized: bool = Depends(security.is_admin)
):
    if mac in state.users:
        try:
            amount = abs(int(amount))
            seconds = amount * 3600 if unit == "hours" else amount * 60
            
            if action == "subtract":
                state.users[mac]["time"] -= seconds
            elif action == "add":
                state.users[mac]["time"] += seconds
            
            if state.users[mac]["time"] < 0: state.users[mac]["time"] = 0
            
            # Status updates
            if state.users[mac]["time"] == 0 and state.users[mac]["status"] == "connected":
                state.users[mac]["status"] = "expired"
                firewall.block_user(mac)
            
            if action == "add" and state.users[mac]["time"] > 0 and state.users[mac]["status"] == "expired":
                 state.users[mac]["status"] = "connected"
                 firewall.allow_user(mac, state.users[mac].get("ip"))

            database.sync_user(mac, state.users[mac])
        except ValueError:
            pass 
    return RedirectResponse(url="/admin", status_code=303)

@router.post("/admin/block")
async def admin_block(mac: str = Form(...), authorized: bool = Depends(security.is_admin)):
    if mac in state.users:
        state.users[mac]["status"] = "blocked"
        firewall.block_user(mac)
        database.sync_user(mac, state.users[mac])
    return RedirectResponse(url="/admin", status_code=303)

@router.post("/admin/unblock")
async def admin_unblock(mac: str = Form(...), authorized: bool = Depends(security.is_admin)):
    if mac in state.users:
        state.users[mac]["status"] = "new"
        database.sync_user(mac, state.users[mac])
    return RedirectResponse(url="/admin", status_code=303)

@router.post("/admin/delete_user")
async def admin_delete_user(mac: str = Form(...), authorized: bool = Depends(security.is_admin)):
    if mac in state.users:
        firewall.block_user(mac)
        del state.users[mac]
        database.delete_user(mac)
    return RedirectResponse(url="/admin", status_code=303)


@router.post("/admin/reboot")
async def reboot_device(authorized: bool = Depends(security.is_admin)):
    """Reboots the Orange Pi immediately."""
    try:
        # 'sudo' is usually not needed if running as root service, but safe to keep
        subprocess.run(["sudo", "reboot"])
        return {"status": "success", "message": "Rebooting now..."}
    except Exception as e:
        return {"status": "error", "message": str(e)}