from dotenv import load_dotenv
import os
# Configuration Settings
LAN_INTERFACE = "br0" # for LAN or the USB adapter
WAN_INTERFACE = "eth0" #for WAN
COIN_PIN_WPI = "3"        # Coin Signal
RELAY_PINS = ["5"]   # Light/Power
PULSE_VALUE = 1          # 1 Credits per Pulse

load_dotenv()

# --- SECURITY SECRETS ---
# If .env is missing, it falls back to 'unsafe_default' (warns you)
SECRET_KEY = os.getenv("SECRET_KEY")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
