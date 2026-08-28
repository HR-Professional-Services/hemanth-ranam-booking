# HR Bookings — V1 Deployment & Operational Guide

## System Requirements
- **Runtime**: Python 3.10, 3.11, or 3.12
- **Port**: `8002`
- **Memory**: ~40MB RAM

---

## Environment Variables
| Variable | Default | Description |
| :--- | :--- | :--- |
| `PORT` | `8002` | Uvicorn listener port |
| `BOOKING_DB_PATH` | `booking.db` | SQLite database path |

---

## Startup Commands
```bash
# Development
python3 -m uvicorn src.app:app --host 0.0.0.0 --port 8002 --reload

# Production
python3 -m uvicorn src.app:app --host 0.0.0.0 --port 8002 --workers 2
```

## Health Check
```bash
curl http://127.0.0.1:8002/api/health
# Expected: {"status":"healthy","service":"HR Bookings"}
```

## Backup
```bash
sqlite3 booking.db ".backup 'booking_snapshot_$(date +%Y%m%d).db'"
```
