import sqlite3
import os
import hashlib
from typing import Optional
from contextlib import contextmanager

def hash_password(password: str) -> str:
    salt = "hr_bookings_salt_2026"
    return hashlib.sha256((password + salt).encode()).hexdigest()

def get_db_path():
    return os.getenv("BOOKING_DB_PATH", os.getenv("BOOKINGS_DB_PATH", "booking.db"))

def init_db(db_path: Optional[str] = None):
    """Initializes SQLite database with WAL mode, foreign keys, and comprehensive booking tables."""
    target_path = db_path or get_db_path()
    conn = sqlite3.connect(target_path, timeout=20.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    cursor = conn.cursor()

    # 1. Users table (RBAC)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        full_name TEXT NOT NULL,
        role TEXT DEFAULT 'Staff', -- 'Admin', 'Staff'
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 2. Services table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS services (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        category TEXT DEFAULT 'General',
        duration_minutes INTEGER NOT NULL,
        buffer_minutes INTEGER DEFAULT 15,
        price REAL DEFAULT 0.0,
        currency TEXT DEFAULT 'GBP',
        description TEXT,
        color_token TEXT DEFAULT '#3b82f6',
        active BOOLEAN DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 3. Staff / Specialists table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS staff (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        phone TEXT,
        role TEXT DEFAULT 'Consultant',
        working_days TEXT DEFAULT '1,2,3,4,5,6', -- Mon-Sat
        start_time TEXT DEFAULT '09:00',
        end_time TEXT DEFAULT '17:00',
        break_start TEXT DEFAULT '13:00',
        break_end TEXT DEFAULT '14:00',
        color_code TEXT DEFAULT '#06b6d4',
        active BOOLEAN DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 4. Customers table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS customers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        phone TEXT,
        total_visits INTEGER DEFAULT 0,
        total_spent REAL DEFAULT 0.0,
        notes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 5. Appointments table (Collision-Proof)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS appointments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        service_id INTEGER REFERENCES services(id) ON DELETE RESTRICT,
        staff_id INTEGER REFERENCES staff(id) ON DELETE RESTRICT,
        customer_id INTEGER REFERENCES customers(id) ON DELETE CASCADE,
        booking_date DATE NOT NULL,
        start_time TEXT NOT NULL,
        end_time TEXT NOT NULL,
        buffer_end_time TEXT NOT NULL,
        status TEXT DEFAULT 'Confirmed', -- Confirmed, Completed, Cancelled, No-Show
        deposit_paid REAL DEFAULT 0.0,
        price REAL DEFAULT 0.0,
        customer_notes TEXT,
        internal_notes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Seed Admin User if empty
    cursor.execute("SELECT COUNT(*) FROM users;")
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
        INSERT INTO users (email, password_hash, full_name, role)
        VALUES (?, ?, ?, ?);
        """, ("booking.admin@demo.local", hash_password("demo123"), "Booking Coordinator", "Admin"))

    # Seed Default Services if empty (100% Generic Appointment Types)
    cursor.execute("SELECT COUNT(*) FROM services;")
    if cursor.fetchone()[0] == 0:
        services = [
            ("Initial Consultation", "Consultation", 60, 15, 150.0, "GBP", "Comprehensive initial discovery & assessment session", "#2563eb"),
            ("Standard Appointment", "Standard", 45, 15, 95.0, "GBP", "Standard professional consultation & review", "#0284c7"),
            ("Follow-up Session", "Follow-up", 30, 15, 65.0, "GBP", "Routine progress review & status check", "#10b981"),
            ("Assessment Session", "Assessment", 45, 15, 110.0, "GBP", "Technical requirements & workflow evaluation", "#f59e0b")
        ]
        cursor.executemany("""
        INSERT INTO services (name, category, duration_minutes, buffer_minutes, price, currency, description, color_token)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?);
        """, services)

    # Seed Staff if empty
    cursor.execute("SELECT COUNT(*) FROM staff;")
    if cursor.fetchone()[0] == 0:
        staff_members = [
            ("Sarah Mitchell", "sarah.mitchell@demo.local", "+44 7700 900111", "Principal Consultant", "1,2,3,4,5", "09:00", "17:00", "13:00", "14:00", "#2563eb"),
            ("James Wilson", "james.wilson@demo.local", "+44 7700 900222", "Senior Specialist", "1,2,3,4,5,6", "08:30", "17:30", "12:30", "13:30", "#0284c7"),
            ("Daniel Carter", "daniel.carter@demo.local", "+44 7700 900333", "Operations Lead", "1,2,3,4,5", "10:00", "18:00", "14:00", "15:00", "#10b981")
        ]
        cursor.executemany("""
        INSERT INTO staff (name, email, phone, role, working_days, start_time, end_time, break_start, break_end, color_code)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, staff_members)

    # Seed Customers if empty
    cursor.execute("SELECT COUNT(*) FROM customers;")
    if cursor.fetchone()[0] == 0:
        customers = [
            ("Olivia Bennett", "olivia.bennett@example.com", "+44 7700 900444", 3, 450.0, "Prefers morning appointments"),
            ("Michael Harris", "michael.harris@example.com", "+44 7700 900555", 2, 190.0, "Regular consultation client"),
            ("Emily Cooper", "emily.cooper@example.com", "+44 7700 900666", 5, 550.0, "Monthly review subscriber")
        ]
        cursor.executemany("""
        INSERT INTO customers (name, email, phone, total_visits, total_spent, notes)
        VALUES (?, ?, ?, ?, ?, ?);
        """, customers)

        # Seed Appointments
        appointments = [
            (1, 1, 1, "2026-08-29", "10:00", "11:00", "11:15", "Confirmed", 50.0, 150.0, "Initial consultation notes", "Pre-consultation briefing prepared"),
            (2, 2, 2, "2026-08-29", "14:00", "14:45", "15:00", "Confirmed", 0.0, 95.0, "Standard review appointment", None),
            (3, 3, 3, "2026-08-28", "11:00", "11:30", "11:45", "Completed", 65.0, 65.0, "Routine follow-up", "Session completed")
        ]
        cursor.executemany("""
        INSERT INTO appointments (service_id, staff_id, customer_id, booking_date, start_time, end_time, buffer_end_time, status, deposit_paid, price, customer_notes, internal_notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, appointments)

    conn.commit()
    conn.close()

@contextmanager
def get_db(db_path: Optional[str] = None):
    target_path = db_path or get_db_path()
    conn = sqlite3.connect(target_path, timeout=20.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON;")
    try:
        yield conn
    finally:
        conn.close()
