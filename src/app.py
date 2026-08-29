import os
import json
import csv
import io
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, Response, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional, List
from src.database import init_db, get_db, get_db_path, hash_password

app = FastAPI(title="HR Bookings", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BRANDING_FILE = os.path.join(os.path.dirname(__file__), "branding.json")

def load_branding():
    if os.path.exists(BRANDING_FILE):
        with open(BRANDING_FILE, "r") as f:
            return json.load(f)
    return {
        "brand_name": "HR Services",
        "product_name": "HR Bookings",
        "primary_color": "#2563eb",
        "bg_canvas": "#ffffff",
        "bg_secondary": "#f8fafc",
        "text_primary": "#0f172a",
        "text_muted": "#64748b"
    }

@app.on_event("startup")
def startup_event():
    init_db()

# --- Pydantic Data Models ---
class ServiceCreate(BaseModel):
    name: str
    category: Optional[str] = "General"
    duration_minutes: int
    buffer_minutes: Optional[int] = 15
    price: float
    currency: Optional[str] = "GBP"
    description: Optional[str] = ""
    color_token: Optional[str] = "#3b82f6"

class StaffCreate(BaseModel):
    name: str
    email: str
    phone: Optional[str] = ""
    role: Optional[str] = "Specialist"
    working_days: Optional[str] = "1,2,3,4,5"
    start_time: Optional[str] = "09:00"
    end_time: Optional[str] = "17:00"
    break_start: Optional[str] = "13:00"
    break_end: Optional[str] = "14:00"
    color_code: Optional[str] = "#06b6d4"

class BookingCreate(BaseModel):
    service_id: int
    staff_id: int
    customer_name: str
    customer_email: str
    customer_phone: Optional[str] = ""
    booking_date: str # YYYY-MM-DD
    start_time: str   # HH:MM
    customer_notes: Optional[str] = ""

class BookingStatusUpdate(BaseModel):
    status: str # Confirmed, Completed, Cancelled, No-Show

# --- API Endpoints ---
@app.get("/api/health")
def health():
    return {"status": "healthy", "service": "HR Bookings", "version": "2.0.0", "database": "SQLite WAL"}

@app.get("/api/branding")
def get_branding():
    return load_branding()

@app.get("/api/dashboard/stats")
def dashboard_stats():
    with get_db() as conn:
        today = datetime.now().strftime("%Y-%m-%d")
        today_count = conn.execute("SELECT COUNT(*) FROM appointments WHERE booking_date = ? AND status != 'Cancelled'", (today,)).fetchone()[0]
        total_upcoming = conn.execute("SELECT COUNT(*) FROM appointments WHERE booking_date >= ? AND status = 'Confirmed'", (today,)).fetchone()[0]
        total_completed = conn.execute("SELECT COUNT(*) FROM appointments WHERE status = 'Completed'").fetchone()[0]
        total_revenue = conn.execute("SELECT COALESCE(SUM(price), 0) FROM appointments WHERE status IN ('Confirmed', 'Completed')").fetchone()[0]
        
        staff_stats = conn.execute("""
        SELECT s.name, s.role, s.color_code, COUNT(a.id) as booking_count, COALESCE(SUM(a.price), 0) as staff_revenue
        FROM staff s
        LEFT JOIN appointments a ON s.id = a.staff_id AND a.status != 'Cancelled'
        GROUP BY s.id ORDER BY booking_count DESC
        """).fetchall()

        service_stats = conn.execute("""
        SELECT s.name, s.category, s.price, COUNT(a.id) as count
        FROM services s
        LEFT JOIN appointments a ON s.id = a.service_id AND a.status != 'Cancelled'
        GROUP BY s.id ORDER BY count DESC
        """).fetchall()

        return {
            "today_bookings": today_count,
            "upcoming_appointments": total_upcoming,
            "completed_appointments": total_completed,
            "total_revenue": total_revenue,
            "staff_breakdown": [dict(r) for r in staff_stats],
            "popular_services": [dict(r) for r in service_stats]
        }

@app.get("/api/services")
def list_services():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM services WHERE active = 1 ORDER BY category, name").fetchall()
        return [dict(r) for r in rows]

@app.post("/api/services", status_code=201)
def create_service(payload: ServiceCreate):
    with get_db() as conn:
        cur = conn.execute("""
        INSERT INTO services (name, category, duration_minutes, buffer_minutes, price, currency, description, color_token)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (payload.name, payload.category, payload.duration_minutes, payload.buffer_minutes, payload.price,
              payload.currency, payload.description, payload.color_token))
        conn.commit()
        return {"id": cur.lastrowid, "message": "Service created successfully"}

@app.get("/api/staff")
def list_staff():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM staff WHERE active = 1 ORDER BY name").fetchall()
        return [dict(r) for r in rows]

@app.post("/api/staff", status_code=201)
def create_staff(payload: StaffCreate):
    with get_db() as conn:
        cur = conn.execute("""
        INSERT INTO staff (name, email, phone, role, working_days, start_time, end_time, break_start, break_end, color_code)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (payload.name, payload.email, payload.phone, payload.role, payload.working_days, payload.start_time,
              payload.end_time, payload.break_start, payload.break_end, payload.color_code))
        conn.commit()
        return {"id": cur.lastrowid, "message": "Staff member created successfully"}

# --- Dynamic Availability Calculation (Collision Prevention) ---
@app.get("/api/availability")
def get_availability(service_id: int, staff_id: int, date: str):
    """Calculates all collision-free time slots for a given staff member, date, and service duration + buffer."""
    with get_db() as conn:
        staff_row = conn.execute("SELECT * FROM staff WHERE id = ?", (staff_id,)).fetchone()
        service_row = conn.execute("SELECT * FROM services WHERE id = ?", (service_id,)).fetchone()
        if not staff_row or not service_row:
            raise HTTPException(status_code=404, detail="Staff or Service not found")

        # Parse Day of Week (Monday=1, Sunday=7)
        try:
            dt = datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

        dow = str(dt.isoweekday())
        working_days = staff_row["working_days"].split(",")
        if dow not in working_days:
            return {"date": date, "available_slots": [], "reason": "Staff not working on this day"}

        # Generate standard time slots (e.g. 09:00 to 17:00 in 15m or 30m steps)
        fmt = "%H:%M"
        work_start = datetime.strptime(staff_row["start_time"], fmt)
        work_end = datetime.strptime(staff_row["end_time"], fmt)
        break_start = datetime.strptime(staff_row["break_start"], fmt)
        break_end = datetime.strptime(staff_row["break_end"], fmt)

        duration = service_row["duration_minutes"]
        buffer_time = service_row["buffer_minutes"]
        total_block = duration + buffer_time

        # Existing active bookings on that date for this staff
        existing = conn.execute("""
        SELECT start_time, buffer_end_time FROM appointments
        WHERE staff_id = ? AND booking_date = ? AND status != 'Cancelled'
        """, (staff_id, date)).fetchall()

        busy_intervals = []
        for e in existing:
            s_t = datetime.strptime(e["start_time"], fmt)
            e_t = datetime.strptime(e["buffer_end_time"], fmt)
            busy_intervals.append((s_t, e_t))

        # Add lunch break to busy intervals
        busy_intervals.append((break_start, break_end))

        available_slots = []
        curr = work_start
        step = timedelta(minutes=15)

        while curr + timedelta(minutes=duration) <= work_end:
            slot_start = curr
            slot_end = curr + timedelta(minutes=duration)
            slot_buffered_end = curr + timedelta(minutes=total_block)

            # Check overlap with any busy interval
            collision = False
            for (b_start, b_end) in busy_intervals:
                # If slot starts before busy ends and slot buffer ends after busy starts -> COLLISION
                if slot_start < b_end and slot_buffered_end > b_start:
                    collision = True
                    break

            if not collision:
                available_slots.append(slot_start.strftime("%H:%M"))

            curr += step

        return {
            "date": date,
            "service": service_row["name"],
            "duration_minutes": duration,
            "buffer_minutes": buffer_time,
            "available_slots": available_slots
        }

# --- Bookings Management ---
@app.get("/api/bookings")
def list_bookings(date: Optional[str] = None, staff_id: Optional[int] = None, status: Optional[str] = None):
    with get_db() as conn:
        query = """
        SELECT a.*, 
               s.name as service_name, s.duration_minutes, s.price as service_price, s.color_token as service_color,
               st.name as staff_name, st.role as staff_role, st.color_code as staff_color,
               c.name as customer_name, c.email as customer_email, c.phone as customer_phone
        FROM appointments a
        JOIN services s ON a.service_id = s.id
        JOIN staff st ON a.staff_id = st.id
        JOIN customers c ON a.customer_id = c.id
        WHERE 1=1
        """
        params = []
        if date:
            query += " AND a.booking_date = ?"
            params.append(date)
        if staff_id:
            query += " AND a.staff_id = ?"
            params.append(staff_id)
        if status:
            query += " AND a.status = ?"
            params.append(status)
        query += " ORDER BY a.booking_date ASC, a.start_time ASC"
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

@app.post("/api/bookings", status_code=201)
def create_booking(payload: BookingCreate):
    with get_db() as conn:
        # 1. Fetch Service & Staff
        service = conn.execute("SELECT * FROM services WHERE id = ?", (payload.service_id,)).fetchone()
        staff = conn.execute("SELECT * FROM staff WHERE id = ?", (payload.staff_id,)).fetchone()
        if not service or not staff:
            raise HTTPException(status_code=404, detail="Service or Staff not found")

        # 2. Calculate end_time and buffer_end_time
        fmt = "%H:%M"
        try:
            start_dt = datetime.strptime(payload.start_time, fmt)
            end_dt = start_dt + timedelta(minutes=service["duration_minutes"])
            buffer_end_dt = start_dt + timedelta(minutes=service["duration_minutes"] + service["buffer_minutes"])
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid start_time format (HH:MM required)")

        end_str = end_dt.strftime(fmt)
        buffer_end_str = buffer_end_dt.strftime(fmt)

        # 3. Collision Prevention Check
        overlapping = conn.execute("""
        SELECT id FROM appointments
        WHERE staff_id = ? AND booking_date = ? AND status != 'Cancelled'
        AND (
            (start_time < ? AND buffer_end_time > ?)
        )
        """, (payload.staff_id, payload.booking_date, buffer_end_str, payload.start_time)).fetchall()

        if overlapping:
            raise HTTPException(status_code=409, detail="Collision Conflict: Selected specialist is already booked during this time/buffer window.")

        # 4. Find or Create Customer
        cust = conn.execute("SELECT id, total_visits, total_spent FROM customers WHERE email = ?", (payload.customer_email,)).fetchone()
        if cust:
            cust_id = cust["id"]
            conn.execute("UPDATE customers SET total_visits = total_visits + 1, total_spent = total_spent + ? WHERE id = ?",
                         (service["price"], cust_id))
        else:
            cur_c = conn.execute("INSERT INTO customers (name, email, phone, total_visits, total_spent) VALUES (?, ?, ?, 1, ?)",
                                 (payload.customer_name, payload.customer_email, payload.customer_phone, service["price"]))
            cust_id = cur_c.lastrowid

        # 5. Insert Appointment
        cur_a = conn.execute("""
        INSERT INTO appointments (service_id, staff_id, customer_id, booking_date, start_time, end_time, buffer_end_time, status, price, customer_notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'Confirmed', ?, ?)
        """, (payload.service_id, payload.staff_id, cust_id, payload.booking_date, payload.start_time, end_str, buffer_end_str, service["price"], payload.customer_notes))
        
        conn.commit()
        return {
            "id": cur_a.lastrowid,
            "status": "Confirmed",
            "date": payload.booking_date,
            "start_time": payload.start_time,
            "end_time": end_str,
            "service": service["name"],
            "staff": staff["name"],
            "price": service["price"]
        }

@app.patch("/api/bookings/{booking_id}/status")
@app.patch("/api/appointments/{booking_id}/cancel")
def update_booking_status(booking_id: int, payload: Optional[BookingStatusUpdate] = None):
    new_status = payload.status if payload else "Cancelled"
    with get_db() as conn:
        conn.execute("UPDATE appointments SET status = ? WHERE id = ?", (new_status, booking_id))
        conn.commit()
        return {"status": "updated", "id": booking_id, "new_status": new_status}

@app.get("/api/customers")
def list_customers():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM customers ORDER BY total_spent DESC").fetchall()
        return [dict(r) for r in rows]

# --- Export Endpoints ---
@app.get("/api/export/csv")
def export_csv():
    with get_db() as conn:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Booking ID", "Date", "Start Time", "End Time", "Service", "Staff", "Customer", "Email", "Price (GBP)", "Status"])
        rows = conn.execute("""
        SELECT a.id, a.booking_date, a.start_time, a.end_time, s.name, st.name, c.name, c.email, a.price, a.status
        FROM appointments a
        JOIN services s ON a.service_id = s.id
        JOIN staff st ON a.staff_id = st.id
        JOIN customers c ON a.customer_id = c.id
        ORDER BY a.booking_date DESC
        """).fetchall()
        for r in rows:
            writer.writerow(list(r))
        return Response(content=output.getvalue(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=hr_bookings.csv"})

@app.get("/api/export/json")
def export_json():
    with get_db() as conn:
        appointments = [dict(r) for r in conn.execute("SELECT * FROM appointments").fetchall()]
        services = [dict(r) for r in conn.execute("SELECT * FROM services").fetchall()]
        staff = [dict(r) for r in conn.execute("SELECT * FROM staff").fetchall()]
        customers = [dict(r) for r in conn.execute("SELECT * FROM customers").fetchall()]
        return {"export_timestamp": "2026-08-28T00:00:00Z", "appointments": appointments, "services": services, "staff": staff, "customers": customers}

# --- Public Booking Portal UI ---
@app.get("/book", response_class=HTMLResponse)
def public_booking_portal():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Book an Appointment — HR Services</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@500;600;700&display=swap" rel="stylesheet">
  <style>
    :root {
      --hr-primary: #2563eb;
      --hr-primary-hover: #1d4ed8;
      --hr-primary-light: #eff6ff;
      --hr-primary-border: #bfdbfe;
      --hr-bg: #f8fafc;
      --hr-surface: #ffffff;
      --hr-surface-elevated: #f1f5f9;
      --hr-text: #0f172a;
      --hr-text-secondary: #475569;
      --hr-muted: #64748b;
      --hr-border: #e2e8f0;
      --hr-success: #16a34a;
      --hr-success-bg: #f0fdf4;
      --hr-success-border: #bbf7d0;
      --hr-warning: #d97706;
      --hr-danger: #dc2626;
      --hr-radius: 12px;
      --hr-shadow-sm: 0 1px 2px 0 rgba(0, 0, 0, 0.05);
      --hr-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.06), 0 2px 4px -2px rgba(0, 0, 0, 0.04);
      --hr-shadow-lg: 0 10px 15px -3px rgba(0, 0, 0, 0.08), 0 4px 6px -4px rgba(0, 0, 0, 0.04);
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background-color: var(--hr-bg);
      color: var(--hr-text);
      font-family: 'Inter', system-ui, -apple-system, sans-serif;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      -webkit-font-smoothing: antialiased;
    }
    
    /* Header */
    .public-header {
      background: var(--hr-surface);
      border-bottom: 1px solid var(--hr-border);
      padding: 16px 24px;
      position: sticky;
      top: 0;
      z-index: 50;
      box-shadow: var(--hr-shadow-sm);
    }
    .header-container {
      max-width: 1140px;
      margin: 0 auto;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    .brand-logo-wrap {
      display: flex;
      align-items: center;
      gap: 12px;
      text-decoration: none;
    }
    .brand-logo-badge {
      width: 40px;
      height: 40px;
      background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%);
      border-radius: 10px;
      display: flex;
      align-items: center;
      justify-content: center;
      color: #ffffff;
      font-weight: 800;
      font-size: 16px;
      letter-spacing: -0.5px;
      box-shadow: 0 2px 5px rgba(37, 99, 235, 0.25);
    }
    .brand-title {
      font-size: 16px;
      font-weight: 800;
      color: var(--hr-text);
      line-height: 1.2;
    }
    .brand-subtitle {
      font-size: 12px;
      color: var(--hr-muted);
      font-weight: 500;
    }
    .header-help {
      font-size: 13px;
      color: var(--hr-text-secondary);
      display: flex;
      align-items: center;
      gap: 6px;
    }
    .header-help a {
      color: var(--hr-primary);
      text-decoration: none;
      font-weight: 600;
    }
    .header-help a:hover {
      text-decoration: underline;
    }

    /* Main Container */
    .main-wrapper {
      max-width: 1140px;
      width: 100%;
      margin: 0 auto;
      padding: 32px 20px 64px 20px;
      flex: 1;
    }

    /* Hero Section */
    .hero-section {
      text-align: center;
      margin-bottom: 32px;
    }
    .hero-badge {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 4px 12px;
      background: var(--hr-primary-light);
      border: 1px solid var(--hr-primary-border);
      color: var(--hr-primary);
      font-size: 12px;
      font-weight: 600;
      border-radius: 9999px;
      margin-bottom: 12px;
    }
    .hero-title {
      font-size: 32px;
      font-weight: 800;
      color: var(--hr-text);
      letter-spacing: -0.5px;
      margin-bottom: 8px;
    }
    .hero-subtitle {
      font-size: 15px;
      color: var(--hr-text-secondary);
      max-width: 600px;
      margin: 0 auto 16px auto;
      line-height: 1.5;
    }
    .hero-features {
      display: flex;
      justify-content: center;
      gap: 20px;
      font-size: 12px;
      color: var(--hr-muted);
      flex-wrap: wrap;
    }
    .hero-feature-item {
      display: flex;
      align-items: center;
      gap: 5px;
      font-weight: 600;
    }

    /* Stepper */
    .stepper-wrap {
      background: var(--hr-surface);
      border: 1px solid var(--hr-border);
      border-radius: var(--hr-radius);
      padding: 16px 24px;
      margin-bottom: 28px;
      box-shadow: var(--hr-shadow-sm);
    }
    .stepper-nav {
      display: flex;
      justify-content: space-between;
      position: relative;
    }
    .stepper-nav::before {
      content: '';
      position: absolute;
      top: 18px;
      left: 36px;
      right: 36px;
      height: 2px;
      background: var(--hr-border);
      z-index: 1;
    }
    .step-item {
      position: relative;
      z-index: 2;
      display: flex;
      flex-direction: column;
      align-items: center;
      cursor: pointer;
      background: var(--hr-surface);
      padding: 0 8px;
    }
    .step-circle {
      width: 36px;
      height: 36px;
      border-radius: 50%;
      background: var(--hr-surface);
      border: 2px solid var(--hr-border);
      color: var(--hr-muted);
      font-size: 14px;
      font-weight: 700;
      display: flex;
      align-items: center;
      justify-content: center;
      transition: all 0.2s ease;
      margin-bottom: 6px;
    }
    .step-item.active .step-circle {
      border-color: var(--hr-primary);
      background: var(--hr-primary);
      color: #ffffff;
      box-shadow: 0 0 0 4px var(--hr-primary-light);
    }
    .step-item.completed .step-circle {
      border-color: var(--hr-success);
      background: var(--hr-success);
      color: #ffffff;
    }
    .step-label {
      font-size: 12px;
      font-weight: 600;
      color: var(--hr-muted);
      transition: color 0.2s;
    }
    .step-item.active .step-label {
      color: var(--hr-primary);
      font-weight: 700;
    }
    .step-item.completed .step-label {
      color: var(--hr-text);
    }

    /* Layout Grid (Desktop & Mobile) */
    .portal-grid {
      display: grid;
      grid-template-columns: 1fr 340px;
      gap: 28px;
      align-items: start;
    }
    @media (max-width: 860px) {
      .portal-grid {
        grid-template-columns: 1fr;
      }
    }

    /* Wizard Content Card */
    .wizard-card {
      background: var(--hr-surface);
      border: 1px solid var(--hr-border);
      border-radius: var(--hr-radius);
      padding: 28px;
      box-shadow: var(--hr-shadow);
    }
    .step-panel {
      display: none;
      animation: fadeIn 0.25s ease-out;
    }
    .step-panel.active {
      display: block;
    }
    @keyframes fadeIn {
      from { opacity: 0; transform: translateY(6px); }
      to { opacity: 1; transform: translateY(0); }
    }

    .panel-header {
      margin-bottom: 20px;
      padding-bottom: 14px;
      border-bottom: 1px solid var(--hr-border);
    }
    .panel-title {
      font-size: 18px;
      font-weight: 800;
      color: var(--hr-text);
      margin-bottom: 4px;
    }
    .panel-desc {
      font-size: 13px;
      color: var(--hr-text-secondary);
    }

    /* Service Cards */
    .services-list {
      display: flex;
      flex-direction: column;
      gap: 12px;
    }
    .service-card {
      border: 1.5px solid var(--hr-border);
      border-radius: 10px;
      padding: 16px 18px;
      cursor: pointer;
      transition: all 0.2s ease;
      display: flex;
      justify-content: space-between;
      align-items: center;
      background: var(--hr-surface);
    }
    .service-card:hover {
      border-color: var(--hr-primary-border);
      background: var(--hr-bg);
      transform: translateY(-1px);
    }
    .service-card.selected {
      border-color: var(--hr-primary);
      background: var(--hr-primary-light);
      box-shadow: 0 0 0 1px var(--hr-primary);
    }
    .service-info {
      flex: 1;
    }
    .service-tag {
      font-size: 11px;
      font-weight: 700;
      color: var(--hr-primary);
      text-transform: uppercase;
      letter-spacing: 0.5px;
      margin-bottom: 4px;
    }
    .service-name {
      font-size: 15px;
      font-weight: 700;
      color: var(--hr-text);
      margin-bottom: 4px;
    }
    .service-desc {
      font-size: 13px;
      color: var(--hr-muted);
      line-height: 1.4;
    }
    .service-meta {
      text-align: right;
      padding-left: 16px;
    }
    .service-price {
      font-size: 18px;
      font-weight: 800;
      color: var(--hr-text);
    }
    .service-duration {
      font-size: 12px;
      color: var(--hr-muted);
      font-weight: 500;
      margin-top: 2px;
    }

    /* Specialist Cards */
    .specialists-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
      gap: 14px;
    }
    .specialist-card {
      border: 1.5px solid var(--hr-border);
      border-radius: 10px;
      padding: 16px;
      cursor: pointer;
      transition: all 0.2s ease;
      background: var(--hr-surface);
      display: flex;
      flex-direction: column;
      align-items: center;
      text-align: center;
    }
    .specialist-card:hover {
      border-color: var(--hr-primary-border);
      background: var(--hr-bg);
      transform: translateY(-1px);
    }
    .specialist-card.selected {
      border-color: var(--hr-primary);
      background: var(--hr-primary-light);
      box-shadow: 0 0 0 1px var(--hr-primary);
    }
    .staff-avatar {
      width: 48px;
      height: 48px;
      border-radius: 50%;
      background: var(--hr-primary-light);
      color: var(--hr-primary);
      border: 2px solid var(--hr-primary-border);
      font-size: 16px;
      font-weight: 800;
      display: flex;
      align-items: center;
      justify-content: center;
      margin-bottom: 10px;
    }
    .staff-name {
      font-size: 14px;
      font-weight: 700;
      color: var(--hr-text);
      margin-bottom: 2px;
    }
    .staff-role {
      font-size: 12px;
      color: var(--hr-muted);
      margin-bottom: 8px;
    }
    .staff-status {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      font-size: 11px;
      font-weight: 600;
      color: var(--hr-success);
      background: var(--hr-success-bg);
      padding: 2px 8px;
      border-radius: 9999px;
      border: 1px solid var(--hr-success-border);
    }

    /* Date & Time Step */
    .calendar-container {
      margin-bottom: 24px;
    }
    .calendar-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 12px;
    }
    .calendar-month-title {
      font-size: 15px;
      font-weight: 700;
      color: var(--hr-text);
    }
    .calendar-nav-btn {
      background: var(--hr-surface-elevated);
      border: 1px solid var(--hr-border);
      border-radius: 6px;
      padding: 6px 12px;
      font-size: 12px;
      font-weight: 600;
      color: var(--hr-text);
      cursor: pointer;
      transition: all 0.15s;
    }
    .calendar-nav-btn:hover {
      background: var(--hr-border);
    }
    .calendar-grid {
      display: grid;
      grid-template-columns: repeat(7, 1fr);
      gap: 6px;
      text-align: center;
    }
    .cal-day-header {
      font-size: 11px;
      font-weight: 700;
      color: var(--hr-muted);
      padding: 6px 0;
      text-transform: uppercase;
    }
    .cal-day-cell {
      padding: 10px 0;
      font-size: 13px;
      font-weight: 600;
      border-radius: 8px;
      border: 1px solid transparent;
      cursor: pointer;
      transition: all 0.15s ease;
      color: var(--hr-text);
    }
    .cal-day-cell:hover:not(.disabled) {
      background: var(--hr-bg);
      border-color: var(--hr-primary-border);
    }
    .cal-day-cell.selected {
      background: var(--hr-primary) !important;
      color: #ffffff !important;
      font-weight: 700;
    }
    .cal-day-cell.disabled {
      color: #cbd5e1;
      cursor: not-allowed;
      background: transparent;
    }
    .cal-day-cell.today {
      border-color: var(--hr-primary);
    }

    /* Slots Section */
    .slots-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 12px;
    }
    .slots-title {
      font-size: 14px;
      font-weight: 700;
      color: var(--hr-text);
    }
    .slots-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(95px, 1fr));
      gap: 10px;
      margin-bottom: 16px;
    }
    .slot-pill {
      background: var(--hr-surface);
      border: 1.5px solid var(--hr-border);
      border-radius: 8px;
      padding: 10px 8px;
      font-family: 'JetBrains Mono', monospace;
      font-size: 13px;
      font-weight: 600;
      color: var(--hr-text);
      text-align: center;
      cursor: pointer;
      transition: all 0.15s ease;
    }
    .slot-pill:hover {
      border-color: var(--hr-primary);
      background: var(--hr-primary-light);
    }
    .slot-pill.selected {
      background: var(--hr-primary);
      color: #ffffff;
      border-color: var(--hr-primary);
      font-weight: 700;
      box-shadow: 0 2px 6px rgba(37, 99, 235, 0.3);
    }
    .slot-empty {
      grid-column: 1 / -1;
      padding: 24px;
      text-align: center;
      background: var(--hr-surface-elevated);
      border: 1px dashed var(--hr-border);
      border-radius: 8px;
      color: var(--hr-muted);
      font-size: 13px;
    }

    /* Customer Details Form */
    .form-group {
      margin-bottom: 16px;
    }
    .form-label {
      display: block;
      font-size: 13px;
      font-weight: 600;
      color: var(--hr-text);
      margin-bottom: 6px;
    }
    .form-label span {
      color: var(--hr-danger);
    }
    .form-input, .form-textarea {
      width: 100%;
      background: var(--hr-surface);
      border: 1.5px solid var(--hr-border);
      border-radius: 8px;
      padding: 11px 14px;
      color: var(--hr-text);
      font-size: 14px;
      font-family: inherit;
      transition: all 0.15s;
    }
    .form-input:focus, .form-textarea:focus {
      outline: none;
      border-color: var(--hr-primary);
      box-shadow: 0 0 0 3px var(--hr-primary-light);
    }
    .form-input.error {
      border-color: var(--hr-danger);
      background: #fef2f2;
    }
    .form-error-msg {
      font-size: 12px;
      color: var(--hr-danger);
      margin-top: 4px;
      display: none;
    }
    .form-error-msg.visible {
      display: block;
    }

    /* Wizard Navigation Buttons */
    .wizard-actions {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-top: 24px;
      padding-top: 16px;
      border-top: 1px solid var(--hr-border);
    }
    .btn-secondary {
      background: var(--hr-surface);
      border: 1.5px solid var(--hr-border);
      border-radius: 8px;
      padding: 10px 18px;
      font-size: 13px;
      font-weight: 600;
      color: var(--hr-text-secondary);
      cursor: pointer;
      transition: all 0.15s;
    }
    .btn-secondary:hover {
      background: var(--hr-surface-elevated);
      color: var(--hr-text);
    }
    .btn-primary {
      background: var(--hr-primary);
      border: none;
      border-radius: 8px;
      padding: 11px 22px;
      font-size: 14px;
      font-weight: 700;
      color: #ffffff;
      cursor: pointer;
      transition: all 0.15s;
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }
    .btn-primary:hover {
      background: var(--hr-primary-hover);
      box-shadow: 0 4px 10px rgba(37, 99, 235, 0.3);
    }
    .btn-primary:disabled {
      background: #94a3b8;
      cursor: not-allowed;
      box-shadow: none;
    }

    /* Sticky Summary Card (Right Side) */
    .summary-card {
      background: var(--hr-surface);
      border: 1px solid var(--hr-border);
      border-radius: var(--hr-radius);
      padding: 24px;
      box-shadow: var(--hr-shadow);
      position: sticky;
      top: 90px;
    }
    .summary-title {
      font-size: 16px;
      font-weight: 800;
      color: var(--hr-text);
      margin-bottom: 16px;
      padding-bottom: 12px;
      border-bottom: 1px solid var(--hr-border);
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    .summary-row {
      margin-bottom: 12px;
    }
    .summary-label {
      font-size: 11px;
      font-weight: 600;
      color: var(--hr-muted);
      text-transform: uppercase;
      letter-spacing: 0.5px;
      margin-bottom: 2px;
    }
    .summary-value {
      font-size: 14px;
      font-weight: 600;
      color: var(--hr-text);
    }
    .summary-value.empty {
      color: #94a3b8;
      font-weight: 400;
      font-style: italic;
    }
    .summary-divider {
      height: 1px;
      background: var(--hr-border);
      margin: 16px 0;
    }
    .summary-total-wrap {
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      margin-bottom: 16px;
    }
    .summary-total-label {
      font-size: 13px;
      font-weight: 700;
      color: var(--hr-text);
    }
    .summary-total-val {
      font-size: 24px;
      font-weight: 800;
      color: var(--hr-primary);
    }
    .summary-trust-badge {
      display: flex;
      align-items: center;
      gap: 6px;
      font-size: 11px;
      font-weight: 600;
      color: var(--hr-muted);
      background: var(--hr-bg);
      padding: 8px 12px;
      border-radius: 6px;
      border: 1px solid var(--hr-border);
      margin-top: 14px;
    }

    /* Confirmation Success Panel */
    .success-panel {
      display: none;
      background: var(--hr-surface);
      border: 1px solid var(--hr-border);
      border-radius: var(--hr-radius);
      padding: 40px 32px;
      text-align: center;
      max-width: 680px;
      margin: 0 auto;
      box-shadow: var(--hr-shadow-lg);
      animation: fadeIn 0.3s ease-out;
    }
    .success-icon-wrap {
      width: 72px;
      height: 72px;
      border-radius: 50%;
      background: var(--hr-success-bg);
      border: 2px solid var(--hr-success-border);
      color: var(--hr-success);
      font-size: 32px;
      display: flex;
      align-items: center;
      justify-content: center;
      margin: 0 auto 16px auto;
      box-shadow: 0 4px 12px rgba(22, 163, 74, 0.15);
    }
    .success-title {
      font-size: 24px;
      font-weight: 800;
      color: var(--hr-text);
      margin-bottom: 8px;
    }
    .success-subtitle {
      font-size: 14px;
      color: var(--hr-text-secondary);
      max-width: 480px;
      margin: 0 auto 24px auto;
      line-height: 1.5;
    }
    .receipt-box {
      background: var(--hr-bg);
      border: 1px solid var(--hr-border);
      border-radius: 10px;
      padding: 20px;
      text-align: left;
      margin-bottom: 28px;
    }
    .receipt-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 14px;
    }
    .receipt-ref-badge {
      background: var(--hr-primary-light);
      border: 1px solid var(--hr-primary-border);
      color: var(--hr-primary);
      padding: 4px 10px;
      border-radius: 6px;
      font-family: 'JetBrains Mono', monospace;
      font-size: 13px;
      font-weight: 700;
      display: inline-block;
    }
    .calendar-actions {
      display: flex;
      gap: 12px;
      justify-content: center;
      flex-wrap: wrap;
      margin-bottom: 20px;
    }
    .btn-cal {
      background: var(--hr-surface);
      border: 1.5px solid var(--hr-border);
      border-radius: 8px;
      padding: 10px 16px;
      font-size: 13px;
      font-weight: 600;
      color: var(--hr-text);
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      transition: all 0.15s;
      cursor: pointer;
    }
    .btn-cal:hover {
      border-color: var(--hr-primary);
      background: var(--hr-primary-light);
      color: var(--hr-primary);
    }

    /* Footer */
    .public-footer {
      background: var(--hr-surface);
      border-top: 1px solid var(--hr-border);
      padding: 32px 20px;
      margin-top: auto;
    }
    .footer-container {
      max-width: 1140px;
      margin: 0 auto;
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 16px;
    }
    .footer-brand {
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .footer-links {
      display: flex;
      gap: 20px;
      font-size: 13px;
    }
    .footer-links a {
      color: var(--hr-muted);
      text-decoration: none;
      transition: color 0.15s;
    }
    .footer-links a:hover {
      color: var(--hr-primary);
    }
    .footer-copy {
      font-size: 12px;
      color: var(--hr-muted);
      width: 100%;
      text-align: center;
      margin-top: 16px;
      padding-top: 16px;
      border-top: 1px dashed var(--hr-border);
    }
  
    /* --- Universal Responsive Sidebar --- */
    .sidebar { width: 260px; background: var(--hr-surface); border-right: 1px solid var(--hr-border); display: flex; flex-direction: column; flex-shrink: 0; transition: width 200ms cubic-bezier(0.16, 1, 0.3, 1); z-index: 100; }
    body.sidebar-collapsed .sidebar { width: 68px; }
    body.sidebar-collapsed .sidebar .brand-title,
    body.sidebar-collapsed .sidebar .brand-sub,
    body.sidebar-collapsed .sidebar .nav-section-title,
    body.sidebar-collapsed .sidebar .nav-badge,
    body.sidebar-collapsed .sidebar .user-info { display: none !important; }
    body.sidebar-collapsed .sidebar .brand-header { justify-content: center; padding: 16px 8px; }
    body.sidebar-collapsed .sidebar .nav-item a { justify-content: center; padding: 10px; }
    body.sidebar-collapsed .sidebar .user-footer { justify-content: center; padding: 12px 8px; }
    
    .sidebar-overlay { position: fixed; inset: 0; background: rgba(15,23,42,0.45); backdrop-filter: blur(2px); z-index: 9998; display: none; }
    .sidebar-overlay.active { display: block; }

    @media (max-width: 1023px) {
      .sidebar { position: fixed; top: 0; bottom: 0; left: 0; z-index: 9999; transform: translateX(-100%); transition: transform 250ms cubic-bezier(0.16, 1, 0.3, 1); box-shadow: 10px 0 30px rgba(15,23,42,0.15); width: 280px !important; }
      .sidebar.mobile-open { transform: translateX(0); }
      .mobile-menu-btn { display: inline-flex !important; }
      .top-bar { padding: 0 16px !important; }
      .content-body { padding: 16px !important; }
    }

  </style>
</head>
<body>
  <div id="sidebar-overlay" class="sidebar-overlay"></div>

  <!-- Public Header -->
  <header class="public-header">
    <div class="header-container">
      <div class="brand-logo-wrap">
        <div class="brand-logo-badge">HR</div>
        <div>
          <div class="brand-title">HR Services</div>
          <div class="brand-subtitle">Client Appointment & Availability Portal</div>
        </div>
      </div>
      <div class="header-help">
        Need assistance? <a href="mailto:support@hr-services.local">Contact Support</a>
      </div>
    </div>
  </header>

  <!-- Main Container -->
  <main class="main-wrapper">
    
    <!-- Hero Section -->
    <div class="hero-section">
      <div class="hero-badge">⚡ Instant Collision-Free Booking</div>
      <h1 class="hero-title">Book an Appointment</h1>
      <p class="hero-subtitle">Choose a service, select a specialist, pick a convenient time, and confirm your appointment. Simple. Fast. Secure.</p>
      <div class="hero-features">
        <div class="hero-feature-item">✓ Instant Confirmation</div>
        <div class="hero-feature-item">✓ Guaranteed Real-Time Slots</div>
        <div class="hero-feature-item">✓ Calendar Invitations</div>
      </div>
    </div>

    <!-- Stepper Navigation -->
    <div class="stepper-wrap" id="stepper-container">
      <div class="stepper-nav">
        <div class="step-item active" id="step-nav-1" onclick="goToStep(1)">
          <div class="step-circle" id="step-num-1">1</div>
          <div class="step-label">Service</div>
        </div>
        <div class="step-item" id="step-nav-2" onclick="goToStep(2)">
          <div class="step-circle" id="step-num-2">2</div>
          <div class="step-label">Specialist</div>
        </div>
        <div class="step-item" id="step-nav-3" onclick="goToStep(3)">
          <div class="step-circle" id="step-num-3">3</div>
          <div class="step-label">Date & Time</div>
        </div>
        <div class="step-item" id="step-nav-4" onclick="goToStep(4)">
          <div class="step-circle" id="step-num-4">4</div>
          <div class="step-label">Your Details</div>
        </div>
      </div>
    </div>

    <!-- Wizard & Summary Layout -->
    <div class="portal-grid" id="booking-wizard-layout">
      
      <!-- Wizard Left Panel -->
      <div class="wizard-card">
        
        <!-- STEP 1: SERVICE SELECTION -->
        <div class="step-panel active" id="panel-step-1">
          <div class="panel-header">
            <h2 class="panel-title">1. Choose a Service</h2>
            <p class="panel-desc">Select the advisory or consultation service you wish to reserve.</p>
          </div>
          <div class="services-list" id="services-container">
            <div style="padding:20px; text-align:center; color:var(--hr-muted);">Loading available services...</div>
          </div>
          <div class="wizard-actions">
            <div></div>
            <button type="button" class="btn-primary" id="btn-to-step-2" onclick="nextStep(2)" disabled>
              Continue to Specialist →
            </button>
          </div>
        </div>

        <!-- STEP 2: SPECIALIST SELECTION -->
        <div class="step-panel" id="panel-step-2">
          <div class="panel-header">
            <h2 class="panel-title">2. Choose Your Specialist</h2>
            <p class="panel-desc">Select the advisor or senior specialist for your session.</p>
          </div>
          <div class="specialists-grid" id="staff-container">
            <div style="padding:20px; text-align:center; color:var(--hr-muted); grid-column:1/-1;">Loading qualified specialists...</div>
          </div>
          <div class="wizard-actions">
            <button type="button" class="btn-secondary" onclick="prevStep(1)">← Back to Services</button>
            <button type="button" class="btn-primary" id="btn-to-step-3" onclick="nextStep(3)" disabled>
              Continue to Date & Time →
            </button>
          </div>
        </div>

        <!-- STEP 3: DATE & TIME -->
        <div class="step-panel" id="panel-step-3">
          <div class="panel-header">
            <h2 class="panel-title">3. Pick Date & Time</h2>
            <p class="panel-desc">Select a date on the calendar, then choose an available collision-free time slot.</p>
          </div>

          <!-- Interactive Calendar -->
          <div class="calendar-container">
            <div class="calendar-header">
              <button type="button" class="calendar-nav-btn" onclick="changeMonth(-1)">‹ Previous</button>
              <div class="calendar-month-title" id="cal-month-name">August 2026</div>
              <button type="button" class="calendar-nav-btn" onclick="changeMonth(1)">Next ›</button>
            </div>
            <div class="calendar-grid" id="calendar-grid"></div>
          </div>

          <!-- Time Slots -->
          <div class="slots-header">
            <div class="slots-title">Available Openings on <span id="selected-date-display" style="color:var(--hr-primary);">Today</span></div>
          </div>
          <div class="slots-grid" id="slots-container">
            <div class="slot-empty">Please select a date on the calendar above.</div>
          </div>

          <div class="wizard-actions">
            <button type="button" class="btn-secondary" onclick="prevStep(2)">← Back to Specialist</button>
            <button type="button" class="btn-primary" id="btn-to-step-4" onclick="nextStep(4)" disabled>
              Continue to Details →
            </button>
          </div>
        </div>

        <!-- STEP 4: CUSTOMER DETAILS -->
        <div class="step-panel" id="panel-step-4">
          <div class="panel-header">
            <h2 class="panel-title">4. Your Details</h2>
            <p class="panel-desc">Enter your contact information to receive your confirmation and calendar invite.</p>
          </div>

          <form id="booking-form" onsubmit="submitBooking(event)">
            <div class="form-group">
              <label class="form-label" for="cust-name">Full Name <span>*</span></label>
              <input type="text" id="cust-name" class="form-input" placeholder="e.g. Oliver Queen" required oninput="validateInput(this)">
              <div class="form-error-msg" id="err-cust-name">Please enter your full name.</div>
            </div>

            <div style="display:grid; grid-template-columns:1fr 1fr; gap:14px;">
              <div class="form-group">
                <label class="form-label" for="cust-email">Email Address <span>*</span></label>
                <input type="email" id="cust-email" class="form-input" placeholder="oliver@example.com" required oninput="validateInput(this)">
                <div class="form-error-msg" id="err-cust-email">Please enter a valid email address.</div>
              </div>
              <div class="form-group">
                <label class="form-label" for="cust-phone">Phone Number <span>*</span></label>
                <input type="tel" id="cust-phone" class="form-input" placeholder="+44 7700 900000" required oninput="validateInput(this)">
                <div class="form-error-msg" id="err-cust-phone">Please enter your contact phone number.</div>
              </div>
            </div>

            <div class="form-group">
              <label class="form-label" for="cust-notes">Appointment Notes (Optional)</label>
              <textarea id="cust-notes" class="form-textarea" rows="3" placeholder="Provide any key objectives or questions for the specialist..."></textarea>
            </div>

            <div class="wizard-actions">
              <button type="button" class="btn-secondary" onclick="prevStep(3)">← Back to Date & Time</button>
              <button type="submit" class="btn-primary" id="btn-submit-booking">
                Confirm & Reserve Appointment ✓
              </button>
            </div>
          </form>
        </div>

      </div>

      <!-- Right Sticky Summary Card -->
      <div class="summary-card">
        <div class="summary-title">
          <span>Appointment Summary</span>
          <span style="font-size:12px; font-weight:700; color:var(--hr-primary);" id="summary-badge">Step 1 of 4</span>
        </div>

        <div class="summary-row">
          <div class="summary-label">Service</div>
          <div class="summary-value empty" id="sum-service">Not selected</div>
        </div>

        <div class="summary-row">
          <div class="summary-label">Specialist</div>
          <div class="summary-value empty" id="sum-staff">Not selected</div>
        </div>

        <div class="summary-row">
          <div class="summary-label">Date</div>
          <div class="summary-value empty" id="sum-date">Not selected</div>
        </div>

        <div class="summary-row">
          <div class="summary-label">Time & Duration</div>
          <div class="summary-value empty" id="sum-time">Not selected</div>
        </div>

        <div class="summary-divider"></div>

        <div class="summary-total-wrap">
          <div class="summary-total-label">Total Fee:</div>
          <div class="summary-total-val" id="sum-total">£0.00</div>
        </div>

        <div class="summary-trust-badge">
          <span>🔒</span>
          <span>Collision-Free Real-Time Lock</span>
        </div>
      </div>

    </div>

    <!-- Success / Confirmation Screen -->
    <div class="success-panel" id="success-panel">
      <div class="success-icon-wrap">✓</div>
      <h2 class="success-title">Appointment Confirmed!</h2>
      <p class="success-subtitle" id="success-welcome-msg">Thank you. Your appointment has been successfully reserved.</p>

      <div class="receipt-box">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:14px; padding-bottom:10px; border-bottom:1px solid var(--hr-border);">
          <span style="font-size:12px; font-weight:700; color:var(--hr-muted); text-transform:uppercase;">Booking Reference</span>
          <span class="receipt-ref-badge" id="receipt-ref">HR-2026-00001</span>
        </div>

        <div class="receipt-grid">
          <div>
            <div class="summary-label">Service</div>
            <div class="summary-value" id="receipt-service">Initial Consultation</div>
          </div>
          <div>
            <div class="summary-label">Specialist</div>
            <div class="summary-value" id="receipt-staff">Sarah Mitchell</div>
          </div>
          <div>
            <div class="summary-label">Date & Time</div>
            <div class="summary-value" id="receipt-datetime">28 Aug 2026 at 10:00 - 11:00</div>
          </div>
          <div>
            <div class="summary-label">Fee (GBP)</div>
            <div class="summary-value" id="receipt-price" style="color:var(--hr-primary); font-weight:800;">£150.00</div>
          </div>
        </div>
      </div>

      <div class="calendar-actions">
        <a id="btn-google-cal" href="#" target="_blank" class="btn-cal">
          📅 Add to Google Calendar
        </a>
        <button type="button" class="btn-cal" onclick="downloadIcsFile()">
          📥 Download .ics Calendar File
        </button>
      </div>

      <button type="button" class="btn-secondary" style="margin-top:10px;" onclick="resetBookingPortal()">
        ➕ Book Another Appointment
      </button>
    </div>

  </main>

  <!-- Public Footer -->
  <footer class="public-footer">
    <div class="footer-container">
      <div class="footer-brand">
        <div class="brand-logo-badge" style="width:30px; height:30px; font-size:13px;">HR</div>
        <div>
          <div style="font-weight:700; font-size:14px;">HR Services</div>
          <div style="font-size:11px; color:var(--hr-muted);">Universal 24/7 Appointment & Availability Engine</div>
        </div>
      </div>
      <div class="footer-links">
        <a href="mailto:privacy@hr-services.local">Privacy Policy</a>
        <a href="mailto:terms@hr-services.local">Terms of Service</a>
        <a href="mailto:support@hr-services.local">Support</a>
      </div>
      <div class="footer-copy">
        &copy; 2026 HR Services. All rights reserved. Self-Service Client Appointment Portal.
      </div>
    </div>
  </footer>

  <script>
    // State Management
    let currentStep = 1;
    let servicesList = [];
    let staffList = [];
    let selectedService = null;
    let selectedStaff = null;
    let selectedDate = null;
    let selectedTime = null;
    let confirmedBookingData = null;

    // Calendar state
    let calCurrentMonth = new Date(); // Active viewing month

    // Format Helpers
    function formatCurrency(val) {
      return '£' + (val || 0).toLocaleString('en-GB', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }

    function formatDateFriendly(dateStr) {
      if (!dateStr) return '';
      const [y, m, d] = dateStr.split('-').map(Number);
      const dt = new Date(y, m - 1, d);
      return dt.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' });
    }

    // Step Navigation
    function goToStep(step) {
      // Validate permissions to move forward
      if (step === 2 && !selectedService) return;
      if (step === 3 && (!selectedService || !selectedStaff)) return;
      if (step === 4 && (!selectedService || !selectedStaff || !selectedDate || !selectedTime)) return;
      
      currentStep = step;
      updateStepUI();
    }

    function nextStep(step) {
      currentStep = step;
      updateStepUI();
    }

    function prevStep(step) {
      currentStep = step;
      updateStepUI();
    }

    function updateStepUI() {
      // Panels
      for (let i = 1; i <= 4; i++) {
        const panel = document.getElementById(`panel-step-${i}`);
        const nav = document.getElementById(`step-nav-${i}`);
        const num = document.getElementById(`step-num-${i}`);

        if (panel) panel.classList.toggle('active', i === currentStep);
        if (nav) {
          nav.classList.toggle('active', i === currentStep);
          nav.classList.toggle('completed', i < currentStep);
          if (i < currentStep) {
            num.innerHTML = '✓';
          } else {
            num.innerText = i;
          }
        }
      }

      document.getElementById('summary-badge').innerText = `Step ${currentStep} of 4`;
      window.scrollTo({ top: 120, behavior: 'smooth' });
    }

    // Service Selection
    function selectService(sId) {
      selectedService = servicesList.find(s => s.id === sId);
      document.querySelectorAll('.service-card').forEach(el => {
        el.classList.toggle('selected', parseInt(el.dataset.id) === sId);
      });
      document.getElementById('btn-to-step-2').disabled = false;

      // Update Summary
      document.getElementById('sum-service').innerHTML = `<strong>${selectedService.name}</strong> <span style="font-size:12px; color:var(--hr-muted);">(${selectedService.duration_minutes}m)</span>`;
      document.getElementById('sum-service').classList.remove('empty');
      document.getElementById('sum-total').innerText = formatCurrency(selectedService.price);

      // Auto advance to Specialist
      setTimeout(() => nextStep(2), 200);
    }

    // Specialist Selection
    function selectSpecialist(stId) {
      selectedStaff = staffList.find(st => st.id === stId);
      document.querySelectorAll('.specialist-card').forEach(el => {
        el.classList.toggle('selected', parseInt(el.dataset.id) === stId);
      });
      document.getElementById('btn-to-step-3').disabled = false;

      // Update Summary
      document.getElementById('sum-staff').innerHTML = `<strong>${selectedStaff.name}</strong> <span style="font-size:12px; color:var(--hr-muted);">(${selectedStaff.role})</span>`;
      document.getElementById('sum-staff').classList.remove('empty');

      // Refresh calendar & availability
      renderCalendar();
      if (selectedDate) {
        fetchLiveAvailability();
      }

      // Auto advance to Date & Time
      setTimeout(() => nextStep(3), 200);
    }

    // Calendar Generation
    function changeMonth(delta) {
      calCurrentMonth.setMonth(calCurrentMonth.getMonth() + delta);
      renderCalendar();
    }

    function renderCalendar() {
      const year = calCurrentMonth.getFullYear();
      const month = calCurrentMonth.getMonth();
      const monthName = calCurrentMonth.toLocaleString('en-GB', { month: 'long', year: 'numeric' });
      document.getElementById('cal-month-name').innerText = monthName;

      const grid = document.getElementById('calendar-grid');
      grid.innerHTML = `
        <div class="cal-day-header">Mo</div>
        <div class="cal-day-header">Tu</div>
        <div class="cal-day-header">We</div>
        <div class="cal-day-header">Th</div>
        <div class="cal-day-header">Fr</div>
        <div class="cal-day-header">Sa</div>
        <div class="cal-day-header">Su</div>
      `;

      const firstDay = new Date(year, month, 1);
      const lastDay = new Date(year, month + 1, 0);
      const today = new Date();
      today.setHours(0, 0, 0, 0);

      // Days of week: getDay() 0=Sun, 1=Mon -> convert to Mon=0..Sun=6
      let startDayOfWeek = firstDay.getDay() - 1;
      if (startDayOfWeek === -1) startDayOfWeek = 6;

      // Empty padding cells for start of month
      for (let i = 0; i < startDayOfWeek; i++) {
        const emptyCell = document.createElement('div');
        grid.appendChild(emptyCell);
      }

      // Staff working days set
      const workingDays = selectedStaff ? selectedStaff.working_days.split(',') : ['1','2','3','4','5','6'];

      // Populate month days
      for (let d = 1; d <= lastDay.getDate(); d++) {
        const dateObj = new Date(year, month, d);
        const isoDate = `${year}-${String(month + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
        
        let dow = dateObj.getDay(); // 0 is Sun
        let isoDow = dow === 0 ? '7' : String(dow);

        const isPast = dateObj < today;
        const isWorkingDay = workingDays.includes(isoDow);
        const isSelected = selectedDate === isoDate;
        const isToday = dateObj.getTime() === today.getTime();

        const dayCell = document.createElement('div');
        dayCell.className = `cal-day-cell ${isPast || !isWorkingDay ? 'disabled' : ''} ${isSelected ? 'selected' : ''} ${isToday ? 'today' : ''}`;
        dayCell.innerText = d;

        if (!isPast && isWorkingDay) {
          dayCell.onclick = () => selectCalendarDate(isoDate);
        } else if (!isWorkingDay) {
          dayCell.title = "Specialist not available on this day";
        }

        grid.appendChild(dayCell);
      }
    }

    function selectCalendarDate(isoDate) {
      selectedDate = isoDate;
      selectedTime = null;
      document.getElementById('btn-to-step-4').disabled = true;

      // Update Summary
      document.getElementById('sum-date').innerHTML = `<strong>${formatDateFriendly(isoDate)}</strong>`;
      document.getElementById('sum-date').classList.remove('empty');
      document.getElementById('sum-time').innerHTML = `Not selected`;
      document.getElementById('sum-time').classList.add('empty');
      document.getElementById('selected-date-display').innerText = formatDateFriendly(isoDate);

      renderCalendar();
      fetchLiveAvailability();
    }

    // Availability Engine API Call
    async function fetchLiveAvailability() {
      const container = document.getElementById('slots-container');
      if (!selectedService || !selectedStaff || !selectedDate) {
        container.innerHTML = `<div class="slot-empty">Please pick a service, specialist, and date to view live openings.</div>`;
        return;
      }

      container.innerHTML = `<div class="slot-empty" style="color:var(--hr-primary);">Checking live availability for ${selectedStaff.name}...</div>`;

      try {
        const res = await fetch(`/api/availability?service_id=${selectedService.id}&staff_id=${selectedStaff.id}&date=${selectedDate}`);
        const data = await res.json();

        if (!data.available_slots || data.available_slots.length === 0) {
          container.innerHTML = `<div class="slot-empty" style="color:var(--hr-danger);">No appointments available on ${formatDateFriendly(selectedDate)}.<br><span style="font-size:12px; color:var(--hr-muted); margin-top:4px; display:inline-block;">Please select another date on the calendar above.</span></div>`;
          return;
        }

        container.innerHTML = data.available_slots.map(slot => `
          <div class="slot-pill ${slot === selectedTime ? 'selected' : ''}" onclick="selectSlotTime('${slot}', this)">
            ${slot}
          </div>
        `).join('');
      } catch (err) {
        container.innerHTML = `<div class="slot-empty" style="color:var(--hr-danger);">Unable to compute availability. Please try again.</div>`;
      }
    }

    function selectSlotTime(time, el) {
      selectedTime = time;
      document.querySelectorAll('.slot-pill').forEach(b => b.classList.remove('selected'));
      if (el) el.classList.add('selected');
      document.getElementById('btn-to-step-4').disabled = false;

      // Calculate end time
      const [h, m] = time.split(':').map(Number);
      const endDt = new Date();
      endDt.setHours(h, m + selectedService.duration_minutes, 0, 0);
      const endStr = `${String(endDt.getHours()).padStart(2, '0')}:${String(endDt.getMinutes()).padStart(2, '0')}`;

      // Update Summary
      document.getElementById('sum-time').innerHTML = `<strong>${time} – ${endStr}</strong> <span style="font-size:12px; color:var(--hr-muted);">(${selectedService.duration_minutes} mins)</span>`;
      document.getElementById('sum-time').classList.remove('empty');
    }

    // Input Validation
    function validateInput(input) {
      const errEl = document.getElementById(`err-${input.id}`);
      if (input.required && !input.value.trim()) {
        input.classList.add('error');
        if (errEl) errEl.classList.add('visible');
        return false;
      }
      if (input.type === 'email') {
        const emailRegex = /^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$/;
        if (!emailRegex.test(input.value.trim())) {
          input.classList.add('error');
          if (errEl) errEl.classList.add('visible');
          return false;
        }
      }
      input.classList.remove('error');
      if (errEl) errEl.classList.remove('visible');
      return true;
    }

    // Submit Booking
    async function submitBooking(e) {
      e.preventDefault();
      
      const nameInput = document.getElementById('cust-name');
      const emailInput = document.getElementById('cust-email');
      const phoneInput = document.getElementById('cust-phone');
      const notesInput = document.getElementById('cust-notes');

      const v1 = validateInput(nameInput);
      const v2 = validateInput(emailInput);
      const v3 = validateInput(phoneInput);

      if (!v1 || !v2 || !v3) return;

      if (!selectedService || !selectedStaff || !selectedDate || !selectedTime) {
        alert('Please complete all previous booking selections first.');
        return;
      }

      const submitBtn = document.getElementById('btn-submit-booking');
      submitBtn.disabled = true;
      submitBtn.innerText = 'Locking & Reserving Slot...';

      const payload = {
        service_id: selectedService.id,
        staff_id: selectedStaff.id,
        booking_date: selectedDate,
        start_time: selectedTime,
        customer_name: nameInput.value.trim(),
        customer_email: emailInput.value.trim(),
        customer_phone: phoneInput.value.trim(),
        customer_notes: notesInput.value.trim()
      };

      try {
        const res = await fetch('/api/bookings', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });

        if (res.status === 201) {
          const data = await res.json();
          confirmedBookingData = { ...data, ...payload };
          showSuccessScreen(confirmedBookingData);
        } else {
          const errData = await res.json();
          alert('Booking Conflict: ' + (errData.detail || 'This time slot was just booked by another customer. Please select another time.'));
          submitBtn.disabled = false;
          submitBtn.innerText = 'Confirm & Reserve Appointment ✓';
          goToStep(3);
          fetchLiveAvailability();
        }
      } catch (err) {
        alert('Communication error with server. Please try again.');
        submitBtn.disabled = false;
        submitBtn.innerText = 'Confirm & Reserve Appointment ✓';
      }
    }

    // Success Screen
    function showSuccessScreen(data) {
      document.getElementById('stepper-container').style.display = 'none';
      document.getElementById('booking-wizard-layout').style.display = 'none';
      
      const successPanel = document.getElementById('success-panel');
      successPanel.style.display = 'block';

      document.getElementById('success-welcome-msg').innerText = `Thank you, ${data.customer_name}. Your appointment has been successfully reserved with institutional collision-lock protection.`;
      document.getElementById('receipt-ref').innerText = `HR-2026-${String(data.id).padStart(5, '0')}`;
      document.getElementById('receipt-service').innerText = data.service;
      document.getElementById('receipt-staff').innerText = data.staff;
      document.getElementById('receipt-datetime').innerText = `${formatDateFriendly(data.date)} at ${data.start_time} - ${data.end_time}`;
      document.getElementById('receipt-price').innerText = formatCurrency(data.price);

      // Generate Google Calendar Link
      const startTimeFormatted = data.date.replace(/-/g, '') + 'T' + data.start_time.replace(/:/g, '') + '00Z';
      const endTimeFormatted = data.date.replace(/-/g, '') + 'T' + data.end_time.replace(/:/g, '') + '00Z';
      const eventTitle = encodeURIComponent(`HR Appointment: ${data.service} (${data.staff})`);
      const eventDetails = encodeURIComponent(`Confirmed Booking Reference: HR-2026-${String(data.id).padStart(5, '0')}\\nSpecialist: ${data.staff}\\nClient: ${data.customer_name}\\nPrice: £${data.price.toFixed(2)}`);
      
      const gcalUrl = `https://calendar.google.com/calendar/render?action=TEMPLATE&text=${eventTitle}&dates=${startTimeFormatted}/${endTimeFormatted}&details=${eventDetails}&location=HR+Professional+Services`;
      document.getElementById('btn-google-cal').href = gcalUrl;

      window.scrollTo({ top: 100, behavior: 'smooth' });
    }

    // Download .ics Calendar File
    function downloadIcsFile() {
      if (!confirmedBookingData) return;
      const d = confirmedBookingData;
      const startDt = d.date.replace(/-/g, '') + 'T' + d.start_time.replace(/:/g, '') + '00';
      const endDt = d.date.replace(/-/g, '') + 'T' + d.end_time.replace(/:/g, '') + '00';

      const icsContent = [
        'BEGIN:VCALENDAR',
        'VERSION:2.0',
        'PRODID:-//HR Services//HR Bookings//EN',
        'CALSCALE:GREGORIAN',
        'METHOD:PUBLISH',
        'BEGIN:VEVENT',
        `UID:HR-BKG-${d.id}@hr-services.local`,
        `DTSTAMP:${new Date().toISOString().replace(/[-:]/g, '').split('.')[0]}Z`,
        `DTSTART:${startDt}`,
        `DTEND:${endDt}`,
        `SUMMARY:HR Appointment: ${d.service} with ${d.staff}`,
        `DESCRIPTION:Reference: HR-2026-${String(d.id).padStart(5, '0')}\\nSpecialist: ${d.staff}\\nCustomer: ${d.customer_name}\\nFee: £${d.price.toFixed(2)}`,
        'LOCATION:HR Services',
        'STATUS:CONFIRMED',
        'END:VEVENT',
        'END:VCALENDAR'
      ].join('\\r\\n');

      const blob = new Blob([icsContent], { type: 'text/calendar;charset=utf-8' });
      const link = document.createElement('a');
      link.href = window.URL.createObjectURL(blob);
      link.setAttribute('download', `appointment-HR-${d.id}.ics`);
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
    }

    function resetBookingPortal() {
      window.location.reload();
    }

    // Initialization
    async function initPortal() {
      try {
        // 1. Fetch Services
        const sRes = await fetch('/api/services');
        servicesList = await sRes.json();
        const servContainer = document.getElementById('services-container');
        
        servContainer.innerHTML = servicesList.map(s => `
          <div class="service-card" data-id="${s.id}" onclick="selectService(${s.id})">
            <div class="service-info">
              <div class="service-tag">${s.category || 'General'}</div>
              <div class="service-name">${s.name}</div>
              <div class="service-desc">${s.description || 'Institutional advisory & review session.'}</div>
            </div>
            <div class="service-meta">
              <div class="service-price">${formatCurrency(s.price)}</div>
              <div class="service-duration">⏱ ${s.duration_minutes} mins</div>
            </div>
          </div>
        `).join('');

        // 2. Fetch Specialists
        const stRes = await fetch('/api/staff');
        staffList = await stRes.json();
        const staffContainer = document.getElementById('staff-container');

        staffContainer.innerHTML = staffList.map(st => {
          const initials = st.name.split(' ').map(n => n[0]).join('').substring(0, 2);
          return `
            <div class="specialist-card" data-id="${st.id}" onclick="selectSpecialist(${st.id})">
              <div class="staff-avatar">${initials}</div>
              <div class="staff-name">${st.name}</div>
              <div class="staff-role">${st.role || 'Specialist'}</div>
              <div class="staff-status">● Available</div>
            </div>
          `;
        }).join('');

        // Set default date to today
        const todayIso = new Date().toISOString().split('T')[0];
        selectedDate = todayIso;
        renderCalendar();
      } catch (err) {
        console.error('Error initializing portal:', err);
      }
    }

    window.addEventListener('DOMContentLoaded', initPortal);
  </script>

<script>
  (function() {
    const KEY = 'hr_sidebar_collapsed';
    if (localStorage.getItem(KEY) === 'true' && window.innerWidth >= 1024) {
      document.body.classList.add('sidebar-collapsed');
      const s = document.querySelector('.sidebar');
      if (s) s.classList.add('collapsed');
    }
    window.toggleSidebar = function() {
      if (window.innerWidth < 1024) {
        const s = document.querySelector('.sidebar');
        const o = document.getElementById('sidebar-overlay');
        if (s) {
          const open = s.classList.toggle('mobile-open');
          if (o) o.classList.toggle('active', open);
          document.body.style.overflow = open ? 'hidden' : '';
        }
      } else {
        const c = document.body.classList.toggle('sidebar-collapsed');
        const s = document.querySelector('.sidebar');
        if (s) s.classList.toggle('collapsed', c);
        localStorage.setItem(KEY, c);
      }
    };
    window.closeSidebar = function() {
      const s = document.querySelector('.sidebar');
      const o = document.getElementById('sidebar-overlay');
      if (s) s.classList.remove('mobile-open');
      if (o) o.classList.remove('active');
      document.body.style.overflow = '';
    };
    document.addEventListener('DOMContentLoaded', () => {
      const o = document.getElementById('sidebar-overlay');
      if (o) o.addEventListener('click', window.closeSidebar);
    });
  })();
</script>

</body>
</html>
"""


# --- Main Admin Application Shell ---
@app.get("/", response_class=HTMLResponse)
@app.get("/admin", response_class=HTMLResponse)
def admin_page():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>HR Bookings — Appointment Scheduling & Roster Management</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@500;700&display=swap" rel="stylesheet">
  <style>
    :root {
      --hr-primary: #2563eb;
      --hr-primary-hover: #1d4ed8;
      --hr-primary-light: #eff6ff;
      --hr-success: #10b981;
      --hr-warning: #f59e0b;
      --hr-danger: #ef4444;
      --hr-bg: #f8fafc;
      --hr-surface: #ffffff;
      --hr-surface-elevated: #f1f5f9;
      --hr-surface-hover: #f8fafc;
      --hr-text: #0f172a;
      --hr-text-secondary: #475569;
      --hr-muted: #64748b;
      --hr-border: #e2e8f0;
      --hr-border-subtle: #f1f5f9;
      --hr-radius-sm: 6px;
      --hr-radius-md: 10px;
      --hr-font-sans: 'Inter', sans-serif;
      --hr-font-mono: 'JetBrains Mono', monospace;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { background-color: var(--hr-bg); color: var(--hr-text); font-family: var(--hr-font-sans); display: flex; height: 100vh; overflow: hidden; }
    
    .sidebar { width: 250px; background: var(--hr-surface); border-right: 1px solid var(--hr-border); display: flex; flex-direction: column; flex-shrink: 0; }
    .brand-header { padding: 20px; display: flex; align-items: center; gap: 12px; border-bottom: 1px solid var(--hr-border); }
    .brand-badge { background: linear-gradient(135deg, #2563eb, #1d4ed8); color: #fff; font-weight: 800; font-size: 16px; padding: 6px 10px; border-radius: 8px; }
    .brand-title { font-weight: 700; font-size: 16px; color: var(--hr-text); }
    
    .nav-menu { list-style: none; padding: 16px 12px; flex: 1; display: flex; flex-direction: column; gap: 4px; }
    .nav-item a { display: flex; align-items: center; gap: 12px; padding: 10px 14px; color: var(--hr-text-secondary); text-decoration: none; border-radius: var(--hr-radius-sm); font-size: 13px; font-weight: 500; }
    .nav-item a:hover { background: var(--hr-surface-hover); color: var(--hr-text); }
    .nav-item.active a { background: var(--hr-primary-light); color: var(--hr-primary); font-weight: 600; border-left: 3px solid var(--hr-primary); }
    
    .main-wrapper { flex: 1; display: flex; flex-direction: column; height: 100vh; overflow: hidden; }
    .top-bar { height: 64px; background: var(--hr-surface); border-bottom: 1px solid var(--hr-border); display: flex; align-items: center; justify-content: space-between; padding: 0 28px; }
    .content-body { flex: 1; overflow-y: auto; padding: 28px; }
    .view-section { display: none; }
    .view-section.active { display: block; }

    .btn { display: inline-flex; align-items: center; gap: 8px; padding: 8px 16px; border-radius: var(--hr-radius-sm); font-size: 13px; font-weight: 600; cursor: pointer; border: none; }
    .btn-primary { background: var(--hr-primary); color: #fff; }
    .btn-primary:hover { background: var(--hr-primary-hover); }
    .btn-secondary { background: var(--hr-surface); color: var(--hr-text); border: 1px solid var(--hr-border); }
    .btn-secondary:hover { background: var(--hr-surface-hover); }

    .kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 16px; margin-bottom: 24px; }
    .kpi-card { background: var(--hr-surface); border: 1px solid var(--hr-border); border-radius: var(--hr-radius-md); padding: 20px; box-shadow: 0 1px 2px 0 rgba(0,0,0,0.03); }
    .kpi-label { font-size: 12px; color: var(--hr-muted); text-transform: uppercase; margin-bottom: 8px; font-weight: 600; }
    .kpi-val { font-size: 24px; font-weight: 800; font-family: var(--hr-font-mono); color: var(--hr-text); }

    .data-card { background: var(--hr-surface); border: 1px solid var(--hr-border); border-radius: var(--hr-radius-md); overflow: hidden; margin-bottom: 24px; box-shadow: 0 1px 2px 0 rgba(0,0,0,0.03); }
    .card-header { padding: 18px 22px; border-bottom: 1px solid var(--hr-border); display: flex; justify-content: space-between; align-items: center; }
    .card-title { font-size: 15px; font-weight: 700; color: var(--hr-text); }

    table { width: 100%; border-collapse: collapse; text-align: left; font-size: 13px; }
    th { padding: 12px 18px; background: #f8fafc; color: var(--hr-muted); font-weight: 600; border-bottom: 1px solid var(--hr-border); font-size: 11px; text-transform: uppercase; }
    td { padding: 14px 18px; border-bottom: 1px solid var(--hr-border); color: var(--hr-text); }
    tr:hover td { background: #f8fafc; }

    .badge { display: inline-flex; padding: 3px 8px; border-radius: 999px; font-size: 11px; font-weight: 600; }
    .badge-success { background: #ecfdf5; color: #10b981; }
    .badge-warning { background: #fffbeb; color: #f59e0b; }
    .badge-danger { background: #fef2f2; color: #ef4444; }
  </style>
</head>
<body>

  <aside class="sidebar">
    <div class="brand-header">
      <div class="brand-badge">HR</div>
      <div>
        <div class="brand-title">HR Bookings</div>
        <div style="font-size:11px; color:var(--hr-muted);">Appointment & Scheduling</div>
      </div>
    </div>
    <ul class="nav-menu">
      <li class="nav-item active" id="nav-dashboard"><a href="#dashboard" onclick="navigate('dashboard')">📊 Dashboard</a></li>
      <li class="nav-item" id="nav-appointments"><a href="#appointments" onclick="navigate('appointments')">📅 Appointments</a></li>
      <li class="nav-item" id="nav-staff"><a href="#staff" onclick="navigate('staff')">👥 Staff Rosters</a></li>
      <li class="nav-item" id="nav-services"><a href="#services" onclick="navigate('services')">✂️ Services & Buffer</a></li>
      <li class="nav-item" id="nav-customers"><a href="#customers" onclick="navigate('customers')">👤 Customer CRM</a></li>
      <li class="nav-item" id="nav-portal"><a href="/book" target="_blank">🌐 Public Booking Link ↗</a></li>
    </ul>
  </aside>

  <main class="main-wrapper">
    <header class="top-bar">
      <div style="font-size: 18px; font-weight: 700;" id="top-title">Dashboard Overview</div>
      <div style="display:flex; gap:10px;">
        <button class="btn btn-secondary" onclick="window.open('/api/export/csv')">📥 Export CSV</button>
        <button class="btn btn-primary" onclick="window.open('/book', '_blank')">+ New Appointment</button>
      </div>
    </header>

    <div class="content-body">
      
      <!-- 1. DASHBOARD VIEW -->
      <section id="view-dashboard" class="view-section active">
        <div class="kpi-grid">
          <div class="kpi-card">
            <div class="kpi-label">Today's Appointments</div>
            <div class="kpi-val" id="kpi-today">0</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">Upcoming Confirmed</div>
            <div class="kpi-val" id="kpi-upcoming">0</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">Total Booking Revenue</div>
            <div class="kpi-val" id="kpi-revenue" style="color:var(--accent-success);">£0.00</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-label">Completed Sessions</div>
            <div class="kpi-val" id="kpi-completed">0</div>
          </div>
        </div>

        <div style="display:grid; grid-template-columns: 2fr 1fr; gap: 20px;">
          <div class="data-card">
            <div class="card-header"><div class="card-title">Staff Utilization & Booking Counts</div></div>
            <div style="padding:20px;" id="staff-container"></div>
          </div>
          <div class="data-card">
            <div class="card-header"><div class="card-title">Top Requested Services</div></div>
            <div style="padding:20px;" id="services-container"></div>
          </div>
        </div>
      </section>

      <!-- 2. APPOINTMENTS VIEW -->
      <section id="view-appointments" class="view-section">
        <div class="data-card">
          <div class="card-header">
            <div class="card-title">Confirmed Schedule & Bookings</div>
          </div>
          <table>
            <thead>
              <tr>
                <th>Date & Time</th>
                <th>Service</th>
                <th>Specialist</th>
                <th>Customer</th>
                <th>Fee</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody id="appointments-tbody"></tbody>
          </table>
        </div>
      </section>

      <!-- 3. STAFF VIEW -->
      <section id="view-staff" class="view-section">
        <div class="data-card">
          <div class="card-header"><div class="card-title">Specialist Rosters & Shifts</div></div>
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Role</th>
                <th>Working Hours</th>
                <th>Break Time</th>
                <th>Contact</th>
              </tr>
            </thead>
            <tbody id="staff-tbody"></tbody>
          </table>
        </div>
      </section>

      <!-- 4. SERVICES VIEW -->
      <section id="view-services" class="view-section">
        <div class="data-card">
          <div class="card-header"><div class="card-title">Services, Durations & Buffers</div></div>
          <table>
            <thead>
              <tr>
                <th>Service Name</th>
                <th>Category</th>
                <th>Duration</th>
                <th>Buffer Time</th>
                <th>Price</th>
              </tr>
            </thead>
            <tbody id="services-tbody"></tbody>
          </table>
        </div>
      </section>

      <!-- 5. CUSTOMERS VIEW -->
      <section id="view-customers" class="view-section">
        <div class="data-card">
          <div class="card-header"><div class="card-title">Client Directory & Visit Histories</div></div>
          <table>
            <thead>
              <tr>
                <th>Customer Name</th>
                <th>Email / Phone</th>
                <th>Total Visits</th>
                <th>Total Spent</th>
                <th>Notes</th>
              </tr>
            </thead>
            <tbody id="customers-tbody"></tbody>
          </table>
        </div>
      </section>

    </div>
  </main>

  <script>
    function navigate(view) {
      document.querySelectorAll('.view-section').forEach(s => s.classList.remove('active'));
      document.querySelectorAll('.nav-item').forEach(i => i.classList.remove('active'));
      const sec = document.getElementById('view-' + view);
      const nav = document.getElementById('nav-' + view);
      if (sec) sec.classList.add('active');
      if (nav) nav.classList.add('active');
      loadAdminData();
    }

    async function loadAdminData() {
      // 1. Dashboard Stats
      const res = await fetch('/api/dashboard/stats');
      const data = await res.json();
      document.getElementById('kpi-today').innerText = data.today_bookings || 0;
      document.getElementById('kpi-upcoming').innerText = data.upcoming_appointments || 0;
      document.getElementById('kpi-revenue').innerText = '£' + (data.total_revenue || 0).toFixed(2);
      document.getElementById('kpi-completed').innerText = data.completed_appointments || 0;

      document.getElementById('staff-container').innerHTML = data.staff_breakdown.map(s => `
        <div style="display:flex; justify-content:space-between; padding:10px 0; border-bottom:1px solid var(--border-subtle); font-size:13px;">
          <div><strong>${s.name}</strong> <span style="font-size:11px; color:var(--text-muted);">(${s.role})</span></div>
          <div style="font-weight:700; font-family:var(--font-mono); color:var(--accent-primary);">${s.booking_count} sessions &bull; £${s.staff_revenue.toFixed(2)}</div>
        </div>
      `).join('');

      document.getElementById('services-container').innerHTML = data.popular_services.map(srv => `
        <div style="display:flex; justify-content:space-between; padding:10px 0; border-bottom:1px solid var(--border-subtle); font-size:13px;">
          <div><strong>${srv.name}</strong></div>
          <div style="font-weight:700; font-family:var(--font-mono);">${srv.count} booked</div>
        </div>
      `).join('');

      // 2. Appointments
      const aRes = await fetch('/api/bookings');
      const appointments = await aRes.json();
      document.getElementById('appointments-tbody').innerHTML = appointments.map(a => `
        <tr>
          <td><strong>${a.booking_date}</strong><br><span style="font-family:var(--font-mono); font-size:12px; color:var(--accent-primary);">${a.start_time} - ${a.end_time}</span></td>
          <td>${a.service_name}</td>
          <td>${a.staff_name}</td>
          <td><strong>${a.customer_name}</strong><br><span style="font-size:11px; color:var(--text-muted);">${a.customer_email}</span></td>
          <td style="font-family:var(--font-mono); font-weight:700;">£${a.price.toFixed(2)}</td>
          <td><span class="badge ${a.status === 'Confirmed' ? 'badge-success' : (a.status === 'Completed' ? 'badge-warning' : 'badge-danger')}">${a.status}</span></td>
          <td>
            ${a.status === 'Confirmed' ? `<button class="btn btn-secondary" style="padding:4px 8px; font-size:11px; color:var(--accent-danger);" onclick="cancelBooking(${a.id})">Cancel</button>` : '—'}
          </td>
        </tr>
      `).join('');

      // 3. Staff
      const stRes = await fetch('/api/staff');
      const staffList = await stRes.json();
      document.getElementById('staff-tbody').innerHTML = staffList.map(st => `
        <tr>
          <td><strong>${st.name}</strong></td>
          <td>${st.role}</td>
          <td style="font-family:var(--font-mono);">${st.start_time} - ${st.end_time}</td>
          <td style="font-family:var(--font-mono); color:var(--text-muted);">${st.break_start} - ${st.break_end}</td>
          <td>${st.email}<br>${st.phone || ''}</td>
        </tr>
      `).join('');

      // 4. Services
      const sRes = await fetch('/api/services');
      const serviceList = await sRes.json();
      document.getElementById('services-tbody').innerHTML = serviceList.map(s => `
        <tr>
          <td><strong>${s.name}</strong></td>
          <td>${s.category}</td>
          <td style="font-family:var(--font-mono);">${s.duration_minutes} mins</td>
          <td style="font-family:var(--font-mono); color:var(--accent-warning);">+${s.buffer_minutes} mins buffer</td>
          <td style="font-family:var(--font-mono); font-weight:700; color:var(--accent-success);">£${s.price.toFixed(2)}</td>
        </tr>
      `).join('');

      // 5. Customers
      const cRes = await fetch('/api/customers');
      const custList = await cRes.json();
      document.getElementById('customers-tbody').innerHTML = custList.map(c => `
        <tr>
          <td><strong>${c.name}</strong></td>
          <td>${c.email}<br>${c.phone || ''}</td>
          <td>${c.total_visits} visits</td>
          <td style="font-family:var(--font-mono); font-weight:700; color:var(--accent-success);">£${c.total_spent.toFixed(2)}</td>
          <td style="font-size:11px; color:var(--text-secondary);">${c.notes || '—'}</td>
        </tr>
      `).join('');
    }

    async function cancelBooking(id) {
      if (confirm('Cancel this appointment?')) {
        await fetch(`/api/appointments/${id}/cancel`, { method: 'PATCH' });
        loadAdminData();
      }
    }

    window.addEventListener('DOMContentLoaded', () => {
      loadAdminData();
      const hash = window.location.hash.replace('#', '') || 'dashboard';
      navigate(hash);
    });
  </script>
</body>
</html>
"""
