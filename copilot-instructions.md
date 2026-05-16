# Copilot Instructions

Use The Color Shop MVP rules as the baseline for all work in this repository.

## Mandatory context
- Load and follow [.github/instructions/django-mvp.instructions.md](.github/instructions/django-mvp.instructions.md) when changing Django models, views, forms, templates, settings, auth, checkout, or order flows.
- Load and follow [.github/instructions/product-inventory.instructions.md](.github/instructions/product-inventory.instructions.md) when changing products, variants, SKUs, stock, cart validation, or order-item behavior.
- Load and follow [.github/instructions/tcs-ecommerce.instructions.md](.github/instructions/tcs-ecommerce.instructions.md) for all customer/storefront/staff ecommerce work.
- Load and follow [.github/instructions/staff-admin-portal.instructions.md](.github/instructions/staff-admin-portal.instructions.md) when changing the custom `/staff/` portal, staff templates, staff CSS, or staff product-management workflows.

## Product architecture
- Treat `Product` as the merchandised product and `ProductVariant` as the sellable SKU.
- Treat Shopify-style `Option name + Option value` as the canonical variant model. Do not build new staff or storefront features around the legacy fixed `color`, `size`, or `finish` fields except for migration or compatibility work.
- Keep price and inventory at the sellable variant level unless a later task explicitly redesigns that rule.
- Preserve historical order-item snapshots when product or variant structures change.

## Staff portal direction
- Prefer the custom Bootstrap 5 `/staff/` portal over Django admin for all new operational UI work.
- Keep `/admin/` available as fallback until custom staff pages reach parity; do not remove it.
- Match the established staff shell direction: light sidebar, dark compact top bar, neutral workspace, dense editor cards, and responsive desktop/mobile behavior.

## Business constraints
- Phase 1 is pickup only.
- Phase 1 payment is cash at store.
- Do not add delivery, shipping, or online payment workflows unless explicitly requested.
- Keep store/pickup details aligned with Samoa operations and current environment-variable configuration.

## Validation loop
- After each substantive edit slice, run the narrowest useful validation first.
- Prefer: focused form/view test, render check, `python manage.py check`, then broader test runs.
- When changing product or staff editor behavior, validate real GET and POST paths, not just static analysis.
- When changing schema, create/apply migrations and verify existing data still works.

## Implementation preference
- Fix root causes, not just template symptoms.
- Keep migrations and compatibility paths explicit when replacing legacy product behavior.
- Do not introduce new always-on dependencies unless they are clearly justified by the task.

## Release packaging
- Build cPanel release archives from the repository root with `Set-ExecutionPolicy -Scope Process Bypass; .\scripts\package_release.ps1`.
- The app archive is `dist/tcs-app-release.zip` and must contain only `config/`, `shop/`, `templates/`, `static/`, `manage.py`, `requirements.txt`, `README.md`, `.env.example`, `.env.production.example`, and `passenger_wsgi.py`.
- The media bootstrap archive is `dist/tcs-media-bootstrap.zip` and is only emitted when the `media/` tree contains real files for first deployment or curated media refreshes.
- Never package `.env`, `.venv/`, `db.sqlite3`, `*.sqlite3`, `staticfiles/`, `__pycache__/`, `.git/`, or other local-only artifacts.
- For cPanel Application Manager, use `passenger_wsgi.py` as the startup file, `application` as the entry point, `/home/USERNAME/colourshop` as the expected app root pattern, and `colourshop.ws` as the production domain baseline unless the task explicitly changes it.
- For production setup, use `.env.production.example` as the starting template and leave only database and mail credentials blank unless the task explicitly changes that rule.
- On the current VPS, create the app virtual environment with `/opt/alt/python-internal/bin/python3.11 -m venv venv`, install from `requirements.txt`, and point the `passenger_wsgi.py` shebang at `/home/USERNAME/colourshop/venv/bin/python`.
