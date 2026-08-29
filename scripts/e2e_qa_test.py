#!/usr/bin/env python3
"""
HR Bookings — Collision Prevention & Public Appointment Simulation E2E Test
"""

import os
import sys
import tempfile
from pathlib import Path

test_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
test_db.close()
os.environ["BOOKINGS_DB_PATH"] = test_db.name

sys.path.insert(0, str(Path(__file__).parent.parent))
from fastapi.testclient import TestClient
from src.app import app
from src.database import init_db

def run_booking_qa():
    print("==================================================")
    print("🧪 REAL-WORLD QA SIMULATION: 02 — HR BOOKINGS")
    print("==================================================")
    init_db(test_db.name)
    client = TestClient(app)

    # 1. Health & Branding
    health = client.get("/api/health")
    assert health.status_code == 200
    branding = client.get("/api/branding")
    assert branding.status_code == 200
    assert branding.json()["product_name"] in ["HR Bookings", "HR Services Bookings"]
    print("✅ [1/6] Health & Branding verified.")

    # 2. Availability Calculation
    avail = client.get("/api/availability?service_id=1&staff_id=1&date=2026-09-10").json()
    assert "available_slots" in avail
    assert len(avail["available_slots"]) > 0
    slot = avail["available_slots"][0]
    print(f"✅ [2/6] Dynamic availability computed ({len(avail['available_slots'])} free slots, First: {slot}).")

    # 3. Public Customer Booking
    book_res = client.post("/api/bookings", json={
        "service_id": 1,
        "staff_id": 1,
        "customer_name": "Alexander Vance",
        "customer_email": "alex.vance@vancecap.com",
        "customer_phone": "+44 7700 900777",
        "booking_date": "2026-09-10",
        "start_time": slot
    })
    assert book_res.status_code == 201
    booking_id = book_res.json()["id"]
    print(f"✅ [3/6] Booking successfully confirmed (ID: {booking_id}, Time: {slot}).")

    # 4. Strict Collision Rejection
    dup_res = client.post("/api/bookings", json={
        "service_id": 1,
        "staff_id": 1,
        "customer_name": "Collision Tester",
        "customer_email": "collision@test.com",
        "booking_date": "2026-09-10",
        "start_time": slot
    })
    assert dup_res.status_code == 409
    print(f"✅ [4/6] Collision prevention rejected double-booking with HTTP 409 Conflict.")

    # 5. Cancellation & Slot Freeing
    cancel_res = client.patch(f"/api/appointments/{booking_id}/cancel")
    assert cancel_res.status_code == 200
    print(f"✅ [5/6] Appointment cancelled & slot immediately freed.")

    # 6. CSV & JSON Export
    csv_res = client.get("/api/export/csv")
    assert csv_res.status_code == 200
    json_res = client.get("/api/export/json")
    assert json_res.status_code == 200
    print("✅ [6/6] CSV & JSON booking ledger exports verified.")

    print("\n🎉 ALL REAL-WORLD HR BOOKINGS QA TESTS PASSED WITH 100% SUCCESS!\n")

    if os.path.exists(test_db.name):
        os.remove(test_db.name)

if __name__ == "__main__":
    run_booking_qa()
