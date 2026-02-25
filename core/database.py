# pisowifi/core/database.py
import sqlite3
import time
from passlib.context import CryptContext
import config

DB_FILE = "pisowifi.db"
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

# --- HELPER: CONNECTION FACTORY ---
def get_connection():
    """
    Creates a database connection with a 30-second timeout.
    This prevents immediate failures when the DB is busy.
    """
    return sqlite3.connect(DB_FILE, timeout=30)

def init_db():
    # Use context manager to ensure connection closes even if errors occur
    with get_connection() as conn:
        c = conn.cursor()
        
        # --- ENABLE WAL MODE (Crucial for Concurrency) ---
        # Allows readers and writers to exist simultaneously
        try:
            c.execute("PRAGMA journal_mode=WAL")
        except Exception as e:
            print(f"Error enabling WAL: {e}")
        
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

        # --- CREATE DEFAULT ADMIN SECURELY ---
        try:
            # Get credentials from config.py (which loads .env)
            admin_user = config.ADMIN_USERNAME
            admin_pass = config.ADMIN_PASSWORD
            
            # Hash the password from .env
            password_hash = pwd_context.hash(admin_pass)

            c.execute("INSERT INTO admins (username, password_hash) VALUES (?, ?)", 
                      (admin_user, password_hash))
            print(f"✅ Default Admin created: {admin_user}")
        except sqlite3.IntegrityError:
            # Admin already exists, skip
            pass 
        
        # Explicit commit to ensure table creation
        conn.commit()

# --- AUTH FUNCTIONS ---
def verify_admin(username, plain_password):
    try:
        with get_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT password_hash FROM admins WHERE username=?", (username,))
            row = c.fetchone()
        
        if row and pwd_context.verify(plain_password, row[0]):
            return True
        return False
    except Exception as e:
        print(f"DB Error (verify_admin): {e}")
        return False

# --- USER FUNCTIONS ---
def load_users():
    users_dict = {}
    try:
        with get_connection() as conn:
            c = conn.cursor()
            # Updated Query to include 'points'
            c.execute("SELECT mac, ip, time_remaining, status, balance, free_claimed, points FROM users")
            rows = c.fetchall()
        
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
    except Exception as e:
        print(f"DB Error (load_users): {e}")
        
    return users_dict

def sync_user(mac, data):
    try:
        with get_connection() as conn:
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
    except Exception as e:
        print(f"DB Error (sync_user): {e}")

def delete_user(mac):
    try:
        with get_connection() as conn:
            c = conn.cursor()
            c.execute("DELETE FROM users WHERE mac=?", (mac,))
            conn.commit()
    except Exception as e:
        print(f"DB Error (delete_user): {e}")

# --- RESET FREE CLAIMS ---
def reset_all_free_claimed():
    try:
        with get_connection() as conn:
            c = conn.cursor()
            c.execute("UPDATE users SET free_claimed = 0")
            conn.commit()
    except Exception as e:
        print(f"DB Error (reset_all_free_claimed): {e}")

# --- SALES FUNCTIONS ---
def add_sale(mac, amount):
    try:
        with get_connection() as conn:
            c = conn.cursor()
            c.execute("INSERT INTO sales (mac, amount, timestamp) VALUES (?, ?, ?)", (mac, amount, int(time.time())))
            conn.commit()
    except Exception as e:
        print(f"DB Error (add_sale): {e}")

def get_total_sales():
    try:
        with get_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT SUM(amount) FROM sales")
            total = c.fetchone()[0]
        return total if total else 0
    except Exception as e:
        print(f"DB Error (get_total_sales): {e}")
        return 0

def get_sales_since(timestamp_start):
    try:
        with get_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT SUM(amount) FROM sales WHERE timestamp >= ?", (timestamp_start,))
            total = c.fetchone()[0]
        return total if total else 0
    except Exception as e:
        print(f"DB Error (get_sales_since): {e}")
        return 0

def get_sales_range(start_ts, end_ts):
    try:
        with get_connection() as conn:
            c = conn.cursor()
            # Fetch sum of amounts where timestamp is between start (inclusive) and end (exclusive)
            c.execute("SELECT SUM(amount) FROM sales WHERE timestamp >= ? AND timestamp < ?", (start_ts, end_ts))
            total = c.fetchone()[0]
        return total if total else 0
    except Exception as e:
        print(f"DB Error (get_sales_range): {e}")
        return 0