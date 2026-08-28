# HR Bookings — V1 Development Guide

## Local Setup
```bash
cd products/hemanth-ranam-booking
pip install fastapi uvicorn pydantic httpx pytest
python3 -m uvicorn src.app:app --host 127.0.0.1 --port 8002 --reload
```

## Public Booking Portal
Open `http://localhost:8002/book` in browser to test the customer-facing 4-step wizard.

## Run E2E Tests
```bash
python3 scripts/e2e_qa_test.py
```
Expected:
```
✅ [1/6] Health & Branding verified.
✅ [2/6] Dynamic availability computed.
✅ [3/6] Booking confirmed.
✅ [4/6] Collision prevention rejected double-booking (409).
✅ [5/6] Appointment cancelled.
✅ [6/6] CSV & JSON exports verified.
🎉 ALL REAL-WORLD HR BOOKINGS QA TESTS PASSED WITH 100% SUCCESS!
```
