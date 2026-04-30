import datetime

def system_log(msg: str):
    """Helper function to log portal and slot activities."""
    try:
        with open("system.log", "a") as f:
            dt = datetime.datetime.now().strftime("%Y-%m-%d %I:%M:%S %p")
            f.write(f"[{dt}] {msg}\n")
    except: 
        pass