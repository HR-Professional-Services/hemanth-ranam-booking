# HR Bookings — V1 Security Policy

## Implemented Security Controls

### SQL Injection Defense
All queries use parameterized `?` placeholders exclusively. No string formatting into SQL.

### Booking Reference Uniqueness
`booking_reference` is generated as `BK-{year}-{random_5digits}` with a `UNIQUE` DB constraint; duplicate references are rejected at the database layer.

### Time Slot Atomicity
Availability check and booking insert run in the same SQLite WAL transaction, preventing double-booking from concurrent requests.

### Input Validation
Pydantic schemas validate all incoming payloads. Invalid email formats, past dates, and missing required fields return `422 Unprocessable Entity` before any DB operation.

---

## Future Security Roadmap (V2)
- Staff authentication with session tokens for the admin panel
- Rate limiting on `POST /api/bookings` to prevent spam from the public portal
- CAPTCHA integration on `/book` customer-facing form
- Booking confirmation email with cancellation token link
