---
description: "Use when designing or modifying product catalog, paint variants, SKUs, inventory, stock movement, cart validation, or order item behavior for The Color Shop."
name: "Product and Inventory Guidelines"
applyTo: "**/*.py, **/*.html, **/*.md"
---

# Product and Inventory Guidelines

- Model a base product separately from sellable variants. A variant should represent the purchasable SKU, such as paint color, size, finish, or other stocked option.
- Store SKU, price, active status, and stock quantity on the sellable variant unless a clear business rule requires product-level values.
- Let categories organize browsing, but do not use categories as substitutes for colors, sizes, finishes, or inventory-bearing variants.
- Keep stock validation close to cart and checkout logic so customers cannot place pickup orders for unavailable quantities.
- When an order is placed, preserve the product and variant names, SKU, unit price, and selected options on the order item for historical accuracy.
- Use explicit inventory states or fields that support admin work, such as in stock, low stock, inactive, or out of stock.
- Make admin search and filtering work for product name, variant attributes, SKU, category, stock state, and active status.
- Treat manual admin stock edits as the Phase 1 default. Add automated inventory alerts, purchase orders, or supplier workflows only when requested.
- Keep the customer UI clear when variants exist: require a valid variant choice before adding to cart and show stock availability without exposing internal admin-only details.