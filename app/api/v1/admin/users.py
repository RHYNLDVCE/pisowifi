from datetime import datetime
from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse

from core import database, state, security, utils
from core.templates import templates
from app.domain.models import RenameRequest
from app.api.dependencies import get_admin_service, get_network_scanner
from services.admin_service import AdminService
from infrastructure.network_scanner import NetworkScanner
from core.logger import audit_log

router = APIRouter()

@router.get("/admin/user/{mac}", response_class=HTMLResponse)
async def manage_single_user(
    request: Request, mac: str, authorized: bool = Depends(security.is_admin),
    net_scan: NetworkScanner = Depends(get_network_scanner)
):
    if mac not in state.users:
        return RedirectResponse(url="/admin", status_code=303)
    
    user_data = state.users[mac]
    display_name, _ = net_scan.get_vendor_info_and_check_type(mac.lower(), user_data.get("ip", ""), net_scan.get_dhcp_leases())
    user_data["device_name"] = display_name

    sales_history = database.get_user_sales(mac)
    for s in sales_history:
        dt = datetime.fromtimestamp(s["timestamp"])
        s["date_str"] = dt.strftime("%b %d, %Y %I:%M %p")

    return templates.TemplateResponse("components/manage_user.html", {
        "request": request, 
        "mac": mac, 
        "user": user_data,
        "history": sales_history
    })

@router.post("/admin/manage_time")
async def admin_manage_time(
    request: Request,
    mac: str = Form(...), amount: int = Form(...), unit: str = Form(...),
    action: str = Form(...), authorized: bool = Depends(security.is_admin),
    admin_svc: AdminService = Depends(get_admin_service)
):
    client_ip = request.client.host
    client_mac = utils.get_mac(client_ip) or "Unknown-MAC"

    admin_svc.manage_user_time(mac, amount, unit, action)
    audit_log("TIME_UPDATE", client_ip, client_mac, f"{action.upper()} {amount} {unit} applied to target user {mac}")
    
    return RedirectResponse(url=f"/admin/user/{mac}", status_code=303)

@router.post("/admin/manage_points")
async def admin_manage_points(
    request: Request, mac: str = Form(...), amount: float = Form(...),
    action: str = Form(...), authorized: bool = Depends(security.is_admin)
):
    client_ip = request.client.host
    client_mac = utils.get_mac(client_ip) or "Unknown-MAC"

    if mac in state.users:
        try:
            amount = abs(float(amount))
            if action == "subtract":
                state.users[mac]["points"] -= amount
            elif action == "add":
                state.users[mac]["points"] += amount
            
            if state.users[mac]["points"] < 0: state.users[mac]["points"] = 0
            database.sync_user(mac, state.users[mac])
            
            audit_log("POINTS_UPDATE", client_ip, client_mac, f"{action.upper()} {amount} points applied to target user {mac}")
        except ValueError:
            pass 
    return RedirectResponse(url=f"/admin/user/{mac}", status_code=303)

@router.post("/admin/block")
async def admin_block(
    request: Request, mac: str = Form(...), authorized: bool = Depends(security.is_admin),
    admin_svc: AdminService = Depends(get_admin_service)
):
    client_ip = request.client.host
    client_mac = utils.get_mac(client_ip) or "Unknown-MAC"

    admin_svc.update_user_status(mac, "blocked")
    audit_log("USER_BLOCKED", client_ip, client_mac, f"Blocked access for target user {mac}")
    return RedirectResponse(url=f"/admin/user/{mac}", status_code=303)

@router.post("/admin/unblock")
async def admin_unblock(
    request: Request, mac: str = Form(...), authorized: bool = Depends(security.is_admin),
    admin_svc: AdminService = Depends(get_admin_service)
):
    client_ip = request.client.host
    client_mac = utils.get_mac(client_ip) or "Unknown-MAC"

    admin_svc.update_user_status(mac, "new")
    audit_log("USER_UNBLOCKED", client_ip, client_mac, f"Restored access for target user {mac}")
    return RedirectResponse(url=f"/admin/user/{mac}", status_code=303)

@router.post("/admin/delete_user")
async def admin_delete_user(
    request: Request, mac: str = Form(...), authorized: bool = Depends(security.is_admin),
    admin_svc: AdminService = Depends(get_admin_service)
):
    client_ip = request.client.host
    client_mac = utils.get_mac(client_ip) or "Unknown-MAC"

    admin_svc.delete_user(mac)
    audit_log("USER_DELETED", client_ip, client_mac, f"Deleted target user {mac} from system")
    return RedirectResponse(url="/admin", status_code=303)

@router.post("/admin/rename_device")
async def rename_device(request: Request, data: RenameRequest, authorized: bool = Depends(security.is_admin)):
    client_ip = request.client.host
    client_mac = utils.get_mac(client_ip) or "Unknown-MAC"

    if "custom_device_names" not in state.config:
        state.config["custom_device_names"] = {}
    
    state.config["custom_device_names"][data.mac] = data.name.strip()
    state.save_config()
    
    audit_log("DEVICE_RENAMED", client_ip, client_mac, f"Renamed device {data.mac} to '{data.name.strip()}'")
    return {"status": "success"}