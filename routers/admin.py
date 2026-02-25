import os
import shutil
import time
import json 
import psutil 
import socket 
import subprocess
from datetime import datetime, timedelta
from typing import List, Dict
from fastapi import APIRouter, Request, Form, UploadFile, File, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
import config
from core import database, state, security
from core.templates import templates
from network import firewall

router = APIRouter()

# --- LOGIN / AUTH ROUTES ---
class RestartScheduleRequest(BaseModel):
    enabled: bool
    time: str

class PromoItem(BaseModel):
    id: int
    name: str
    cost: float
    minutes: int

class PointsConfigRequest(BaseModel):
    enabled: bool
    coin_map: Dict[str, float]
    promos: List[PromoItem]

class RenameRequest(BaseModel):
    mac: str
    name: str

@router.get("/admin/get_restart_schedule")
async def get_restart_schedule(authorized: bool = Depends(security.is_admin)):
    return state.config.get("restart_schedule", {"enabled": False, "time": "03:00"})

@router.post("/admin/set_restart_schedule")
async def set_restart_schedule(data: RestartScheduleRequest, authorized: bool = Depends(security.is_admin)):
    state.config["restart_schedule"] = {
        "enabled": data.enabled,
        "time": data.time
    }
    state.save_config()
    return {"status": "success", "message": "Schedule updated"}

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@router.post("/auth")
async def login_action(username: str = Form(...), password: str = Form(...)):
    if database.verify_admin(username, password):
        access_token_expires = timedelta(minutes=30)
        access_token = security.create_access_token(
            data={"sub": username},
            expires_delta=access_token_expires
        )
        
        response = RedirectResponse(url="/admin", status_code=303)
        response.set_cookie(
            key="admin_token", 
            value=access_token, 
            httponly=True,
            samesite="lax",
            secure=False
        )
        return response
        
    return RedirectResponse(url="/login?error=Invalid Credentials", status_code=303)

@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("admin_token")
    return response

# --- SYSTEM STATUS API ---

@router.get("/admin/system_stats")
async def get_system_stats(authorized: bool = Depends(security.is_admin)):
    cpu_temp = "N/A"
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            cpu_temp = round(int(f.read()) / 1000, 1)
    except:
        try:
            temps = psutil.sensors_temperatures()
            if 'cpu_thermal' in temps: 
                cpu_temp = temps['cpu_thermal'][0].current
            elif 'coretemp' in temps: 
                cpu_temp = temps['coretemp'][0].current
        except: pass

    mem = psutil.virtual_memory()
    disk = psutil.disk_usage('/')

    net_stats = psutil.net_io_counters(pernic=True)
    wan_stats = net_stats.get(config.WAN_INTERFACE)
    
    rx_bytes = wan_stats.bytes_recv if wan_stats else 0
    tx_bytes = wan_stats.bytes_sent if wan_stats else 0

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
        "wan_rx_total": rx_bytes,
        "wan_tx_total": tx_bytes
    }

# --- ADMIN PANEL ---

@router.get("/admin", response_class=HTMLResponse)
async def admin_panel(
    request: Request, 
    search: str = "", 
    page: int = 1, 
    authorized: bool = Depends(security.is_admin)
):
    ITEMS_PER_PAGE = 10
    
    now = datetime.now()
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    ts_day = start_of_day.timestamp()
    start_of_week = start_of_day - timedelta(days=now.weekday())
    ts_week = start_of_week.timestamp()
    start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    ts_month = start_of_month.timestamp()
    start_of_year = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    ts_year = start_of_year.timestamp()
    start_of_yesterday = start_of_day - timedelta(days=1)
    ts_yesterday_start = start_of_yesterday.timestamp()

    stats = {
        "total": database.get_total_sales(),
        "yesterday": database.get_sales_range(ts_yesterday_start, ts_day),
        "daily": database.get_sales_since(ts_day),
        "weekly": database.get_sales_since(ts_week),
        "monthly": database.get_sales_since(ts_month),
        "yearly": database.get_sales_since(ts_year),
    }

    total_users_count = len(state.users)
    active_users_count = sum(1 for u in state.users.values() if u.get("status") == "connected")

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

    banner_files = []
    if os.path.exists("static/banners/set"):
        actual_files = os.listdir("static/banners/set")
        saved_order = state.config.get("banner_order", [])
        for f in saved_order:
            if f in actual_files: banner_files.append(f)
        for f in actual_files:
            if f not in banner_files: banner_files.append(f)

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

@router.post("/admin/clear_banners")
async def clear_banners(authorized: bool = Depends(security.is_admin)):
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
    try:
        subprocess.run(["sudo", "reboot"])
        return {"status": "success", "message": "Rebooting now..."}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.get("/admin/get_points_config")
async def get_points_config(authorized: bool = Depends(security.is_admin)):
    return {
        "enabled": state.config.get("points_enabled", False),
        "coin_map": state.config.get("coin_point_map", {"1":0.5, "5":1, "10":3, "20":5}),
        "promos": state.config.get("point_promos", [])
    }

@router.post("/admin/save_points_config")
async def save_points_config(data: PointsConfigRequest, authorized: bool = Depends(security.is_admin)):
    state.config["points_enabled"] = data.enabled
    state.config["coin_point_map"] = data.coin_map
    state.config["point_promos"] = [p.dict() for p in data.promos]
    state.save_config()
    return {"status": "success", "message": "Points configuration saved"}

# --- INFRASTRUCTURE SCANNING ---

def get_vendor_info_and_check_type(mac: str, leases: dict) -> tuple[str, bool]:
    mac_clean = mac.replace(":", "").replace("-", "").upper()
    oui = mac_clean[:6]
    
    vendors = {
        # --- COMFAST ---
        "200DB0": "Comfast", "40A5EF": "Comfast", "E0E1A9": "Comfast", "8C3D16": "Comfast", "00E04C": "Comfast",
        # --- TP-LINK ---
        "18D6C7": "TP-Link", "CC32E5": "TP-Link", "003192": "TP-Link", "14CC20": "TP-Link",
        "50C7BF": "TP-Link", "8416F9": "TP-Link", "C025E9": "TP-Link", "E848B8": "TP-Link",
        "000AEB": "TP-Link", "001478": "TP-Link", "0019E0": "TP-Link", "001D0F": "TP-Link",
        "002127": "TP-Link", "0023CD": "TP-Link", "002586": "TP-Link", "002719": "TP-Link",
        "04F9F8": "TP-Link", "081F71": "TP-Link", "0C4B54": "TP-Link", "10FEED": "TP-Link",
        "147590": "TP-Link", "14CF92": "TP-Link", "18A6F7": "TP-Link", "1C3BF3": "TP-Link",
        "206BE7": "TP-Link", "20DCE6": "TP-Link", "246968": "TP-Link", "282CB2": "TP-Link",
        "30B5C2": "TP-Link", "349672": "TP-Link", "34E894": "TP-Link", "388345": "TP-Link",
        "3C46D8": "TP-Link", "40169F": "TP-Link", "44B32D": "TP-Link", "480EEC": "TP-Link",
        "503EAA": "TP-Link", "50BD5F": "TP-Link", "54E6FC": "TP-Link", "584120": "TP-Link",
        "60E327": "TP-Link", "6466B3": "TP-Link", "704F57": "TP-Link", "7405A5": "TP-Link",
        "74DA88": "TP-Link", "7844FD": "TP-Link", "7C8BCA": "TP-Link", "808917": "TP-Link",
        "882593": "TP-Link", "8C210A": "TP-Link", "90F652": "TP-Link", "940C6D": "TP-Link",
        "984827": "TP-Link", "98DED0": "TP-Link", "A0F3C1": "TP-Link", "A42BB0": "TP-Link",
        "AC84C6": "TP-Link", "B0487A": "TP-Link", "B0BE76": "TP-Link", "B8F883": "TP-Link",
        "C04A00": "TP-Link", "C46E1F": "TP-Link", "CC3429": "TP-Link", "D4016D": "TP-Link",
        "D807B6": "TP-Link", "DC0077": "TP-Link", "E005C5": "TP-Link", "E4C32A": "TP-Link",
        "EC086B": "TP-Link", "F4F26D": "TP-Link", "F81A67": "TP-Link", "FC70F4": "TP-Link",
        # --- TENDA ---
        "0495E6": "Tenda", "0840F3": "Tenda", "500FF5": "Tenda", "502B73": "Tenda",
        "CC2D21": "Tenda", "C83A35": "Tenda", "0050FC": "Tenda",
        # --- FIBER MODEMS ---
        "001882": "Huawei", "00E0FC": "Huawei", "4846F1": "Huawei", 
        "0015EB": "ZTE", "001E73": "ZTE", "D0DD7C": "ZTE",
        "286ED4": "FiberHome", "807D14": "FiberHome"
    }

    brand = vendors.get(oui, "Unknown")
    hostname = leases.get(mac, "")
    if hostname == "*": hostname = ""
    
    is_known = (brand != "Unknown")

    if brand != "Unknown" and hostname:
        display = f"{brand} ({hostname})"
    elif brand != "Unknown":
        display = brand
    elif hostname:
        display = f"Unknown ({hostname})"
    else:
        display = "Unknown Device"
        
    return display, is_known

def is_random_mac(mac: str) -> bool:
    try:
        first_byte = int(mac.split(':')[0], 16)
        return (first_byte & 0x02) != 0
    except:
        return False

@router.post("/admin/rename_device")
async def rename_device(data: RenameRequest, authorized: bool = Depends(security.is_admin)):
    if "custom_device_names" not in state.config:
        state.config["custom_device_names"] = {}
    
    state.config["custom_device_names"][data.mac] = data.name.strip()
    state.save_config()
    return {"status": "success"}

def is_reachable(ip: str) -> bool:
    try:
        subprocess.check_call(
            ['ping', '-c', '1', '-W', '1', ip],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        return True
    except:
        return False

@router.get("/admin/get_infrastructure_devices")
async def get_infrastructure_devices(authorized: bool = Depends(security.is_admin)):
    devices = []
    active_user_macs = set(state.users.keys())
    custom_names = state.config.get("custom_device_names", {})

    dhcp_leases = {}
    lease_files = ["/var/lib/misc/dnsmasq.leases", "/var/lib/dnsmasq/dnsmasq.leases"]
    for lf in lease_files:
        if os.path.exists(lf):
            try:
                with open(lf, 'r') as f:
                    for line in f:
                        parts = line.split()
                        if len(parts) >= 4:
                            dhcp_leases[parts[1]] = parts[3] 
            except: pass

    try:
        with open('/proc/net/arp') as f:
            lines = f.readlines()[1:] 

        for line in lines:
            parts = line.split()
            if len(parts) < 6: continue
            
            ip, hw_type, flags, mac, mask, interface = parts[:6]

            # We relax the strict filter. 
            # We SHOW "Unknown Devices" now so you can find your Comfast APs.
            if (interface == config.LAN_INTERFACE and 
                mac != "00:00:00:00:00:00" and 
                mac not in active_user_macs):
                
                # 1. Filter Random MACs (Likely Phones) - KEEP
                if is_random_mac(mac) and mac not in custom_names:
                    continue

                display_name, is_known_brand = get_vendor_info_and_check_type(mac, dhcp_leases)
                
                # 2. Filter Explicit Hostnames (Likely Phones) - KEEP
                # Clean up the list by hiding obvious phones
                name_upper = display_name.upper()
                phone_keywords = ["NAM", "V2", "OPPO", "VIVO", "REALME", "IPHONE", "GALAXY", "XIAOMI", "POCO", "REDMI", "ANDROID"]
                
                is_likely_phone = False
                for kw in phone_keywords:
                    if kw in name_upper:
                        is_likely_phone = True
                        break
                
                if is_likely_phone and mac not in custom_names:
                    continue
                
                # 3. SHOW EVERYTHING ELSE (Even Unknowns)
                # This ensures your Comfasts will appear even if my list is missing their MAC prefix.
                
                online_status = is_reachable(ip)

                if mac in custom_names and custom_names[mac]:
                    display_name = f"{custom_names[mac]}"
                    is_custom = True
                else:
                    is_custom = False
                
                devices.append({
                    "ip": ip,
                    "mac": mac,
                    "vendor": display_name,
                    "is_custom": is_custom,
                    "is_online": online_status
                })

    except Exception as e:
        print(f"ARP Error: {e}")

    return {"devices": devices}