# core/database.py
import sqlite3
import time
from passlib.context import CryptContext

DB_FILE = "pisowifi.db"
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # 1. Users Table (Updated with 'points')
    c.execute('''CREATE TABLE IF NOT EXISTS users (
                    mac TEXT PRIMARY KEY,
                    ip TEXT,
                    time_remaining INTEGER,
                    status TEXT,
                    last_updated INTEGER,
                    balance INTEGER DEFAULT 0,
                    free_claimed INTEGER DEFAULT 0,
                    points REAL DEFAULT 0
                )''')
    
    # --- MIGRATIONS (Run safely if columns exist) ---
    try:
        c.execute("ALTER TABLE users ADD COLUMN balance INTEGER DEFAULT 0")
    except:
        pass 

    try:
        c.execute("ALTER TABLE users ADD COLUMN free_claimed INTEGER DEFAULT 0")
    except:
        pass

    # --- NEW: MIGRATION FOR POINTS ---
    try:
        c.execute("ALTER TABLE users ADD COLUMN points REAL DEFAULT 0")
    except:
        pass

    # 2. Sales Table
    c.execute('''CREATE TABLE IF NOT EXISTS sales (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    mac TEXT,
                    amount INTEGER,
                    timestamp INTEGER
                )''')

    # 3. Admins Table
    c.execute('''CREATE TABLE IF NOT EXISTS admins (
                    username TEXT PRIMARY KEY,
                    password_hash TEXT
                )''')

    # Create Default Admin
    try:
        default_pass = pwd_context.hash("reyespisowifiadmin")
        c.execute("INSERT INTO admins (username, password_hash) VALUES (?, ?)", 
                  ("admin", default_pass))
    except sqlite3.IntegrityError:
        pass 

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

# --- USER FUNCTIONS ---
def load_users():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # Updated Query to include 'points'
    c.execute("SELECT mac, ip, time_remaining, status, balance, free_claimed, points FROM users")
    rows = c.fetchall()
    conn.close()
    
    users_dict = {}
    for row in rows:
        # Handle potential NULLs or missing columns from old DB versions
        balance = row[4] if len(row) > 4 and row[4] is not None else 0
        claimed = row[5] if len(row) > 5 and row[5] is not None else 0
        points = row[6] if len(row) > 6 and row[6] is not None else 0
        
        users_dict[row[0]] = {
            "ip": row[1], 
            "time": row[2], 
            "status": row[3],
            "balance": balance,
            "free_claimed": claimed,
            "points": points  # <--- Load Points
        }
    return users_dict

def sync_user(mac, data):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # Updated Query to save 'points'
    c.execute("INSERT OR REPLACE INTO users (mac, ip, time_remaining, status, last_updated, balance, free_claimed, points) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", 
                 (mac, 
                  data.get("ip", ""), 
                  data["time"], 
                  data["status"], 
                  int(time.time()), 
                  data.get("balance", 0), 
                  data.get("free_claimed", 0), 
                  data.get("points", 0)  # <--- Save Points
                 ))
    conn.commit()
    conn.close()

def delete_user(mac):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM users WHERE mac=?", (mac,))
    conn.commit()
    conn.close()

# --- RESET FREE CLAIMS ---
def reset_all_free_claimed():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE users SET free_claimed = 0")
    conn.commit()
    conn.close()

# --- SALES FUNCTIONS ---
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

def get_sales_since(timestamp_start):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT SUM(amount) FROM sales WHERE timestamp >= ?", (timestamp_start,))
    total = c.fetchone()[0]
    conn.close()
    return total if total else 0