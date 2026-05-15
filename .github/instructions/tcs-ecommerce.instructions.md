---
description: "Use when building The Color Shop eCommerce platform, especially Django, product catalog, cart, checkout, pickup orders, admin workflows, Brevo email, SQLite/MySQL, or cPanel deployment work."
name: "The Color Shop eCommerce Guidelines"
applyTo: "**/*.py, **/*.html, **/*.css, **/*.js, **/*.ts, **/*.md, **/*.env.example"
---

# The Color Shop eCommerce Guidelines

- Build for The Color Shop in Apia, Samoa: 569J+3VH, Togafu'afu'a Rd, Apia, Samoa; contact +68525577.
- Prefer Django templates with Bootstrap for the Phase 1 frontend. Use Django's built-in admin, authentication, ORM, and template support unless the user explicitly chooses an API-first architecture later.
- Use SQLite for local development and MySQL for production. Keep database access behind Django models and migrations so the database swap stays straightforward.
- Phase 1 is pickup only. Do not add delivery, shipping rates, shipping addresses, or courier workflows unless the user explicitly asks for a later phase.
- Phase 1 payment is cash at store. Orders are created online without a payment gateway, and admin users manually confirm payment after pickup.
- Require customer authentication for ordering. Support local Samoa customers and overseas Samoan customers ordering for family pickup in Samoa.
- Checkout should collect pickup-specific details, including pickup name and notes or special instructions when useful.
- Use order statuses that fit the cash-on-pickup flow, such as pending pickup payment, ready for pickup, completed, and cancelled.
- Send order confirmation and status-update emails through the Brevo API. Keep email credentials in environment variables and avoid hard-coding secrets.
- Model paint variants such as colors, sizes, finishes, and related SKUs as first-class product/inventory concepts in the MVP so stock tracking stays accurate.
- Admin workflows should prioritize product, variant/SKU, category, inventory, order, customer, and email-log management.
- Keep the MVP focused: product catalog, categories, search/filtering, cart, pickup checkout, order history/status, admin management, email notifications, mobile responsiveness, and basic SEO.
- Treat online payments, delivery/shipping, loyalty features, multi-branch support, advanced reporting, SMS, promo codes, and saved recipient details as Phase 2 unless requested.
- Design customer-facing UI for a practical retail store: clear product browsing, mobile-friendly checkout, plain pickup instructions, and minimal friction for overseas users.
- Prepare deployment for a VPS using cPanel Application Manager, with production settings configured through environment variables.