from fastapi import APIRouter
from fastapi.responses import RedirectResponse

router = APIRouter()

# --- CAPTIVE PORTAL TRIGGERS ---
@router.get("/generate_204")
@router.get("/ncsi.txt")
@router.get("/connecttest.txt")
@router.get("/redirect")
async def captive_portal_trigger():
    return RedirectResponse("/")

# --- CATCH-ALL ---
# This ensures any random URL requested by a device forces them back to the portal
@router.get("/{full_path:path}")
async def catch_all(full_path: str):
    return RedirectResponse("/")