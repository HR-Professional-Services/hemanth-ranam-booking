# DEPLOYMENT GUIDE — HR BOOKINGS

**System**: HR Bookings (Product 06)  
**Provider**: Hemanth Ranam Professional Services  
**Source Hub**: [https://app.hemanth-ranam.workers.dev/](https://app.hemanth-ranam.workers.dev/)

---

## 1. Hosting Tier Classifications

| Tier | Environment | Runtime / Stack | Database | Monthly Cost | Best For |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Tier A (Recommended)** | Cloudflare Pages + Serverless | Python / Node / Edge | SQLite WAL / Cloudflare D1 | **$0.00 / month** | Clinics, Salons, Tutors (< 10,000 appts/mo) |
| **Tier B** | Fly.io / Render / Docker | Python FastAPI Container | Persistent SQLite / Postgres | **$0.00 - $5.00 / month** | Multi-location businesses |
| **Tier C** | Client-Owned Dedicated Server | Docker Compose + Nginx | PostgreSQL 16 | **$10.00 / month** | Hospital networks, high volume practices |

---

## 2. Fast Deployment via Docker Compose
```bash
git clone https://github.com/HR-Professional-Services/hemanth-ranam-booking.git
cd hemanth-ranam-booking
docker compose up -d --build
```

---

## 3. Cloudflare DNS & SSL Setup
1. Map `book.clientdomain.com` as an `A` record pointing to the container IP.
2. Ensure Proxy Status is `Proxied` (Orange Cloud) for automatic free SSL and global Edge caching.
