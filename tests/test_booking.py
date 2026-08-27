import pytest
import os
import tempfile
from fastapi.testclient import TestClient
from src.app import app
from src.database import init_db

@pytest.fixture
def client():
    test_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    test_db.close()
    os.environ["BOOKINGS_DB_PATH"] = test_db.name
    init_db(test_db.name)
    with TestClient(app) as c:
        yield c
    if os.path.exists(test_db.name):
        try:
            os.remove(test_db.name)
        except Exception:
            pass

def test_health_and_branding(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["service"] == "HR Bookings"

    b_res = client.get("/api/branding")
    assert b_res.status_code == 200
    assert b_res.json()["product_name"] == "HR Bookings"

def test_services_and_staff(client):
    services = client.get("/api/services").json()
    assert len(services) >= 1

    staff = client.get("/api/staff").json()
    assert len(staff) >= 1

def test_collision_prevention(client):
    # Book slot at 10:00
    res1 = client.post("/api/bookings", json={
        "service_id": 1,
        "staff_id": 1,
        "customer_name": "Test User",
        "customer_email": "test@user.com",
        "booking_date": "2026-10-10",
        "start_time": "10:00"
    })
    assert res1.status_code == 201

    # Overlapping booking attempt (should collide and return 409)
    res2 = client.post("/api/bookings", json={
        "service_id": 1,
        "staff_id": 1,
        "customer_name": "Duplicate User",
        "customer_email": "dup@user.com",
        "booking_date": "2026-10-10",
        "start_time": "10:00"
    })
    assert res2.status_code == 409

def test_public_booking_ui(client):
    res = client.get("/book")
    assert res.status_code == 200
    assert "HR Bookings" in res.text
