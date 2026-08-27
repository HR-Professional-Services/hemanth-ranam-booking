import sqlite3
import os
from contextlib import contextmanager

DB_PATH = os.getenv("BOOKING_DB_PATH", os.getenv("BOOKINGS_DB_PATH", "booking.db"))

def init_db(db_path: str = DB_PATH):
    """Initializes SQLite database with WAL mode and booking tables."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    cursor = conn.cursor()

    # Services table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS services (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        category TEXT DEFAULT 'General',
        duration_minutes INTEGER NOT NULL,
        buffer_minutes INTEGER DEFAULT 0,
        price REAL DEFAULT 0.0,
        currency TEXT DEFAULT 'USD',
        description TEXT,
        active BOOLEAN DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Staff / Providers table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS staff (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        phone TEXT,
        role TEXT DEFAULT 'Specialist',
        working_days TEXT DEFAULT '1,2,3,4,5', -- Monday to Friday
        start_time TEXT DEFAULT '09:00',
        end_time TEXT DEFAULT '17:00',
        active BOOLEAN DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Customers table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS customers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT NOT NULL,
        phone TEXT,
        notes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Appointments / Bookings table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS appointments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        service_id INTEGER REFERENCES services(id) ON DELETE RESTRICT,
        staff_id INTEGER REFERENCES staff(id) ON DELETE RESTRICT,
        customer_id INTEGER REFERENCES customers(id) ON DELETE CASCADE,
        booking_date DATE NOT NULL,
        start_time TEXT NOT NULL,
        end_time TEXT NOT NULL,
        status TEXT DEFAULT 'Confirmed', -- Confirmed, Completed, Cancelled, Rescheduled
        deposit_paid REAL DEFAULT 0.0,
        customer_notes TEXT,
        internal_notes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    conn.commit()
    conn.close()

@contextmanager
def get_db(db_path: str = DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON;")
    try:
        yield conn
    finally:
        conn.close()
