# HR Bookings — V1 Frontend Architecture

## Design System & Theme
- **Theme**: 100% Light Mode Only (`#F8FAFC` page canvas, `#FFFFFF` cards)
- **Primary Color**: `#2563EB`, Hover: `#1D4ED8`
- **Typography**: Inter, System UI; JetBrains Mono for time values and fees
- **Micro-Interactions**: 150ms transitions; animated calendar grid; slot highlight on hover

---

## Internal Admin SPA Views
The staff-facing admin UI uses the standard HR SPA shell with fixed 250px sidebar and `navigate(view)`:

1. **`view-dashboard`**: Today's bookings timeline, upcoming appointment queue, utilisation KPIs (slots booked vs available).
2. **`view-bookings`**: Full appointment ledger with specialist filter, date range filter, status badge filter, Cancel action.
3. **`view-services`**: Service card grid with duration, fee, and assigned specialists.
4. **`view-specialists`**: Specialist profile cards showing working hours, assigned services, and today's schedule.
5. **`view-reports`**: Booking volume by service, by specialist, revenue by period, CSV/JSON export actions.

---

## Public Customer Booking Portal (`/book`)
A 4-step wizard with step indicator, designed for embedding in client-facing websites:
1. **Step 1 — Select Service**: Service cards with duration and fee badge.
2. **Step 2 — Select Specialist**: Filtered by service capability; profile photo fallback initials.
3. **Step 3 — Select Date & Time**: Calendar date picker → live availability slot fetch from `/api/availability`.
4. **Step 4 — Confirm Details**: Client name, email, phone, notes; booking confirmation modal with `booking_reference`.

**Collision Prevention UX**: If a slot is taken between user browsing and submitting, the API returns `409 Conflict` and the wizard resets to Step 3 with an explanatory message.

---

## State Management
- `window.location.hash` for admin SPA view routing (`#bookings`, `#services`, `#specialists`)
- Wizard step controlled via `currentStep` JS variable; no hash routing on the public `/book` page
- All fetch calls wrapped in `try/catch` with toast notifications for network errors
