import time
from fastapi import APIRouter, Depends

from core import state
from hardware import controller
from app.api.dependencies import get_session_service
from services.session_service import SessionService
from core.logger import system_log

router = APIRouter()

# --- ACTION ROUTES ---
@router.post("/connect")
async def start_internet(mac: str, session: SessionService = Depends(get_session_service)):
    return await session.connect_user(mac) 

@router.post("/pause")
def pause_internet(mac: str, session: SessionService = Depends(get_session_service)):
    return session.pause_user(mac)

# --- SLOT MANAGEMENT ---
@router.get("/enable_slot")
async def enable_slot(mac: str):
    user = state.users.get(mac, {})
    if user.get("status") == "blocked": return {"result": "blocked"}

    if controller.current_slot_user is None or controller.current_slot_user == mac:
        controller.current_slot_user = mac
        controller.turn_slot_on()
        state.config["slot_expiry_timestamp"] = time.time() + state.config.get("slot_timeout", 30)
        system_log(f"[PORTAL_EVENT] SLOT OPENED by Device: {mac}")
        
        if mac in state.manager.active_connections:
            await state.manager.send_personal_message({
                "type": "slot_opened",
                "slot_seconds": state.config.get("slot_timeout", 30),
                "balance": user.get("balance", 0),
                "points": user.get("points", 0),
                "coin_rates": state.config.get("coin_rates", "1:10,5:60,10:180,20:300"),
                "time_remaining": user.get("time", 0)
            }, mac)
        return {"result": "success"}
    return {"result": "busy"}

@router.post("/cancel_slot")
async def cancel_slot(mac: str):
    if controller.current_slot_user == mac:
        controller.turn_slot_off()
        state.config["slot_expiry_timestamp"] = 0
        return {"result": "success"}
    return {"result": "fail"}