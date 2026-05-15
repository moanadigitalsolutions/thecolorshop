---
description: "Create a deployment checklist for The Color Shop Django app on a VPS using cPanel Application Manager, MySQL, environment variables, static files, and production checks."
name: "TCS cPanel Deployment Checklist"
argument-hint: "Deployment target or environment details"
agent: "agent"
---

Create a practical deployment checklist for The Color Shop Django eCommerce app using cPanel Application Manager on a VPS.

Use the project rules in [.github/instructions/tcs-ecommerce.instructions.md](../instructions/tcs-ecommerce.instructions.md) and cover:

- Production MySQL database setup and credentials
- Environment variables for Django, database, allowed hosts, CSRF origins, Brevo API, and email sender settings
- Python virtual environment and dependency installation
- cPanel Application Manager setup, app entry point, restart steps, and log locations
- Django migrations, superuser creation, static file collection, media/image handling, and file permissions
- HTTPS, domain, pickup-only order flow, cash-at-store payment, and Brevo email verification checks
- Smoke tests for customer registration, product browsing, cart, checkout, order emails, admin order update, and status email
- Rollback and backup notes appropriate for a small VPS-hosted Django store

Return the checklist grouped by stage: pre-deployment, cPanel setup, Django release tasks, production verification, and rollback.