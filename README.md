# Hemanth Ranam — Appointment & Booking System Blueprint

High-performance appointment scheduling and calendar booking platform for consultants, clinics, agencies, and professional service teams.

---

## 📅 Features
* **Multi-Calendar Sync**: Google Calendar, Microsoft Outlook, CalDAV.
* **Custom Booking Links**: Round-robin staff assignment, group bookings, paid appointments via Stripe/Razorpay.
* **Automated Reminders**: SMS and Email notifications with automated rescheduling links.
* **Webhooks & CRM Integration**: Direct lead creation into `hemanth-ranam-crm`.

---

## 🏛️ Deployment Architecture
* **Stack**: Next.js, Node.js, Prisma, PostgreSQL
* **Cloudflare Role**: SSL, Edge Caching, Custom Subdomain (`booking.clientdomain.com`)

**Author**: Hemanth Ranam  
**Website**: [https://app.hemanth-ranam.workers.dev/](https://app.hemanth-ranam.workers.dev/)
