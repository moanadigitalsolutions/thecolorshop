---
description: "Build or refine a bounded slice of The Color Shop staff admin portal, then immediately recheck it with focused validation before moving on."
name: "TCS Staff Admin Build And Recheck"
argument-hint: "Describe the specific staff-admin slice to implement"
agent: "agent"
---

Implement the requested slice of The Color Shop custom staff admin portal.

Before coding:
- Load [.github/instructions/django-mvp.instructions.md](../instructions/django-mvp.instructions.md)
- Load [.github/instructions/product-inventory.instructions.md](../instructions/product-inventory.instructions.md) when the slice touches products, variants, SKUs, inventory, or order-item behavior.
- Load [.github/instructions/tcs-ecommerce.instructions.md](../instructions/tcs-ecommerce.instructions.md)
- Load [.github/instructions/staff-admin-portal.instructions.md](../instructions/staff-admin-portal.instructions.md)
- Load [copilot-instructions.md](../../copilot-instructions.md)

Workflow:
1. Read only the smallest set of files needed to identify the controlling code path.
2. State one falsifiable local hypothesis about how the slice should work or what is missing.
3. Make the smallest end-to-end code change that tests that hypothesis.
4. Immediately run the narrowest useful validation for that slice.
5. If the validation fails, repair the same slice and rerun the same check before widening scope.
6. If the validation succeeds, report what changed, what passed, and any remaining nearby gap.

Requirements:
- Prefer the custom `/staff/` Bootstrap 5 portal over Django admin for new UI work.
- Keep `/admin/` available as fallback.
- Preserve pickup-only and cash-at-store business rules.
- Treat Shopify-style `Option name + Option value` as the canonical product variant model.
- When changing product editor behavior, validate with a real staff GET and POST path, not only static analysis.
- When changing schema, create/apply migrations and confirm existing data compatibility.

Return:
- Short implementation summary
- Files changed
- Validation performed
- Remaining immediate risk or next slice
