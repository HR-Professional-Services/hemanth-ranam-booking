import os
import sys
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.database import get_db, init_db

def seed():
    init_db()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM appointments")
        cursor.execute("DELETE FROM customers")
        cursor.execute("DELETE FROM staff")
        cursor.execute("DELETE FROM services")

        # Services
        services = [
            ("Business Systems Strategic Audit", "Consulting", 60, 15, 350.0, "USD", "1-on-1 operational bottleneck analysis and automation architecture roadmap."),
            ("Frappe & ERPNext Technical Scoping", "Engineering", 90, 15, 500.0, "USD", "Deep-dive ERP workflow requirements, custom DocTypes, and migration plan."),
            ("Trading Algorithm & EA Strategy Review", "Trading Tech", 45, 10, 250.0, "USD", "PineScript and MT5 Expert Advisor logic review and backtest validation.")
        ]
        s_ids = []
        for s in services:
            cursor.execute("""
            INSERT INTO services (name, category, duration_minutes, buffer_minutes, price, currency, description)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """, s)
            s_ids.append(cursor.lastrowid)

        # Staff
        staff = [
            ("Alexander Ross", "alexander.r@hr-services.local", "+44 20 7946 0991", "Principal Systems Architect", "1,2,3,4,5", "09:00", "18:00"),
            ("Sarah Jenkins", "sarah.j@hr-services.local", "+44 20 7946 0192", "Senior Automation Specialist", "1,2,3,4,5", "10:00", "17:00")
        ]
        st_ids = []
        for st in staff:
            cursor.execute("""
            INSERT INTO staff (name, email, phone, role, working_days, start_time, end_time)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """, st)
            st_ids.append(cursor.lastrowid)

        # Customers
        customers = [
            ("David Miller", "david.m@apexgroup.com", "+44 7700 900888", "Logistics firm CEO seeking CRM migration."),
            ("Elena Rostova", "elena@vanguardcapital.ch", "+41 22 700 1234", "Quantitative trader requesting custom MT5 EA.")
        ]
        c_ids = []
        for c in customers:
            cursor.execute("INSERT INTO customers (name, email, phone, notes) VALUES (?, ?, ?, ?)", c)
            c_ids.append(cursor.lastrowid)

        # Sample future appointments
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        cursor.execute("""
        INSERT INTO appointments (service_id, staff_id, customer_id, booking_date, start_time, end_time, status, customer_notes)
        VALUES (?, ?, ?, ?, '10:00', '11:00', 'Confirmed', 'Discuss enterprise pipeline automation.')
        """, (s_ids[0], st_ids[0], c_ids[0], tomorrow))

        cursor.execute("""
        INSERT INTO appointments (service_id, staff_id, customer_id, booking_date, start_time, end_time, status, customer_notes)
        VALUES (?, ?, ?, ?, '14:00', '14:45', 'Confirmed', 'Review SMC indicators and alert webhooks.')
        """, (s_ids[2], st_ids[0], c_ids[1], tomorrow))

        conn.commit()
    print("✅ HR Bookings demo dataset seeded successfully!")

if __name__ == "__main__":
    seed()
