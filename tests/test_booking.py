import pytest
import os
import tempfile
from datetime import datetime, timedelta
from fastapi.testclient import TestClient

test_db_file = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
test_db_path = test_db_file.name
os.environ["BOOKING_DB_PATH"] = test_db_path

from src.app import app
from src.database import init_db

@pytest.fixture(scope="module", autouse=True)
def setup_test_db():
    init_db(test_db_path)
    yield
    if os.path.exists(test_db_path):
        os.remove(test_db_path)

@pytest.fixture
def client():
    return TestClient(app)

def test_health_check(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["service"] == "HR Bookings"

def test_service_and_staff_creation(client):
    s_res = client.post("/api/services", json={
        "name": "Consulting Session",
        "category": "Advisory",
        "duration_minutes": 60,
        "buffer_minutes": 15,
        "price": 300.0,
        "currency": "USD"
    })
    assert s_res.status_code == 201
    service_id = s_res.json()["id"]

    st_res = client.post("/api/staff", json={
        "name": "Hemanth Ranam",
        "email": "hemanth.ranam@example.com",
        "role": "Principal Consultant",
        "working_days": "1,2,3,4,5,6,7",
        "start_time": "09:00",
        "end_time": "17:00"
    })
    assert st_res.status_code == 201
    staff_id = st_res.json()["id"]

    # Check availability calculation
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    avail_res = client.get(f"/api/availability?service_id={service_id}&staff_id={staff_id}&date={tomorrow}")
    assert avail_res.status_code == 200
    slots = avail_res.json()["available_slots"]
    assert len(slots) > 0
    assert "10:00" in slots

def test_public_booking_and_double_booking_prevention(client):
    # Retrieve created service and staff
    services = client.get("/api/services").json()
    staff = client.get("/api/staff").json()
    s_id = services[0]["id"]
    st_id = staff[0]["id"]
    test_date = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d")

    booking_payload = {
        "service_id": s_id,
        "staff_id": st_id,
        "booking_date": test_date,
        "start_time": "10:00",
        "customer_name": "Oliver Queen",
        "customer_email": "oliver@starling.com",
        "customer_phone": "+1 555 1234",
        "customer_notes": "First time booking"
    }

    # First booking succeeds
    book_res = client.post("/api/v1/public/book", json=booking_payload)
    assert book_res.status_code == 201
    assert book_res.json()["status"] == "success"

    # Second booking at SAME time slot must fail with 409 Conflict
    conflict_res = client.post("/api/v1/public/book", json=booking_payload)
    assert conflict_res.status_code == 409
    assert "no longer available" in conflict_res.json()["detail"]

def test_export_endpoints(client):
    csv_res = client.get("/api/export/csv")
    assert csv_res.status_code == 200
    assert "text/csv" in csv_res.headers["content-type"]

    json_res = client.get("/api/export/json")
    assert json_res.status_code == 200
    assert "appointments" in json_res.json()
