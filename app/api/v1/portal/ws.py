import time
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from core import state

router = APIRouter()

@router.websocket("/ws/{mac}")
async def websocket_endpoint(websocket: WebSocket, mac: str):
    await state.manager.connect(mac, websocket)
    if mac in state.users and websocket.client.host:
        state.users[mac]["ip"] = websocket.client.host
        state.users[mac]["last_active"] = time.time()
    try:
        while True:
            await websocket.receive_text()
            if mac in state.users: state.users[mac]["last_active"] = time.time()
    except WebSocketDisconnect:
        state.manager.disconnect(mac, websocket)