import os
import asyncio
import subprocess
import secrets
import uvicorn
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.staticfiles import StaticFiles
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent

from core import database, state
import config
from network import firewall
from services import background
from api.v1 import portal, admin
from hardware import controller 

# 1. Disable the default, unprotected docs
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

os.makedirs("static/banners/set", exist_ok=True)
os.makedirs("static/sounds", exist_ok=True)

app.mount("/static", StaticFiles(directory="static"), name="static")

# --- SECURE DOCS SETUP ---
security_scheme = HTTPBasic()

def verify_docs_access(credentials: HTTPBasicCredentials = Depends(security_scheme)):
    """Verifies the HTTP Basic Auth credentials against your config.env"""
    correct_username = secrets.compare_digest(credentials.username, config.ADMIN_USERNAME)
    correct_password = secrets.compare_digest(credentials.password, config.ADMIN_PASSWORD)
    
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

@app.get("/docs", include_in_schema=False)
async def get_secure_documentation(username: str = Depends(verify_docs_access)):
    """The protected Swagger UI endpoint"""
    return get_swagger_ui_html(openapi_url="/openapi.json", title="PisoWifi API Docs")

@app.get("/openapi.json", include_in_schema=False)
async def get_secure_openapi(username: str = Depends(verify_docs_access)):
    """The protected OpenAPI schema that Swagger UI relies on"""
    return get_openapi(title="PisoWifi API", version="1.0.0", routes=app.routes)
# -------------------------

# Register New Clean Routes
app.include_router(admin.router)
app.include_router(portal.router)

@app.on_event("startup")
async def startup_event():
    print("Initializing System...")
    database.init_db()
    state.users = database.load_users()
    
    # Reset states
    for mac, data in state.users.items():
        if data["status"] == "connected":
            data["status"] = "paused"
            database.sync_user(mac, data)
            
    firewall.init_firewall()
    
    try:
        subprocess.run(["conntrack", "-F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except: pass

    state.loop = asyncio.get_running_loop()
    controller.setup()
    background.start_background_tasks()
    print("PisoWifi System Started Successfully!")

@app.on_event("shutdown")
def shutdown_event():
    print("System Shutting Down...")
    state.is_shutting_down = True
    
    # Force close any active portal websockets to prevent them from blocking graceful shutdown
    if hasattr(state, "manager") and hasattr(state.manager, "active_connections"):
        for mac, ws in list(state.manager.active_connections.items()):
            try: asyncio.run_coroutine_threadsafe(ws.close(), state.loop)
            except: pass

    try: controller.turn_slot_off()
    except: pass
    
    try: 
        fail_safe_path = os.path.join(ROOT_DIR, "fail_safe.sh")
        subprocess.run([fail_safe_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except: pass

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=80, reload=False, timeout_graceful_shutdown=3)