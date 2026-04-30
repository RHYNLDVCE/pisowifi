from fastapi import APIRouter

# Import the individual route files
from . import auth, dashboard, users, settings

# Create a single master router
router = APIRouter()

# Attach all the split routes to the master router
router.include_router(auth.router)
router.include_router(dashboard.router)
router.include_router(users.router)
router.include_router(settings.router)