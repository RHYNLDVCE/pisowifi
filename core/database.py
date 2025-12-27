import sqlite3
import time
from passlib.context import CryptContext

DB_FILE = "pisowifi.db"
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # 1. Users Table
    c.execute('''CREATE TABLE IF NOT EXISTS users (
                    mac TEXT PRIMARY KEY,
                    ip TEXT,
                    time_remaining INTEGER,
                    status TEXT,
                    last_updated INTEGER
                )''')
                
    # 2. Sales Table
    c.execute('''CREATE TABLE IF NOT EXISTS sales (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    mac TEXT,
                    amount INTEGER,
                    timestamp INTEGER
                )''')

    # 3. Admins Table (NEW)
    c.execute('''CREATE TABLE IF NOT EXISTS admins (
                    username TEXT PRIMARY KEY,
                    password_hash TEXT
                )''')

    # Create Default Admin (admin / admin123) if not exists
    try:
        default_pass = pwd_context.hash("admin123")
        c.execute("INSERT INTO admins (username, password_hash) VALUES (?, ?)", 
                  ("admin", default_pass))
        print("Default admin created: admin / admin123")
    except sqlite3.IntegrityError:
        pass # Admin already exists

    conn.commit()
    conn.close()

# --- AUTH FUNCTIONS ---
def verify_admin(username, plain_password):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT password_hash FROM admins WHERE username=?", (username,))
    row = c.fetchone()
    conn.close()
    
    if row and pwd_context.verify(plain_password, row[0]):
        return True
    return False

# --- USER FUNCTIONS (Same as before) ---
def load_users():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT mac, ip, time_remaining, status FROM users")
    rows = c.fetchall()
    conn.close()
    users_dict = {}
    for row in rows:
        if row[2] > 0:
            users_dict[row[0]] = {"ip": row[1], "time": row[2], "status": "disconnected"}
    return users_dict

def sync_user(mac, data):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO users (mac, ip, time_remaining, status, last_updated) VALUES (?, ?, ?, ?, ?)", 
                 (mac, data.get("ip", ""), data["time"], data["status"], int(time.time())))
    conn.commit()
    conn.close()

def add_sale(mac, amount):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO sales (mac, amount, timestamp) VALUES (?, ?, ?)", (mac, amount, int(time.time())))
    conn.commit()
    conn.close()

def get_total_sales():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT SUM(amount) FROM sales")
    total = c.fetchone()[0]
    conn.close()
    return total if total else 0