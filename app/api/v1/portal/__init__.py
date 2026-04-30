from fastapi import APIRouter

# Import the individual route files
from . import dashboard, session, rewards, ws, captive

# Create a single master router
router = APIRouter()

# Attach all the split routes to the master router
# CRITICAL: `captive` is loaded last because it contains the /{full_path:path} catch-all!
router.include_router(dashboard.router)
router.include_router(session.router)
router.include_router(rewards.router)
router.include_router(ws.router)
router.include_router(captive.router)