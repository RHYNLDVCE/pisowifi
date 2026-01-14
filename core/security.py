# core/security.py
from fastapi import Request, HTTPException, Depends

def is_admin(request: Request) -> bool:
    """Dependency to protect admin routes."""
    token = request.cookies.get("admin_token")
    if token != "secret_logged_in_token":
        raise HTTPException(status_code=302, headers={"Location": "/login"})
    return True