# HR Bookings — Hemanth Ranam Professional Services

[![CI](https://github.com/HR-Professional-Services/hemanth-ranam-booking/actions/workflows/ci.yml/badge.svg)](https://github.com/HR-Professional-Services/hemanth-ranam-booking/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE-COMPLIANCE.md)
[![Zero Monthly Cost](https://img.shields.io/badge/Hosting-Zero--Cost%20Tier-success.svg)](DEPLOYMENT.md)

> **"Universal 24/7 appointment scheduling, staff availability, and double-booking collision prevention engine."**

---

## 🌟 Executive Overview
**HR Bookings** is a turnkey, self-hosted appointment and service reservation platform engineered by **Hemanth Ranam Professional Services**. Designed for dental practices, aesthetic clinics, salons, barbershops, consultants, tutors, and field service professionals, it allows customers to book appointments 24/7 directly through your website without expensive monthly subscription fees like Calendly, Acuity, or Fresha ($30–$100/mo).

---

## 💼 Core Business Features
* **Public 24/7 Client Booking Wizard**: Seamless mobile-friendly appointment booking in 4 easy steps.
* **Double-Booking Collision Prevention**: Real-time slot math accounts for service duration, transition buffers, and staff shifts.
* **Multi-Staff & Multi-Service Catalog**: Individual working hours, days off, pricing, and category filters.
* **Rescheduling & Cancellation Engine**: Automated status updates and client notification hooks.
* **Revenue & Capacity Analytics**: Track projected revenue, completed appointments, and staff utilization.
* **100% Client Data Sovereignty**: Instant CSV & JSON database export.

---

## 🎨 White-Label Branding
Configure brand styling, default currencies, timezones, and slot intervals in `src/branding.json`.

---

## 🚀 Quickstart Installation
```bash
# 1. Clone repo
git clone https://github.com/HR-Professional-Services/hemanth-ranam-booking.git
cd hemanth-ranam-booking

# 2. Install dependencies
pip install -r requirements.txt

# 3. Seed demo data
python scripts/seed_demo_data.py

# 4. Start server
uvicorn src.app:app --reload --port 8000
```
Visit [http://localhost:8000](http://localhost:8000) for the live booking wizard & admin dashboard.

---

## 🐳 Docker Deployment
```bash
docker build -t hemanth-ranam-booking .
docker run -d -p 8000:8000 -v $(pwd)/data:/app/data --name hr-booking hemanth-ranam-booking
```

---

## 📦 Client Handover Suite
* [CLIENT-ONBOARDING.md](client/CLIENT-ONBOARDING.md)
* [SETUP-CHECKLIST.md](client/SETUP-CHECKLIST.md)
* [HANDOVER.md](client/HANDOVER.md)
* [ADMIN-GUIDE.md](client/ADMIN-GUIDE.md)
* [USER-GUIDE.md](client/USER-GUIDE.md)
* [TRAINING.md](client/TRAINING.md)
* [SUPPORT.md](client/SUPPORT.md)

---

## 🏛️ Commercial Inquiries
**Hemanth Ranam Professional Services**  
* **Live Hub**: [https://app.hemanth-ranam.workers.dev/](https://app.hemanth-ranam.workers.dev/)  
* **Direct Contact**: [hemanth.ranam@gmail.com](mailto:hemanth.ranam@gmail.com) | WhatsApp: `+91 7675815245`
