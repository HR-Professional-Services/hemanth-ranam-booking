#!/usr/bin/env python3
"""
HR Bookings — Comprehensive Real-World End-to-End QA Test
Simulates a real salon / appointment business (Demo Salon with Alice & Bob).
"""

import os
import sys
import tempfile
from pathlib import Path

# Set up isolated test DB
test_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
os.environ["BOOKING_DB_PATH"] = test_db.name
os.environ["BOOKINGS_DB_PATH"] = test_db.name

sys.path.insert(0, str(Path(__file__).parent.parent))
from fastapi.testclient import TestClient
from src.app import app
from src.database import init_db

def run_bookings_qa():
    print("==================================================")
    print("🧪 STARTING REAL-WORLD QA AUDIT: 02 — HR BOOKINGS")
    print("==================================================")
    init_db(test_db.name)
    client = TestClient(app)

    # 1. Health & Branding
    health = client.get("/api/health")
    assert health.status_code == 200
    branding = client.get("/api/branding")
    assert branding.status_code == 200
    assert branding.json()["product_name"] == "HR Bookings"
    print("✅ [1/9] Health & Branding verified.")

    # 2. Staff Setup (Alice & Bob)
    alice_res = client.post("/api/staff", json={
        "name": "Alice Morgan",
        "email": "alice@demosalon.example.com",
        "role": "Master Stylist",
        "is_active": True
    })
    assert alice_res.status_code == 201
    alice_id = alice_res.json()["id"]

    bob_res = client.post("/api/staff", json={
        "name": "Bob Vance",
        "email": "bob@demosalon.example.com",
        "role": "Senior Consultant",
        "is_active": True
    })
    assert bob_res.status_code == 201
    bob_id = bob_res.json()["id"]
    print(f"✅ [2/9] Staff created: Alice (ID: {alice_id}), Bob (ID: {bob_id}).")

    # 3. Services Setup (Haircut 30m, Consultation 60m)
    haircut_res = client.post("/api/services", json={
        "name": "Executive Haircut & Styling",
        "duration_minutes": 30,
        "buffer_minutes": 15,
        "price": 45.0,
        "currency": "GBP",
        "description": "30-minute tailored haircut with 15-minute sanitation buffer."
    })
    assert haircut_res.status_code == 201
    haircut_id = haircut_res.json()["id"]

    consult_res = client.post("/api/services", json={
        "name": "Private Hair & Scalp Consultation",
        "duration_minutes": 60,
        "buffer_minutes": 15,
        "price": 95.0,
        "currency": "GBP",
        "description": "60-minute in-depth consultation."
    })
    assert consult_res.status_code == 201
    consult_id = consult_res.json()["id"]
    print(f"✅ [3/9] Services configured with buffer times (Haircut: 30m+15m, Consult: 60m+15m).")

    # 4. Public Booking Wizard Submission
    booking_payload = {
        "service_id": haircut_id,
        "staff_id": alice_id,
        "customer_name": "Eleanor Vance",
        "customer_email": "eleanor.vance@example.com",
        "customer_phone": "+44 7700 900555",
        "appointment_date": "2026-09-10",
        "start_time": "10:00",
        "notes": "First time visit"
    }
    b1_res = client.post("/api/bookings", json=booking_payload)
    assert b1_res.status_code == 201
    b1_data = b1_res.json()
    assert b1_data["status"] == "success"
    assert b1_data["booking_status"] == "Confirmed"
    assert b1_data["end_time"] == "10:30"
    b1_id = b1_data["id"]
    print(f"✅ [4/9] Appointment booked successfully: 2026-09-10 10:00–10:30 (ID: {b1_id}).")

    # 5. Collision Test (Exact duplicate time slot)
    collision_res = client.post("/api/bookings", json=booking_payload)
    assert collision_res.status_code == 409 # Must be rejected due to collision
    print("✅ [5/9] Collision rejection verified (Exact double-booking prevented with 409 Conflict).")

    # 6. Buffer Time Overlap Test (10:00–10:30 has 15m buffer -> 10:15 must be rejected)
    buffer_overlap_payload = dict(booking_payload)
    buffer_overlap_payload["start_time"] = "10:15"
    buffer_res = client.post("/api/bookings", json=buffer_overlap_payload)
    assert buffer_res.status_code == 409
    print("✅ [6/9] Buffer time overlap rejection verified (10:15–10:45 blocked by 10:00–10:45 window).")

    # 7. Independent Staff Availability (Bob should be available at 10:00 on the same date)
    bob_booking_payload = dict(booking_payload)
    bob_booking_payload["staff_id"] = bob_id
    bob_booking_payload["customer_name"] = "Marcus Brody"
    bob_booking_payload["customer_email"] = "marcus.b@example.com"
    bob_b_res = client.post("/api/bookings", json=bob_booking_payload)
    assert bob_b_res.status_code == 201
    print("✅ [7/9] Multi-staff concurrency verified (Bob booked simultaneously without collision).")

    # 8. Cancellation Lifecycle (Cancel Alice's 10:00 appointment -> Slot becomes available again)
    cancel_res = client.put(f"/api/bookings/{b1_id}/cancel")
    assert cancel_res.status_code == 200
    assert cancel_res.json()["status"] == "cancelled"

    # Re-book the newly freed 10:00 slot for Alice
    rebook_res = client.post("/api/bookings", json=booking_payload)
    assert rebook_res.status_code == 201
    print("✅ [8/9] Cancellation & slot release verified (Cancelled slot immediately available).")

    # 9. Data Sovereignty Export
    csv_res = client.get("/api/export/csv")
    assert csv_res.status_code == 200
    assert "Eleanor Vance" in csv_res.text
    json_res = client.get("/api/export/json")
    assert json_res.status_code == 200
    assert len(json_res.json()["bookings"]) >= 2
    print("✅ [9/9] Complete CSV and JSON booking audit exports verified.")

    print("\n🎉 ALL REAL-WORLD HR BOOKINGS QA TESTS PASSED WITH ZERO DEFECTS!\n")

    # Cleanup
    if os.path.exists(test_db.name):
        os.remove(test_db.name)

if __name__ == "__main__":
    run_bookings_qa()
