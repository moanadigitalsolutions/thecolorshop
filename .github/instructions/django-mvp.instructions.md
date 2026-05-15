---
description: "Use when creating or modifying Django code for The Color Shop MVP, including models, views, forms, templates, admin, settings, authentication, cart, checkout, and order flows."
name: "Django MVP Guidelines"
applyTo: "**/*.py, **/*.html, **/*.env.example"
---

# Django MVP Guidelines

- Prefer a conventional Django app structure with server-rendered templates and Bootstrap for Phase 1.
- Use Django class-based or function-based views consistently with the surrounding app; choose the simpler option for the workflow being built.
- Keep business rules in models, services, forms, or managers rather than scattering order and inventory logic through templates.
- Use Django forms for validation-heavy customer and admin workflows, including registration, checkout, pickup details, and admin-side status changes.
- Require login before order placement. Public browsing is allowed, but checkout and order history should require authenticated customers.
- Use Django messages for customer-facing success and error feedback after cart, checkout, account, and admin actions.
- Keep secrets and deployment-specific values in environment variables. Do not hard-code Brevo keys, database credentials, Django secret keys, or production hostnames.
- Use SQLite-friendly code during development and MySQL-compatible model fields, indexes, constraints, and migrations for production.
- Register operational models in Django admin with useful list displays, filters, searches, and readonly fields for orders and email logs.
- Keep templates practical and mobile friendly: clear product lists, short checkout forms, visible pickup instructions, and obvious order status labels.
- Add focused tests around checkout, order creation, stock changes, authentication gates, and email-trigger behavior when those areas change.