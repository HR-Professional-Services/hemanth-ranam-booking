# HR Bookings — V1 Database Schema

## Storage Architecture
- **Engine**: SQLite 3
- **Journal Mode**: `WAL` (Write-Ahead Logging)
- **Foreign Keys**: Enforced via `PRAGMA foreign_keys = ON;`
- **Default Database File**: `booking.db` (overrideable via `BOOKING_DB_PATH`)

---

## Entity Relationship & Table DDL

### 1. `users` (Staff / Specialists)
```sql
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    full_name TEXT NOT NULL,
    role TEXT DEFAULT 'Specialist', -- 'Admin', 'Specialist'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 2. `services` (Bookable Professional Services)
```sql
CREATE TABLE IF NOT EXISTS services (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    duration_min INTEGER NOT NULL DEFAULT 60,
    price_gbp REAL NOT NULL DEFAULT 150.0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 3. `specialists` (Consultants & Practitioners)
```sql
CREATE TABLE IF NOT EXISTS specialists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    phone TEXT,
    title TEXT NOT NULL,
    bio TEXT,
    working_hours_start TEXT DEFAULT '09:00',
    working_hours_end TEXT DEFAULT '17:00',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 4. `specialist_services` (M:N Specialist Capabilities)
```sql
CREATE TABLE IF NOT EXISTS specialist_services (
    specialist_id INTEGER REFERENCES specialists(id) ON DELETE CASCADE,
    service_id INTEGER REFERENCES services(id) ON DELETE CASCADE,
    PRIMARY KEY (specialist_id, service_id)
);
```

### 5. `bookings` (Confirmed Client Appointments)
```sql
CREATE TABLE IF NOT EXISTS bookings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    booking_reference TEXT UNIQUE NOT NULL,
    service_id INTEGER REFERENCES services(id) ON DELETE RESTRICT,
    specialist_id INTEGER REFERENCES specialists(id) ON DELETE RESTRICT,
    booking_date DATE NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    client_name TEXT NOT NULL,
    client_email TEXT NOT NULL,
    client_phone TEXT,
    status TEXT DEFAULT 'Confirmed', -- 'Confirmed', 'Completed', 'Cancelled', 'No-Show'
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## Seed Data Baseline
On initial initialization:
- **Services**:
  1. `Enterprise Architecture Consultation` (60 min — £250.00)
  2. `Multi-Tenant Migration Review` (90 min — £350.00)
  3. `Financial Controls & Ledger Audit` (45 min — £180.00)
- **Specialists**:
  1. `Daniel Carter` (Principal Business Consultant)
  2. `Sarah Mitchell` (Head of Enterprise Engineering)
  3. `Olivia Bennett` (Client Operations Lead)
