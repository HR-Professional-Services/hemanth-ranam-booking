# HR Bookings — Master V1 Architecture Specification

## Baseline
- **Product**: HR Bookings
- **Repository**: `hemanth-ranam-booking`
- **Port**: `8002` (Admin SPA) | `/book` (Public Booking Portal)
- **Version**: `1.0.0` | **Status**: 🔒 FINAL / LOCKED BASELINE

## Purpose
HR Bookings delivers a collision-free professional services appointment scheduling system with a public customer-facing booking wizard and a full staff management interface.

## Core Modules
1. **Collision-Free Availability Engine**: Interval-overlap algorithm guaranteeing zero double-bookings
2. **Public 4-Step Booking Wizard**: `/book` portal for client self-service reservations
3. **Specialist Schedule Management**: Working hours, capabilities, and daily load tracking
4. **Booking Lifecycle Manager**: `Confirmed → Completed / Cancelled / No-Show`
5. **Data Sovereignty Exporter**: CSV/JSON streams of complete booking ledger

## Technology Stack
- **Backend**: FastAPI, Python 3.12, Uvicorn ASGI
- **Database**: SQLite 3 WAL
- **Frontend**: Native HTML5 SPA + public booking wizard; no external framework
- **Theme**: Pure Light Mode Only

## Architecture Freeze
This repository is locked at V1. Future additions (e.g., email confirmation, SMS reminders, recurring bookings) must be implemented as additive endpoints without modifying existing booking or availability engine logic.
