# core/state.py

# In-memory cache of connected users
# Structure: {'mac_address': {'time': 300, 'status': 'connected'}}
users = {}

# Runtime configuration settings
config = {
    "slot_timeout": 30,         # Seconds to insert coin
    "slot_expiry_timestamp": 0  # Unix timestamp when slot closes
}