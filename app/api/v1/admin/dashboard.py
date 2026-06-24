import math
from fastapi import APIRouter, Request, Depends, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import asyncio
import re
from core import state, security
from core.templates import templates
from app.api.dependencies import get_admin_service, get_system_ops, get_network_scanner
from services.admin_service import AdminService
from infrastructure.system_ops import SystemOps
from infrastructure.network_scanner import NetworkScanner

router = APIRouter()

@router.get("/admin", response_class=HTMLResponse)
def admin_panel(
    request: Request, 
    search: str = "", 
    page: int = 1, 
    authorized: bool = Depends(security.is_admin),
    admin_svc: AdminService = Depends(get_admin_service),
    sys_ops: SystemOps = Depends(get_system_ops),
    net_scan: NetworkScanner = Depends(get_network_scanner)
):
    ITEMS_PER_PAGE = 10
    stats = admin_svc.get_dashboard_stats()
    
    total_users_count = len(state.users)
    active_users_count = sum(1 for u in state.users.values() if u.get("status") == "connected")

    dhcp_leases = net_scan.get_dhcp_leases()
    enriched_users = []
    
    for mac, data in state.users.items():
        display_name, _ = net_scan.get_vendor_info_and_check_type(mac.lower(), data.get("ip", ""), dhcp_leases)
        data["device_name"] = display_name
        enriched_users.append((mac, data))
        
    if search:
        search_lower = search.lower()
        enriched_users = [(mac, data) for mac, data in enriched_users if search_lower in mac.lower()]

    def user_sort_key(item):
        mac, user_data = item
        status = user_data.get("status", "")
        time_left = user_data.get("time", 0)
        rank = 1 if status == "connected" else 3 if status == "expired" else 2
        return (rank, -time_left)

    enriched_users.sort(key=user_sort_key)

    total_filtered = len(enriched_users)
    total_pages = math.ceil(total_filtered / ITEMS_PER_PAGE) if total_filtered > 0 else 1
    
    if page < 1: page = 1
    if page > total_pages: page = total_pages

    start_idx = (page - 1) * ITEMS_PER_PAGE
    end_idx = start_idx + ITEMS_PER_PAGE
    paginated_users = dict(enriched_users[start_idx:end_idx])

    active_macs = set(state.users.keys())
    custom_names = state.config.get("custom_device_names", {})
    devices = net_scan.scan_infrastructure(active_macs, custom_names)

    banner_files = sys_ops.get_banners(state.config.get("banner_order", []))
    sound_files = sys_ops.get_sounds()
    system_logs = sys_ops.get_system_logs()

    return templates.TemplateResponse("admin.html", {
        "request": request, 
        "users": paginated_users, 
        "devices": devices,
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
        "sound_coin_selected": state.config.get("sound_coin", "coin-recieved.mp3"),
        "system_logs": system_logs
    })

@router.get("/admin/system_stats")
async def get_system_stats(authorized: bool = Depends(security.is_admin), sys_ops: SystemOps = Depends(get_system_ops)):
    return sys_ops.get_system_stats()

@router.get("/admin/get_infrastructure_devices")
def get_infrastructure_devices(authorized: bool = Depends(security.is_admin), net_scan: NetworkScanner = Depends(get_network_scanner)):
    active_macs = set(state.users.keys())
    custom_names = state.config.get("custom_device_names", {})
    devices = net_scan.scan_infrastructure(active_macs, custom_names)
    return {"devices": devices}

@router.get("/admin/api/logs")
async def get_logs_json(authorized: bool = Depends(security.is_admin), sys_ops: SystemOps = Depends(get_system_ops)):
    return {"logs": sys_ops.get_system_logs(limit=100)}


@router.websocket("/admin/ws/logs")
async def websocket_logs(websocket: WebSocket):
    await websocket.accept()
    # This regex pulls apart your professional log format: [Time] [Type] Message
    log_pattern = re.compile(r"\[(.*?)\] \[(.*?)\] (.*)")
    
    try:
        with open("system.log", "r") as f:
            # 1. Grab the last 50 lines for the initial load
            lines = f.readlines()
            last_lines = lines[-50:] if len(lines) > 50 else lines
            
            for line in last_lines:
                match = log_pattern.search(line)
                if match:
                    await websocket.send_json({
                        "timestamp": match.group(1),
                        "type": match.group(2),
                        "message": match.group(3)
                    })

            # 2. Tail the file continuously (Zero CPU overhead loop)
            while True:
                line = f.readline()
                if not line:
                    await asyncio.sleep(0.5) # Wait half a second if no new logs
                    continue
                
                match = log_pattern.search(line)
                if match:
                    await websocket.send_json({
                        "timestamp": match.group(1),
                        "type": match.group(2),
                        "message": match.group(3)
                    })
                    
    except WebSocketDisconnect:
        # Admin closed the dashboard tab
        pass
    except Exception as e:
        import logging
        logging.error(f"WebSocket Log Error: {e}")