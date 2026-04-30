import time
from fastapi import APIRouter, Request, Form, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from datetime import timedelta

from core import database, security, utils
from core.templates import templates
from .helpers import audit_log

router = APIRouter()

# --- SIMPLE IN-MEMORY RATE LIMITER ---
class LoginLimiter:
    def __init__(self):
        # Stores { ip: [timestamp1, timestamp2, ...] }
        self.attempts = {}
        self.MAX_ATTEMPTS = 5
        self.WINDOW_SECONDS = 300  # 5 Minutes

    def is_blocked(self, ip: str) -> bool:
        now = time.time()
        if ip not in self.attempts:
            return False
        
        # Filter only attempts within the last 5 minutes
        self.attempts[ip] = [t for t in self.attempts[ip] if now - t < self.WINDOW_SECONDS]
        
        return len(self.attempts[ip]) >= self.MAX_ATTEMPTS

    def record_attempt(self, ip: str):
        if ip not in self.attempts:
            self.attempts[ip] = []
        self.attempts[ip].append(time.time())

limiter = LoginLimiter()

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@router.post("/auth")
async def login_action(request: Request, username: str = Form(...), password: str = Form(...)):
    client_ip = request.client.host
    client_mac = utils.get_mac(client_ip) or "Unknown-MAC"

    # 1. Check if the IP is currently rate-limited
    if limiter.is_blocked(client_ip):
        audit_log("SECURITY_ALERT", client_ip, client_mac, f"Rate limit exceeded for account '{username}'")
        return RedirectResponse(url="/login?error=Too many attempts. Try again in 5 minutes.", status_code=303)

    if database.verify_admin(username, password):
        audit_log("LOGIN_SUCCESS", client_ip, client_mac, f"Account '{username}' authenticated.")
        
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
            secure=False # Set to True if using HTTPS
        )
        # Clear attempts on successful login
        if client_ip in limiter.attempts:
            del limiter.attempts[client_ip]
            
        return response
    
    # 2. Record the failed attempt
    limiter.record_attempt(client_ip)
    
    audit_log("LOGIN_FAILED", client_ip, client_mac, f"Failed attempt for account '{username}'.")
    return RedirectResponse(url="/login?error=Invalid Credentials", status_code=303)

@router.get("/logout")
async def logout(request: Request):
    client_ip = request.client.host
    client_mac = utils.get_mac(client_ip) or "Unknown-MAC"
    audit_log("LOGOUT", client_ip, client_mac, "Administrator logged out.")

    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("admin_token")
    return response