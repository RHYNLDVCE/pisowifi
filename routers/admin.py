# routers/admin.py
import shutil
from fastapi import APIRouter, Request, Form, UploadFile, File, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
# from fastapi.templating import Jinja2Templates # <-- Removed

from core import database, state, security
from core.templates import templates # <-- NEW: Import shared instance

router = APIRouter()

# REMOVED: templates = Jinja2Templates(directory="templates")

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

@router.get("/admin", response_class=HTMLResponse)
async def admin_panel(request: Request, authorized: bool = Depends(security.is_admin)):
    total = database.get_total_sales()
    return templates.TemplateResponse("admin.html", {
        "request": request, 
        "users": state.users, 
        "total_sales": total,
        "slot_timeout": state.config["slot_timeout"]
    })

@router.post("/admin/upload_banner")
async def upload_banner(file: UploadFile = File(...), authorized: bool = Depends(security.is_admin)):
    # Note: Ensure the 'static' directory exists or is created in main.py
    with open("static/banner_custom.jpg", "wb+") as file_object:
        shutil.copyfileobj(file.file, file_object)
    return RedirectResponse(url="/admin", status_code=303)

@router.post("/admin/update_settings")
async def update_settings(timeout: int = Form(...), authorized: bool = Depends(security.is_admin)):
    state.config["slot_timeout"] = timeout
    return RedirectResponse(url="/admin", status_code=303)