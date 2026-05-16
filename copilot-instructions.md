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
