import time
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from core import database, state, utils
from core.templates import templates
from network import firewall
from hardware import controller
from services import background

router = APIRouter()

@router.post("/claim_free_time")
def claim_free_time(mac: str):
    if not state.config.get("free_time_enabled", False): return {"result": "disabled"}
    user = state.users.get(mac)
    if not user: return {"result": "error"} 
    if user.get("free_claimed", 0) == 1: return {"result": "already_claimed"}

    duration = state.config.get("free_time_duration", 5) 
    user["time"] += (duration * 60)
    user["free_claimed"] = 1
    user["status"] = "connected"
    user["last_active"] = time.time()
    firewall.allow_user(mac, user.get("ip"))
    
    if controller.current_slot_user == mac: controller.turn_slot_off()
    database.sync_user(mac, user)
    
    if mac in state.manager.active_connections:
        background.send_ws_update(mac, {
            "type": "sync", "status": "connected", "time_remaining": user["time"],
            "balance": 0, "points": user.get("points", 0) 
        })
    return {"result": "success"}

@router.get("/rewards", response_class=HTMLResponse)
async def rewards_page(request: Request):
    client_ip = request.client.host
    mac = utils.get_mac(client_ip)
    if mac and mac not in state.users:
        state.users[mac] = {"time": 0, "status": "new", "balance": 0, "points": 0}
        
    user = state.users.get(mac, {})
    return templates.TemplateResponse("rewards.html", {
        "request": request, "mac": mac, "points": user.get("points", 0),
        "promos": state.config.get("point_promos", []),
        "enabled": state.config.get("points_enabled", False),
        "banner_text": state.config.get("banner_text", ""),
        "banner_link": state.config.get("banner_link", "")
    })

@router.post("/redeem_points")
def redeem_points(data: dict, request: Request): 
    promo_id = data.get("promo_id")
    mac = utils.get_mac(request.client.host)
    if not mac or mac not in state.users: return {"status": "error", "message": "User not found"}
    if not state.config.get("points_enabled", False): return {"status": "error", "message": "Rewards disabled."}

    user = state.users[mac]
    target_promo = next((p for p in state.config.get("point_promos", []) if p["id"] == promo_id), None)
    
    if not target_promo: return {"status": "error", "message": "Invalid Promo"}
    if user.get("points", 0) < target_promo["cost"]: return {"status": "error", "message": "Not enough points"}
        
    user["points"] = round(user["points"] - target_promo["cost"], 2)
    user["time"] += target_promo["minutes"] * 60
    user["status"] = "connected"
    user["last_active"] = time.time()
    
    firewall.allow_user(mac, user.get("ip"))
    database.sync_user(mac, user)
    
    if mac in state.manager.active_connections:
        background.send_ws_update(mac, {
            "type": "sync", "status": "connected",
            "time_remaining": user["time"], "points": user["points"]
        })
    return {"status": "success", "message": f"Successfully redeemed: {target_promo['name']}"}