import logging
import sys
from logging.handlers import RotatingFileHandler

# Configure a SINGLE global system logger
logger = logging.getLogger("PisoWifi")
logger.setLevel(logging.INFO)

# Prevent duplicate logs and file-lock crashes
if not logger.handlers:
    file_handler = RotatingFileHandler(
        "system.log", 
        maxBytes=5 * 1024 * 1024, # 5MB
        backupCount=3
    )
    console_handler = logging.StreamHandler(sys.stdout)
    
    # Universal format (we will inject the specific tags in the functions)
    log_formatter = logging.Formatter(
        "[{asctime}] {message}", 
        datefmt="%Y-%m-%d %I:%M:%S %p",
        style="{"
    )
    
    file_handler.setFormatter(log_formatter)
    console_handler.setFormatter(log_formatter)
    
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

def system_log(msg: str):
    """Helper function to safely log portal, slot, and coin activities."""
    try:
        logger.info(msg)
    except Exception:
        pass

def audit_log(action: str, ip: str, mac: str, details: str):
    """Helper function to safely log Administrator activities."""
    try:
        # Formats exactly how the Admin UI expects it
        logger.info(f"[ADMIN_AUDIT] [{ip} | {mac}] {action}: {details}")
    except Exception:
        pass