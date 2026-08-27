import os
import json
import csv
import io
from datetime import datetime, timedelta, time
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from typing import Optional, List
from .database import get_db, init_db

app = FastAPI(
    title="HR Bookings — Hemanth Ranam Professional Services",
    description="Universal 24/7 Appointment & Availability Management System.",
    version="1.0.0"
)

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
        "brand_name": "Hemanth Ranam Professional Services",
        "product_name": "HR Bookings",
        "theme": {"primary_color": "#2563eb", "bg_canvas": "#ffffff"}
    }

@app.on_event("startup")
def on_startup():
    init_db()

# --- Pydantic Models ---
class ServiceCreate(BaseModel):
    name: str
    category: Optional[str] = "General"
    duration_minutes: int
    buffer_minutes: Optional[int] = 0
    price: Optional[float] = 0.0
    currency: Optional[str] = "USD"
    description: Optional[str] = ""

class StaffCreate(BaseModel):
    name: str
    email: str
    phone: Optional[str] = ""
    role: Optional[str] = "Specialist"
    working_days: Optional[str] = "1,2,3,4,5"
    start_time: Optional[str] = "09:00"
    end_time: Optional[str] = "17:00"

class PublicBookingRequest(BaseModel):
    service_id: int
    staff_id: int
    booking_date: Optional[str] = None # YYYY-MM-DD
    appointment_date: Optional[str] = None # YYYY-MM-DD
    start_time: str   # HH:MM
    customer_name: str
    customer_email: str
    customer_phone: Optional[str] = ""
    customer_notes: Optional[str] = ""
    notes: Optional[str] = ""

class AppointmentStatusUpdate(BaseModel):
    status: str # Confirmed, Completed, Cancelled, Rescheduled

# --- Helper Logic: Availability & Collision Prevention ---

def is_slot_available(service_id: int, staff_id: int, booking_date: str, start_time_str: str) -> bool:
    with get_db() as conn:
        cursor = conn.cursor()
        service = cursor.execute("SELECT duration_minutes, buffer_minutes FROM services WHERE id = ?", (service_id,)).fetchone()
        if not service:
            return False
        
        duration = service[0] + service[1] # total duration + buffer
        start_dt = datetime.strptime(f"{booking_date} {start_time_str}", "%Y-%m-%d %H:%M")
        end_dt = start_dt + timedelta(minutes=duration)
        end_time_str = end_dt.strftime("%H:%M")

        # Check existing active appointments for staff on this date
        query = """
        SELECT start_time, end_time FROM appointments
        WHERE staff_id = ? AND booking_date = ? AND status != 'Cancelled'
        """
        existing = cursor.execute(query, (staff_id, booking_date)).fetchall()
        for appt in existing:
            ex_start = datetime.strptime(f"{booking_date} {appt[0]}", "%Y-%m-%d %H:%M")
            ex_end = datetime.strptime(f"{booking_date} {appt[1]}", "%Y-%m-%d %H:%M")
            # Overlap check
            if (start_dt < ex_end) and (end_dt > ex_start):
                return False # Collision detected
    return True

# --- API Routes ---

@app.get("/api/health")
def health():
    return {
        "status": "healthy",
        "service": "HR Bookings",
        "version": "1.0.0",
        "database": "SQLite WAL"
    }

@app.get("/api/branding")
def branding():
    return load_branding()

@app.get("/api/stats")
def get_stats():
    with get_db() as conn:
        cursor = conn.cursor()
        total_services = cursor.execute("SELECT COUNT(*) FROM services WHERE active = 1").fetchone()[0]
        total_staff = cursor.execute("SELECT COUNT(*) FROM staff WHERE active = 1").fetchone()[0]
        total_appts = cursor.execute("SELECT COUNT(*) FROM appointments").fetchone()[0]
        confirmed_appts = cursor.execute("SELECT COUNT(*) FROM appointments WHERE status = 'Confirmed'").fetchone()[0]
        completed_appts = cursor.execute("SELECT COUNT(*) FROM appointments WHERE status = 'Completed'").fetchone()[0]
        total_revenue = cursor.execute("""
            SELECT COALESCE(SUM(s.price), 0.0) 
            FROM appointments a 
            JOIN services s ON a.service_id = s.id 
            WHERE a.status IN ('Confirmed', 'Completed')
        """).fetchone()[0]

    return {
        "total_services": total_services,
        "total_staff": total_staff,
        "total_appointments": total_appts,
        "confirmed_appointments": confirmed_appts,
        "completed_appointments": completed_appts,
        "total_revenue": total_revenue
    }

# Services
@app.get("/api/services")
def list_services():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM services WHERE active = 1 ORDER BY category, name").fetchall()
        return [dict(r) for r in rows]

@app.post("/api/services", status_code=201)
def create_service(service: ServiceCreate):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO services (name, category, duration_minutes, buffer_minutes, price, currency, description)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (service.name, service.category, service.duration_minutes, service.buffer_minutes, service.price, service.currency, service.description))
        conn.commit()
        return {"id": cursor.lastrowid, **service.model_dump()}

# Staff
@app.get("/api/staff")
def list_staff():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM staff WHERE active = 1 ORDER BY name").fetchall()
        return [dict(r) for r in rows]

@app.post("/api/staff", status_code=201)
def create_staff(staff: StaffCreate):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO staff (name, email, phone, role, working_days, start_time, end_time)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (staff.name, staff.email, staff.phone, staff.role, staff.working_days, staff.start_time, staff.end_time))
        conn.commit()
        return {"id": cursor.lastrowid, **staff.model_dump()}

# Availability Calculator
@app.get("/api/availability")
def get_available_slots(service_id: int, staff_id: int, date: str):
    """Calculates all open time slots for a given date and service provider."""
    with get_db() as conn:
        cursor = conn.cursor()
        staff = cursor.execute("SELECT start_time, end_time, working_days FROM staff WHERE id = ?", (staff_id,)).fetchone()
        service = cursor.execute("SELECT duration_minutes, buffer_minutes FROM services WHERE id = ?", (service_id,)).fetchone()
        
        if not staff or not service:
            raise HTTPException(status_code=404, detail="Staff or Service not found")

        # Parse day of week (Monday=1, Sunday=7)
        req_date = datetime.strptime(date, "%Y-%m-%d")
        day_of_week = str(req_date.isoweekday())
        working_days = staff[2].split(",")
        if day_of_week not in working_days:
            return {"date": date, "slots": [], "message": "Staff not working on this weekday"}

        duration = service[0] + service[1]
        start_hour, start_min = map(int, staff[0].split(":"))
        end_hour, end_min = map(int, staff[1].split(":"))
        
        current_dt = req_date.replace(hour=start_hour, minute=start_min)
        shift_end_dt = req_date.replace(hour=end_hour, minute=end_min)

        slots = []
        while current_dt + timedelta(minutes=duration) <= shift_end_dt:
            slot_str = current_dt.strftime("%H:%M")
            if is_slot_available(service_id, staff_id, date, slot_str):
                slots.append(slot_str)
            current_dt += timedelta(minutes=30) # standard 30-min stepping

        return {"date": date, "service_id": service_id, "staff_id": staff_id, "available_slots": slots}

# Appointments & Public Booking
@app.get("/api/appointments")
@app.get("/api/bookings")
def list_appointments(status: Optional[str] = None):
    with get_db() as conn:
        query = """
        SELECT a.*, s.name as service_name, s.price as service_price, st.name as staff_name, c.name as customer_name, c.email as customer_email, c.phone as customer_phone
        FROM appointments a
        JOIN services s ON a.service_id = s.id
        JOIN staff st ON a.staff_id = st.id
        JOIN customers c ON a.customer_id = c.id
        WHERE 1=1
        """
        params = []
        if status:
            query += " AND a.status = ?"
            params.append(status)
        query += " ORDER BY a.booking_date DESC, a.start_time DESC"
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

@app.post("/api/v1/public/book", status_code=201)
@app.post("/api/bookings", status_code=201)
@app.post("/api/appointments", status_code=201)
def public_book_appointment(req: PublicBookingRequest):
    """Public customer booking endpoint with collision validation."""
    target_date = req.booking_date or req.appointment_date
    if not target_date:
        raise HTTPException(status_code=400, detail="booking_date or appointment_date is required")
    target_notes = req.customer_notes or req.notes or ""

    if not is_slot_available(req.service_id, req.staff_id, target_date, req.start_time):
        raise HTTPException(status_code=409, detail="Selected slot is no longer available. Please choose another time.")

    with get_db() as conn:
        cursor = conn.cursor()
        
        # Get duration
        service = cursor.execute("SELECT duration_minutes, buffer_minutes FROM services WHERE id = ?", (req.service_id,)).fetchone()
        if not service:
            raise HTTPException(status_code=404, detail="Service not found")
        
        start_dt = datetime.strptime(f"{target_date} {req.start_time}", "%Y-%m-%d %H:%M")
        end_dt = start_dt + timedelta(minutes=service[0])
        end_time_str = end_dt.strftime("%H:%M")

        # Create or find customer
        cursor.execute("INSERT INTO customers (name, email, phone, notes) VALUES (?, ?, ?, ?)",
                       (req.customer_name, req.customer_email, req.customer_phone, target_notes))
        customer_id = cursor.lastrowid

        # Create appointment
        cursor.execute("""
        INSERT INTO appointments (service_id, staff_id, customer_id, booking_date, start_time, end_time, status, customer_notes)
        VALUES (?, ?, ?, ?, ?, ?, 'Confirmed', ?)
        """, (req.service_id, req.staff_id, customer_id, target_date, req.start_time, end_time_str, target_notes))
        appt_id = cursor.lastrowid
        conn.commit()

        return {
            "status": "success",
            "booking_status": "Confirmed",
            "id": appt_id,
            "booking_id": appt_id,
            "start_time": req.start_time,
            "end_time": end_time_str,
            "message": "Appointment confirmed successfully",
            "details": {
                "date": target_date,
                "time": f"{req.start_time} - {end_time_str}",
                "customer": req.customer_name
            }
        }

@app.put("/api/appointments/{appt_id}/status")
@app.put("/api/bookings/{appt_id}/status")
def update_status(appt_id: int, req: AppointmentStatusUpdate):
    with get_db() as conn:
        conn.execute("UPDATE appointments SET status = ? WHERE id = ?", (req.status, appt_id))
        conn.commit()
        return {"status": "updated", "id": appt_id, "new_status": req.status}

@app.put("/api/bookings/{appt_id}/cancel")
@app.put("/api/appointments/{appt_id}/cancel")
def cancel_appointment(appt_id: int):
    with get_db() as conn:
        conn.execute("UPDATE appointments SET status = 'Cancelled' WHERE id = ?", (appt_id,))
        conn.commit()
        return {"status": "cancelled", "id": appt_id}

# Export Endpoints (Data Sovereignty)
@app.get("/api/export/csv")
def export_csv():
    with get_db() as conn:
        rows = conn.execute("""
            SELECT a.id, a.booking_date, a.start_time, a.end_time, a.status, s.name, st.name, c.name, c.email, c.phone
            FROM appointments a
            JOIN services s ON a.service_id = s.id
            JOIN staff st ON a.staff_id = st.id
            JOIN customers c ON a.customer_id = c.id
            ORDER BY a.booking_date DESC
        """).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Date", "Start Time", "End Time", "Status", "Service", "Staff", "Customer Name", "Customer Email", "Customer Phone"])
    for r in rows:
        writer.writerow(list(r))
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=hr_bookings_export.csv"}
    )

@app.get("/api/export/json")
def export_json():
    with get_db() as conn:
        appts = [dict(r) for r in conn.execute("SELECT * FROM appointments").fetchall()]
        services = [dict(r) for r in conn.execute("SELECT * FROM services").fetchall()]
        staff = [dict(r) for r in conn.execute("SELECT * FROM staff").fetchall()]
        customers = [dict(r) for r in conn.execute("SELECT * FROM customers").fetchall()]
    return JSONResponse(content={
        "metadata": {"exporter": "Hemanth Ranam Professional Services - HR Bookings", "version": "1.0.0"},
        "appointments": appts,
        "bookings": appts,
        "services": services,
        "staff": staff,
        "customers": customers
    })

# HTML Dashboard & Public Booking App
UI_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>HR Bookings — Hemanth Ranam Professional Services</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Outfit:wght@500;600;700&display=swap" rel="stylesheet">
  <style>
    :root {
      --primary: #2563eb;
      --deep-blue: #1d4ed8;
      --canvas: #ffffff;
      --secondary-bg: #f8fafc;
      --card-border: #e2e8f0;
      --text-main: #0f172a;
      --text-muted: #64748b;
      --radius: 12px;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: 'Inter', sans-serif; background: var(--secondary-bg); color: var(--text-main); line-height: 1.5; }
    .header { background: rgba(255, 255, 255, 0.9); backdrop-filter: blur(10px); border-bottom: 1px solid var(--card-border); padding: 1rem 2rem; display: flex; justify-content: space-between; align-items: center; position: sticky; top: 0; z-index: 100; }
    .logo-badge { font-weight: 700; font-size: 1.25rem; color: var(--primary); display: flex; align-items: center; gap: 0.5rem; }
    .logo-badge span { background: var(--primary); color: white; padding: 0.25rem 0.5rem; border-radius: 6px; font-size: 0.875rem; }
    .btn { background: var(--primary); color: white; padding: 0.5rem 1rem; border-radius: 8px; border: none; font-weight: 500; cursor: pointer; transition: 0.2s; font-size: 0.875rem; }
    .btn:hover { background: var(--deep-blue); }
    .btn-secondary { background: white; color: var(--text-main); border: 1px solid var(--card-border); }
    .container { max-width: 1280px; margin: 2rem auto; padding: 0 1.5rem; }
    .metrics-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 1.25rem; margin-bottom: 2rem; }
    .metric-card { background: white; padding: 1.25rem; border-radius: var(--radius); border: 1px solid var(--card-border); }
    .metric-val { font-size: 1.75rem; font-weight: 700; margin-top: 0.25rem; }
    .card { background: white; border-radius: var(--radius); border: 1px solid var(--card-border); overflow: hidden; margin-bottom: 1.5rem; }
    table { width: 100%; border-collapse: collapse; text-align: left; }
    th { background: var(--secondary-bg); padding: 0.875rem 1.25rem; font-size: 0.75rem; text-transform: uppercase; color: var(--text-muted); border-bottom: 1px solid var(--card-border); }
    td { padding: 1rem 1.25rem; border-bottom: 1px solid var(--card-border); font-size: 0.875rem; }
    .badge { display: inline-block; padding: 0.25rem 0.5rem; border-radius: 9999px; font-size: 0.75rem; font-weight: 600; background: #eff6ff; color: var(--primary); }
    .badge-confirmed { background: #ecfdf5; color: #059669; }
    .booking-wizard { padding: 2rem; }
    .form-group { margin-bottom: 1.25rem; }
    .form-group label { display: block; font-weight: 600; font-size: 0.875rem; margin-bottom: 0.5rem; }
    .form-control { width: 100%; padding: 0.625rem; border-radius: 8px; border: 1px solid var(--card-border); font-family: inherit; }
    .slot-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(80px, 1fr)); gap: 0.5rem; margin-top: 0.5rem; }
    .slot-btn { background: var(--secondary-bg); border: 1px solid var(--card-border); padding: 0.5rem; border-radius: 6px; cursor: pointer; text-align: center; font-size: 0.8125rem; font-weight: 600; }
    .slot-btn.selected { background: var(--primary); color: white; border-color: var(--primary); }
  </style>
</head>
<body>
  <header class="header">
    <div class="logo-badge"><span>HR</span> HR Bookings Engine</div>
    <div>
      <button class="btn btn-secondary" onclick="window.location.href='/api/export/csv'">Export CSV</button>
      <button class="btn btn-secondary" onclick="window.location.href='/api/export/json'">Full Backup</button>
    </div>
  </header>

  <div class="container">
    <div class="metrics-grid">
      <div class="metric-card"><small style="color:var(--text-muted);">Active Services</small><div class="metric-val" id="m-serv">--</div></div>
      <div class="metric-card"><small style="color:var(--text-muted);">Staff Members</small><div class="metric-val" id="m-staff">--</div></div>
      <div class="metric-card"><small style="color:var(--text-muted);">Total Appointments</small><div class="metric-val" id="m-appt">--</div></div>
      <div class="metric-card"><small style="color:var(--text-muted);">Projected Revenue</small><div class="metric-val" id="m-rev" style="color:#059669;">$0.00</div></div>
    </div>

    <div style="display: grid; grid-template-columns: 1fr 1.2fr; gap: 1.5rem;">
      <div class="card booking-wizard">
        <h3 style="margin-bottom: 1.25rem;">Book Appointment (24/7 Client Wizard)</h3>
        <form id="booking-form" onsubmit="submitBooking(event)">
          <div class="form-group">
            <label>1. Select Service</label>
            <select id="b-service" class="form-control" onchange="fetchSlots()"></select>
          </div>
          <div class="form-group">
            <label>2. Select Specialist / Provider</label>
            <select id="b-staff" class="form-control" onchange="fetchSlots()"></select>
          </div>
          <div class="form-group">
            <label>3. Select Date</label>
            <input type="date" id="b-date" class="form-control" onchange="fetchSlots()" required>
          </div>
          <div class="form-group">
            <label>4. Available Time Slot</label>
            <div id="slots-container" class="slot-grid">Select service, staff & date to view open slots.</div>
            <input type="hidden" id="selected-slot" required>
          </div>
          <div class="form-group">
            <label>5. Customer Full Name</label>
            <input type="text" id="c-name" class="form-control" placeholder="e.g. Eleanor Vance" required>
          </div>
          <div class="form-group">
            <label>6. Email Address</label>
            <input type="email" id="c-email" class="form-control" placeholder="e.g. eleanor@example.com" required>
          </div>
          <button type="submit" class="btn" style="width: 100%; padding: 0.75rem;">Confirm & Reserve Appointment</button>
        </form>
      </div>

      <div class="card">
        <div style="padding: 1.25rem; border-bottom: 1px solid var(--card-border); font-weight: 700;">Live Appointment Schedule</div>
        <table>
          <thead>
            <tr>
              <th>Date & Time</th>
              <th>Customer</th>
              <th>Service</th>
              <th>Staff</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody id="appts-tbody">
            <tr><td colspan="5" style="text-align: center; color: var(--text-muted);">Loading appointments...</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>

  <script>
    let services = [];
    let staffList = [];

    async function loadInit() {
      const statsRes = await fetch('/api/stats');
      const stats = await statsRes.json();
      document.getElementById('m-serv').innerText = stats.total_services;
      document.getElementById('m-staff').innerText = stats.total_staff;
      document.getElementById('m-appt').innerText = stats.total_appointments;
      document.getElementById('m-rev').innerText = '$' + Number(stats.total_revenue).toLocaleString();

      const servRes = await fetch('/api/services');
      services = await servRes.json();
      document.getElementById('b-service').innerHTML = services.map(s => `<option value="${s.id}">${s.name} (${s.duration_minutes}m - $${s.price})</option>`).join('');

      const staffRes = await fetch('/api/staff');
      staffList = await staffRes.json();
      document.getElementById('b-staff').innerHTML = staffList.map(st => `<option value="${st.id}">${st.name} — ${st.role}</option>`).join('');

      // Set default tomorrow date
      const tomorrow = new Date();
      tomorrow.setDate(tomorrow.getDate() + 1);
      document.getElementById('b-date').value = tomorrow.toISOString().split('T')[0];

      await fetchSlots();
      await loadAppts();
    }

    async function fetchSlots() {
      const sId = document.getElementById('b-service').value;
      const stId = document.getElementById('b-staff').value;
      const dt = document.getElementById('b-date').value;
      if (!sId || !stId || !dt) return;

      const res = await fetch(`/api/availability?service_id=${sId}&staff_id=${stId}&date=${dt}`);
      const data = await res.json();
      const container = document.getElementById('slots-container');
      
      if (!data.available_slots || data.available_slots.length === 0) {
        container.innerHTML = '<span style="color:var(--text-muted); font-size:0.875rem;">No open slots on this date.</span>';
        document.getElementById('selected-slot').value = '';
        return;
      }

      container.innerHTML = data.available_slots.map(slot => `
        <div class="slot-btn" onclick="selectSlot('${slot}', this)">${slot}</div>
      `).join('');
    }

    function selectSlot(slot, el) {
      document.querySelectorAll('.slot-btn').forEach(b => b.classList.remove('selected'));
      el.classList.add('selected');
      document.getElementById('selected-slot').value = slot;
    }

    async function loadAppts() {
      const res = await fetch('/api/appointments');
      const data = await res.json();
      const tbody = document.getElementById('appts-tbody');
      if (data.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: var(--text-muted);">No appointments booked yet.</td></tr>';
        return;
      }
      tbody.innerHTML = data.map(a => `
        <tr>
          <td><strong>${a.booking_date}</strong><br><small style="color: var(--text-muted);">${a.start_time} - ${a.end_time}</small></td>
          <td><strong>${a.customer_name}</strong><br><small style="color: var(--text-muted);">${a.customer_email}</small></td>
          <td>${a.service_name}</td>
          <td>${a.staff_name}</td>
          <td><span class="badge ${a.status === 'Confirmed' ? 'badge-confirmed' : ''}">${a.status}</span></td>
        </tr>
      `).join('');
    }

    async function submitBooking(e) {
      e.preventDefault();
      const slot = document.getElementById('selected-slot').value;
      if (!slot) {
        alert("Please select an available time slot.");
        return;
      }

      const payload = {
        service_id: parseInt(document.getElementById('b-service').value),
        staff_id: parseInt(document.getElementById('b-staff').value),
        booking_date: document.getElementById('b-date').value,
        start_time: slot,
        customer_name: document.getElementById('c-name').value,
        customer_email: document.getElementById('c-email').value,
        customer_phone: "",
        customer_notes: "Booked via Universal Web Wizard"
      };

      const res = await fetch('/api/v1/public/book', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload)
      });

      if (res.ok) {
        alert("🎉 Appointment successfully booked and confirmed!");
        document.getElementById('c-name').value = '';
        document.getElementById('c-email').value = '';
        await fetchSlots();
        await loadAppts();
      } else {
        const err = await res.json();
        alert("Booking error: " + err.detail);
      }
    }

    window.onload = loadInit;
  </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
def index():
    return UI_HTML
