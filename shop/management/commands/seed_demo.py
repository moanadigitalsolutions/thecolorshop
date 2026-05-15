from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils.text import slugify

from shop.models import Category, Product, ProductVariant


class Command(BaseCommand):
    help = 'Seed demo categories, products, and paint variants for local development.'

    def handle(self, *args, **options):
        categories = {
            'Interior Paint': 'Washable interior paints for Samoa homes and businesses.',
            'Exterior Paint': 'Weather-ready finishes for exterior walls and trim.',
            'Tools and Supplies': 'Brushes, rollers, trays, and prep supplies.',
        }
        category_objects = {}
        for name, description in categories.items():
            category, _ = Category.objects.update_or_create(
                slug=slugify(name),
                defaults={'name': name, 'description': description, 'is_active': True},
            )
            category_objects[name] = category

        products = [
            {
                'category': 'Interior Paint',
                'name': 'Premium Interior Low Sheen',
                'description': 'Durable low-sheen wall paint for bedrooms, living rooms, and rental properties.',
                'variants': [
                    ('TCS-INT-WHT-4L', 'White', '4L', 'Low Sheen', Decimal('89.00'), 18),
                    ('TCS-INT-CRM-4L', 'Cream', '4L', 'Low Sheen', Decimal('92.00'), 10),
                    ('TCS-INT-GRY-10L', 'Soft Grey', '10L', 'Low Sheen', Decimal('195.00'), 6),
                ],
            },
            {
                'category': 'Exterior Paint',
                'name': 'Tropical Exterior Finish',
                'description': 'Exterior paint made for humid coastal conditions and strong sunlight.',
                'variants': [
                    ('TCS-EXT-WHT-4L', 'White', '4L', 'Satin', Decimal('105.00'), 12),
                    ('TCS-EXT-BGE-10L', 'Beige', '10L', 'Satin', Decimal('225.00'), 5),
                ],
            },
            {
                'category': 'Tools and Supplies',
                'name': 'Roller Kit',
                'description': 'Tray, roller frame, and medium nap sleeve for general painting jobs.',
                'variants': [
                    ('TCS-TOOLS-ROLLER-KIT', '', 'Kit', '', Decimal('42.00'), 24),
                ],
            },
        ]

        for product_data in products:
            product, _ = Product.objects.update_or_create(
                slug=slugify(product_data['name']),
                defaults={
                    'category': category_objects[product_data['category']],
                    'name': product_data['name'],
                    'description': product_data['description'],
                    'is_active': True,
                },
            )
            for sku, color, size, finish, price, stock in product_data['variants']:
                ProductVariant.objects.update_or_create(
                    sku=sku,
                    defaults={
                        'product': product,
                        'color': color,
                        'size': size,
                        'finish': finish,
                        'price': price,
                        'stock_quantity': stock,
                        'is_active': True,
                    },
                )

        self.stdout.write(self.style.SUCCESS('Demo catalog seeded.'))
