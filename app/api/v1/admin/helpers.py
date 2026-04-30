from datetime import datetime

def audit_log(action: str, ip: str, mac: str, details: str):
    """Writes professional audit logs containing administrator identity and actions."""
    try:
        with open("system.log", "a") as f:
            dt = datetime.now().strftime("%Y-%m-%d %I:%M:%S %p")
            f.write(f"[{dt}] [ADMIN_AUDIT] [{ip} | {mac}] {action}: {details}\n")
    except Exception:
        pass