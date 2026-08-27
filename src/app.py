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
        "brand_name": "HR",
        "product_name": "HR Bookings",
        "author": "Hemanth Ranam",
        "primary_color": "#06b6d4",
        "dark_bg": "#090d16",
        "surface_bg": "#101726"
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
  <title>Book an Appointment — HR Bookings</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@500;700&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg-app: #090d16;
      --bg-surface: #101726;
      --bg-surface-elevated: #162035;
      --accent-primary: #06b6d4;
      --accent-primary-hover: #0891b2;
      --accent-success: #10b981;
      --accent-danger: #ef4444;
      --text-primary: #f8fafc;
      --text-secondary: #94a3b8;
      --text-muted: #64748b;
      --border-subtle: #1e293b;
      --radius-sm: 8px;
      --radius-md: 12px;
      --font-sans: 'Inter', sans-serif;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { background-color: var(--bg-app); color: var(--text-primary); font-family: var(--font-sans); min-height: 100vh; display: flex; justify-content: center; align-items: center; padding: 20px; }
    .portal-card { background: var(--bg-surface); border: 1px solid var(--border-subtle); border-radius: var(--radius-md); width: 100%; max-width: 620px; padding: 32px; box-shadow: 0 25px 50px -12px rgba(0,0,0,0.6); }
    .brand-header { display: flex; align-items: center; gap: 12px; margin-bottom: 24px; padding-bottom: 16px; border-bottom: 1px solid var(--border-subtle); }
    .brand-badge { background: linear-gradient(135deg, #0891b2, #06b6d4); color: #fff; font-weight: 800; padding: 6px 12px; border-radius: 8px; font-size: 15px; }
    .step-title { font-size: 15px; font-weight: 700; color: var(--accent-primary); margin-bottom: 12px; text-transform: uppercase; letter-spacing: 0.5px; }
    .form-group { margin-bottom: 16px; }
    .form-label { display: block; font-size: 12px; font-weight: 600; color: var(--text-secondary); margin-bottom: 6px; }
    .form-select, .form-input, .form-textarea { width: 100%; background: #0b111e; border: 1px solid var(--border-subtle); border-radius: var(--radius-sm); padding: 11px 14px; color: var(--text-primary); font-size: 14px; font-family: inherit; }
    .form-select:focus, .form-input:focus { outline: none; border-color: var(--accent-primary); }
    .slots-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(90px, 1fr)); gap: 10px; margin-top: 10px; }
    .slot-btn { background: var(--bg-surface-elevated); border: 1px solid var(--border-subtle); border-radius: 6px; padding: 10px; color: var(--text-primary); font-family: var(--font-sans); font-size: 13px; font-weight: 600; cursor: pointer; text-align: center; transition: all 0.15s; }
    .slot-btn:hover { border-color: var(--accent-primary); }
    .slot-btn.selected { background: var(--accent-primary); color: #090d16; font-weight: 700; border-color: var(--accent-primary); }
    .btn-submit { width: 100%; background: var(--accent-primary); color: #090d16; font-weight: 800; font-size: 15px; padding: 13px; border: none; border-radius: var(--radius-sm); cursor: pointer; transition: all 0.15s; margin-top: 10px; }
    .btn-submit:hover { background: var(--accent-primary-hover); box-shadow: 0 0 15px rgba(6,182,212,0.4); }
    .confirmed-box { background: rgba(16,185,129,0.1); border: 1px solid var(--accent-success); border-radius: var(--radius-sm); padding: 24px; text-align: center; display: none; }
  </style>
</head>
<body>

  <div class="portal-card">
    <div class="brand-header">
      <div class="brand-badge">HR</div>
      <div>
        <div style="font-weight: 700; font-size: 18px;">HR Bookings</div>
        <div style="font-size: 12px; color: var(--text-muted);">Self-Service Appointment Portal</div>
      </div>
    </div>

    <form id="public-booking-form" onsubmit="submitPublicBooking(event)">
      
      <!-- Step 1: Select Service & Specialist -->
      <div class="form-group">
        <label class="form-label">1. Select Required Service</label>
        <select class="form-select" id="pub-service" onchange="updateAvailability()" required>
          <option value="">-- Choose a Service --</option>
        </select>
      </div>

      <div class="form-group">
        <label class="form-label">2. Select Specialist</label>
        <select class="form-select" id="pub-staff" onchange="updateAvailability()" required>
          <option value="">-- Choose a Specialist --</option>
        </select>
      </div>

      <!-- Step 2: Select Date & Available Slot -->
      <div class="form-group">
        <label class="form-label">3. Select Appointment Date</label>
        <input type="date" class="form-input" id="pub-date" onchange="updateAvailability()" required>
      </div>

      <div class="form-group">
        <label class="form-label">4. Available Time Slots (Collision-Free Guarantee)</label>
        <div class="slots-grid" id="slots-container">
          <div style="color:var(--text-muted); font-size:12px; grid-column:1/-1;">Please pick a service, specialist, and date to view live openings.</div>
        </div>
        <input type="hidden" id="selected-slot" required>
      </div>

      <!-- Step 3: Customer Details -->
      <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px;">
        <div class="form-group">
          <label class="form-label">Your Full Name</label>
          <input type="text" class="form-input" id="pub-name" placeholder="e.g. Oliver Queen" required>
        </div>
        <div class="form-group">
          <label class="form-label">Email Address</label>
          <input type="email" class="form-input" id="pub-email" placeholder="oliver@example.com" required>
        </div>
      </div>

      <div class="form-group">
        <label class="form-label">Phone Number</label>
        <input type="tel" class="form-input" id="pub-phone" placeholder="+44 7700 900000">
      </div>

      <button type="submit" class="btn-submit" id="btn-confirm">Confirm & Reserve Appointment</button>
    </form>

    <div class="confirmed-box" id="confirm-box">
      <div style="font-size:36px; margin-bottom:10px;">🎉</div>
      <h3 style="color:var(--accent-success); margin-bottom:8px;">Appointment Confirmed!</h3>
      <div id="confirm-details" style="font-size:13px; color:var(--text-secondary); line-height:1.6;"></div>
      <button class="btn-submit" style="margin-top:20px; background:var(--bg-surface-elevated); color:var(--text-primary);" onclick="location.reload()">Book Another Appointment</button>
    </div>
  </div>

  <script>
    let selectedTime = null;

    async function initPublicPortal() {
      // Set min date to today
      const today = new Date().toISOString().split('T')[0];
      document.getElementById('pub-date').min = today;
      document.getElementById('pub-date').value = today;

      // Load Services
      const sRes = await fetch('/api/services');
      const services = await sRes.json();
      document.getElementById('pub-service').innerHTML = '<option value="">-- Choose a Service --</option>' + 
        services.map(s => `<option value="${s.id}">${s.name} (${s.duration_minutes}m) — £${s.price.toFixed(2)}</option>`).join('');

      // Load Staff
      const stRes = await fetch('/api/staff');
      const staff = await stRes.json();
      document.getElementById('pub-staff').innerHTML = '<option value="">-- Choose a Specialist --</option>' + 
        staff.map(st => `<option value="${st.id}">${st.name} (${st.role})</option>`).join('');
    }

    async function updateAvailability() {
      const sId = document.getElementById('pub-service').value;
      const stId = document.getElementById('pub-staff').value;
      const date = document.getElementById('pub-date').value;
      const container = document.getElementById('slots-container');

      if (!sId || !stId || !date) {
        container.innerHTML = '<div style="color:var(--text-muted); font-size:12px; grid-column:1/-1;">Please select service, specialist, and date.</div>';
        return;
      }

      container.innerHTML = '<div style="color:var(--accent-primary); font-size:12px; grid-column:1/-1;">Computing collision-free availability...</div>';

      try {
        const res = await fetch(`/api/availability?service_id=${sId}&staff_id=${stId}&date=${date}`);
        const data = await res.json();
        
        if (!data.available_slots || data.available_slots.length === 0) {
          container.innerHTML = '<div style="color:var(--accent-danger); font-size:12px; grid-column:1/-1;">No available openings on this date. Please try another day.</div>';
          selectedTime = null;
          return;
        }

        container.innerHTML = data.available_slots.map(slot => `
          <div class="slot-btn ${slot === selectedTime ? 'selected' : ''}" onclick="selectSlot('${slot}', this)">${slot}</div>
        `).join('');
      } catch (err) {
        container.innerHTML = '<div style="color:var(--accent-danger); font-size:12px; grid-column:1/-1;">Error loading availability.</div>';
      }
    }

    function selectSlot(time, el) {
      selectedTime = time;
      document.getElementById('selected-slot').value = time;
      document.querySelectorAll('.slot-btn').forEach(b => b.classList.remove('selected'));
      el.classList.add('selected');
    }

    async function submitPublicBooking(e) {
      e.preventDefault();
      if (!selectedTime) {
        alert('Please choose an available time slot.');
        return;
      }

      const payload = {
        service_id: parseInt(document.getElementById('pub-service').value),
        staff_id: parseInt(document.getElementById('pub-staff').value),
        booking_date: document.getElementById('pub-date').value,
        start_time: selectedTime,
        customer_name: document.getElementById('pub-name').value,
        customer_email: document.getElementById('pub-email').value,
        customer_phone: document.getElementById('pub-phone').value
      };

      const res = await fetch('/api/bookings', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload)
      });

      if (res.status === 201) {
        const data = await res.json();
        document.getElementById('public-booking-form').style.display = 'none';
        document.getElementById('confirm-box').style.display = 'block';
        document.getElementById('confirm-details').innerHTML = `
          <strong>${data.service}</strong> with <strong>${data.staff}</strong><br>
          Date: <strong>${data.date}</strong> at <strong>${data.start_time} - ${data.end_time}</strong><br>
          Total Fee: <strong>£${data.price.toFixed(2)}</strong><br>
          A calendar invitation has been reserved for ${payload.customer_name}.
        `;
      } else {
        const err = await res.json();
        alert('Booking conflict: ' + (err.detail || 'Selected slot is no longer free.'));
        updateAvailability();
      }
    }

    window.addEventListener('DOMContentLoaded', initPublicPortal);
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
      --bg-app: #090d16;
      --bg-surface: #101726;
      --bg-surface-elevated: #162035;
      --bg-surface-hover: #1c2a45;
      --accent-primary: #06b6d4;
      --accent-primary-hover: #0891b2;
      --accent-success: #10b981;
      --accent-warning: #f59e0b;
      --accent-danger: #ef4444;
      --text-primary: #f8fafc;
      --text-secondary: #94a3b8;
      --text-muted: #64748b;
      --border-subtle: #1e293b;
      --radius-sm: 6px;
      --radius-md: 10px;
      --font-sans: 'Inter', sans-serif;
      --font-mono: 'JetBrains Mono', monospace;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { background-color: var(--bg-app); color: var(--text-primary); font-family: var(--font-sans); display: flex; height: 100vh; overflow: hidden; }
    
    .sidebar { width: 260px; background: var(--bg-surface); border-right: 1px solid var(--border-subtle); display: flex; flex-direction: column; flex-shrink: 0; }
    .brand-header { padding: 20px; display: flex; align-items: center; gap: 12px; border-bottom: 1px solid var(--border-subtle); }
    .brand-badge { background: linear-gradient(135deg, #0891b2, #06b6d4); color: #fff; font-weight: 800; font-size: 16px; padding: 6px 10px; border-radius: 8px; }
    .brand-title { font-weight: 700; font-size: 16px; }
    
    .nav-menu { list-style: none; padding: 16px 12px; flex: 1; display: flex; flex-direction: column; gap: 4px; }
    .nav-item a { display: flex; align-items: center; gap: 12px; padding: 10px 14px; color: var(--text-secondary); text-decoration: none; border-radius: var(--radius-sm); font-size: 13px; font-weight: 500; }
    .nav-item a:hover { background: var(--bg-surface-hover); color: var(--text-primary); }
    .nav-item.active a { background: rgba(6, 182, 212, 0.15); color: var(--accent-primary); font-weight: 600; border-left: 3px solid var(--accent-primary); }
    
    .main-wrapper { flex: 1; display: flex; flex-direction: column; height: 100vh; overflow: hidden; }
    .top-bar { height: 64px; background: var(--bg-surface); border-bottom: 1px solid var(--border-subtle); display: flex; align-items: center; justify-content: space-between; padding: 0 28px; }
    .content-body { flex: 1; overflow-y: auto; padding: 28px; }
    .view-section { display: none; }
    .view-section.active { display: block; }

    .btn { display: inline-flex; align-items: center; gap: 8px; padding: 8px 16px; border-radius: var(--radius-sm); font-size: 13px; font-weight: 600; cursor: pointer; border: none; }
    .btn-primary { background: var(--accent-primary); color: #090d16; font-weight: 700; }
    .btn-secondary { background: var(--bg-surface-elevated); color: var(--text-primary); border: 1px solid var(--border-subtle); }

    .kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; margin-bottom: 24px; }
    .kpi-card { background: var(--bg-surface); border: 1px solid var(--border-subtle); border-radius: var(--radius-md); padding: 20px; }
    .kpi-label { font-size: 12px; color: var(--text-secondary); text-transform: uppercase; margin-bottom: 8px; }
    .kpi-val { font-size: 24px; font-weight: 800; font-family: var(--font-mono); }

    .data-card { background: var(--bg-surface); border: 1px solid var(--border-subtle); border-radius: var(--radius-md); overflow: hidden; margin-bottom: 24px; }
    .card-header { padding: 18px 22px; border-bottom: 1px solid var(--border-subtle); display: flex; justify-content: space-between; align-items: center; }
    .card-title { font-size: 15px; font-weight: 700; }

    table { width: 100%; border-collapse: collapse; text-align: left; font-size: 13px; }
    th { padding: 12px 18px; background: rgba(0,0,0,0.25); color: var(--text-secondary); font-weight: 600; border-bottom: 1px solid var(--border-subtle); font-size: 11px; text-transform: uppercase; }
    td { padding: 14px 18px; border-bottom: 1px solid var(--border-subtle); }
    tr:hover td { background: var(--bg-surface-hover); }

    .badge { display: inline-flex; padding: 3px 8px; border-radius: 999px; font-size: 11px; font-weight: 600; }
    .badge-success { background: rgba(16,185,129,0.15); color: #10b981; }
    .badge-warning { background: rgba(245,158,11,0.15); color: #f59e0b; }
    .badge-danger { background: rgba(239,68,68,0.15); color: #ef4444; }
  </style>
</head>
<body>

  <aside class="sidebar">
    <div class="brand-header">
      <div class="brand-badge">HR</div>
      <div>
        <div class="brand-title">HR Bookings</div>
        <div style="font-size:11px; color:var(--text-muted);">Scheduling Control</div>
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
