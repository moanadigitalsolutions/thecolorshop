---
description: "Use when building or refactoring the custom Bootstrap 5 staff portal, including /staff/ views, product-management workflows, staff templates, admin.css, and staff-side validation loops."
name: "Staff Admin Portal Guidelines"
applyTo: "shop/staff_*.py, shop/forms.py, templates/staff/**, static/css/admin.css, shop/tests.py, copilot-instructions.md"
---

# Staff Admin Portal Guidelines

- Build staff-facing operational UI in the custom `/staff/` portal first. Treat Django admin as fallback, not the primary experience.
- Use Bootstrap 5 and the shared staff shell. Keep the visual language dense, flat, and operational rather than marketing-styled.
- Favor a compact dark top bar, light sidebar, neutral content canvas, and stacked editor cards with a right-side secondary rail where appropriate.
- Keep staff-only protection explicit with the existing `staff_required` decorator or the nearest equivalent.
- Use Django forms and formsets for validation-heavy editor workflows. Keep save logic transactional in views or service helpers.
- For product management, treat Shopify-style `Option name + Option value` as the canonical variant workflow. Do not add new staff features that depend on legacy fixed variant fields except for migration or compatibility.
- When evolving the product editor, prefer small end-to-end slices: schema or form contract, then template wiring, then validation.
- Preserve compatibility for existing storefront, cart, and order behavior while the staff portal is migrating to the new model set.
- Add focused tests for new staff GET/POST flows, especially product create/edit, option handling, and route protection.
- After changing staff views, forms, or templates, run a narrow validation loop before widening scope: render check, focused POST, `python manage.py check`, then broader tests if needed.
- Avoid broad visual rewrites that do not also preserve or improve the operational workflow. The goal is usable staff product management, not a cosmetic skin.
