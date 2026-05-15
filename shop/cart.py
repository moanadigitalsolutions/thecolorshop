from decimal import Decimal

from django.conf import settings

from .models import ProductVariant


class Cart:
    def __init__(self, request):
        self.session = request.session
        cart = self.session.get(settings.CART_SESSION_ID)
        if cart is None:
            cart = self.session[settings.CART_SESSION_ID] = {}
        self.cart = cart

    def add(self, variant, quantity=1, override_quantity=False):
        variant_id = str(variant.id)
        quantity = max(1, int(quantity))
        current_quantity = int(self.cart.get(variant_id, 0))
        new_quantity = quantity if override_quantity else current_quantity + quantity
        if new_quantity > variant.stock_quantity:
            raise ValueError(f'Only {variant.stock_quantity} available for {variant.sku}.')
        self.cart[variant_id] = new_quantity
        self.save()

    def save(self):
        self.session.modified = True

    def remove(self, variant):
        variant_id = str(variant.id)
        if variant_id in self.cart:
            del self.cart[variant_id]
            self.save()

    def clear(self):
        self.session[settings.CART_SESSION_ID] = {}
        self.cart = self.session[settings.CART_SESSION_ID]
        self.save()

    def quantities(self):
        return {variant_id: int(quantity) for variant_id, quantity in self.cart.items()}

    def __iter__(self):
        variant_ids = self.cart.keys()
        variants = ProductVariant.objects.select_related('product').filter(id__in=variant_ids)
        variants_by_id = {str(variant.id): variant for variant in variants}
        for variant_id, quantity in self.quantities().items():
            variant = variants_by_id.get(variant_id)
            if not variant:
                continue
            yield {
                'variant': variant,
                'quantity': quantity,
                'unit_price': variant.price,
                'line_total': variant.price * quantity,
            }

    def __len__(self):
        return sum(int(quantity) for quantity in self.cart.values())

    def get_total_price(self):
        return sum(item['line_total'] for item in self) or Decimal('0.00')

    def is_empty(self):
        return len(self) == 0
