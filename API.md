# HR Bookings — V1 API Specification

## Overview
- **Service Name**: HR Bookings
- **Port**: 8002
- **Public Booking Portal**: `http://localhost:8002/book`
- **Protocol**: HTTP/1.1 REST JSON + Server-Rendered Wizard
- **Status**: 🔒 V1 Locked

---

## Endpoint Reference

### 1. System & Health
#### `GET /api/health`
- **Description**: Returns microservice reachability and SQLite database status.
- **Response**: `200 OK` (`{"status": "healthy", "service": "HR Bookings", "version": "2.0.0"}`)

#### `GET /api/branding`
- **Description**: Returns branding tokens, currency symbols (`£`), and appointment rules.
- **Response**: `200 OK`

---

### 2. Services & Specialist Directory
#### `GET /api/services`
- **Description**: Lists all bookable professional advisory services with duration (minutes) and fee (GBP).
- **Response**: `200 OK` (Array of Service objects)

#### `GET /api/specialists`
- **Description**: Lists all active specialists, consultants, and their assigned service specialties.
- **Response**: `200 OK` (Array of Specialist objects)

---

### 3. Collision-Free Availability Engine
#### `GET /api/availability`
- **Description**: Computes real-time, non-overlapping available appointment time slots for a given specialist, service duration, and date.
- **Parameters**:
  - `specialist_id` (required, integer): Specialist ID
  - `service_id` (required, integer): Service ID
  - `date` (required, string): Target date (`YYYY-MM-DD`)
- **Response**: `200 OK`
```json
{
  "date": "2026-08-28",
  "specialist_id": 1,
  "service_duration_min": 60,
  "available_slots": [
    "09:00", "10:00", "11:00", "13:00", "14:00", "15:00", "16:00"
  ],
  "booked_count": 1
}
```

---

### 4. Booking Reservations & Lifecycle
#### `GET /api/bookings`
- **Description**: Retrieves all confirmed appointments with filtering by specialist, status, or date range.
- **Response**: `200 OK`

#### `POST /api/bookings`
- **Description**: Confirms and locks an appointment. Validates that the requested specialist is free; if occupied, rejects with `409 Conflict`.
- **Request Body**:
```json
{
  "service_id": 1,
  "specialist_id": 1,
  "booking_date": "2026-08-28",
  "start_time": "09:00",
  "client_name": "Oliver Queen",
  "client_email": "oliver@example.com",
  "client_phone": "+44 7700 900000",
  "notes": "Quarterly cloud infrastructure strategy review"
}
```
- **Response**: `201 Created` (`{"id": 4, "booking_reference": "BK-2026-88910", "status": "Confirmed"}`)
- **Error Response**: `409 Conflict` (`{"detail": "Time slot collision: Specialist is already booked at this time."}`)

#### `DELETE /api/bookings/{booking_id}`
- **Description**: Cancels an appointment and immediately frees the time slot for new reservations.
- **Response**: `200 OK` (`{"status": "Cancelled", "id": 4}`)

---

### 5. Calendar Exports & Data Sovereignty
#### `GET /api/export/csv`
- **Description**: Downloads complete appointment records in CSV format.
- **Response**: `200 OK` (`text/csv`)

#### `GET /api/export/json`
- **Description**: Exports full booking state in JSON format.
- **Response**: `200 OK` (`application/json`)
