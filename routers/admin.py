# routers/admin.py
import shutil
from fastapi import APIRouter, Request, Form, UploadFile, File, Depends
from fastapi.responses import HTMLResponse, RedirectResponse

from core import database, state, security
from core.templates import templates
from network import firewall

router = APIRouter()

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

@router.get("/admin", response_class=HTMLResponse)
async def admin_panel(request: Request, authorized: bool = Depends(security.is_admin)):
    total = database.get_total_sales()
    return templates.TemplateResponse("admin.html", {
        "request": request, 
        "users": state.users, 
        "total_sales": total,
        "slot_timeout": state.config.get("slot_timeout", 30),
        "inactive_timeout": state.config.get("inactive_timeout", 60),
        "auto_pause_enabled": state.config.get("auto_pause_enabled", True),
        "speed_limit_enabled": state.config.get("speed_limit_enabled", False),
        "global_speed_limit": state.config.get("global_speed_limit", 5)
    })

@router.post("/admin/upload_banner")
async def upload_banner(file: UploadFile = File(...), authorized: bool = Depends(security.is_admin)):
    with open("static/banner_custom.jpg", "wb+") as file_object:
        shutil.copyfileobj(file.file, file_object)
    return RedirectResponse(url="/admin", status_code=303)

@router.post("/admin/update_settings")
async def update_settings(
    timeout: int = Form(...), 
    inactive_timeout: int = Form(...), 
    auto_pause: str = Form(None),
    speed_limit_val: int = Form(...),
    speed_limit_toggle: str = Form(None),
    authorized: bool = Depends(security.is_admin)
):
    # Update Memory
    state.config["slot_timeout"] = timeout
    state.config["inactive_timeout"] = inactive_timeout
    state.config["auto_pause_enabled"] = (auto_pause == "on")
    state.config["global_speed_limit"] = speed_limit_val
    state.config["speed_limit_enabled"] = (speed_limit_toggle == "on")
    
    # SAVE TO FILE (The Fix)
    state.save_config()
    
    return RedirectResponse(url="/admin", status_code=303)

# --- USER CONTROL BUTTONS ---

@router.post("/admin/add_time")
async def admin_add_time(mac: str = Form(...), authorized: bool = Depends(security.is_admin)):
    if mac in state.users:
        state.users[mac]["time"] += 300 # Add 5 mins
        database.sync_user(mac, state.users[mac])
    return RedirectResponse(url="/admin", status_code=303)

@router.post("/admin/block")
async def admin_block(mac: str = Form(...), authorized: bool = Depends(security.is_admin)):
    if mac in state.users:
        state.users[mac]["status"] = "blocked"
        state.users[mac]["time"] = 0
        firewall.block_user(mac)
        database.sync_user(mac, state.users[mac])
    return RedirectResponse(url="/admin", status_code=303)