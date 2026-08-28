# HR Bookings — V1 Backend Architecture

## Framework & Lifecycles
- **Web Engine**: FastAPI (Python 3.10+), Uvicorn ASGI
- **Entrypoint**: `src/app.py`
- **Static Public Portal**: `GET /book` served via `FileResponse` or inline Jinja template

---

## Collision-Free Availability Engine
The core booking engine runs in `compute_availability(specialist_id, service_id, date)`:

1. Fetch specialist's `working_hours_start` and `working_hours_end` from the `specialists` table.
2. Generate candidate slots at 60-minute intervals across the working day.
3. Query the `bookings` table for all `Confirmed` records matching `specialist_id` and `booking_date`.
4. For each candidate slot, compute its `end_time` (based on `service.duration_min`).
5. Remove any candidate slot where `[start, end]` overlaps with any booked `[booked_start, booked_end]` interval.
6. Return remaining free slots as an ordered array of `HH:MM` strings.

**Conflict Detection Criteria**: Two time windows overlap when `new_start < existing_end AND new_end > existing_start`.

---

## Booking Lifecycle Flow
```
POST /api/bookings
  → Validate request body (Pydantic)
  → Re-run compute_availability() atomically
  → If slot still free: INSERT into bookings, generate booking_reference (BK-YYYY-XXXXX)
  → If slot taken: RETURN 409 Conflict
  → RETURN 201 Created with booking_reference
```

---

## Validation & Error Handling
- `422 Unprocessable Entity`: Missing required fields (client_name, client_email, booking_date, start_time)
- `409 Conflict`: Time slot occupied by another confirmed booking
- `404 Not Found`: Specialist or Service not found
- `400 Bad Request`: Date is in the past
