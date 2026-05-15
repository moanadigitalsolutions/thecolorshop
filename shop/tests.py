from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import Category, EmailLog, Order, Product, ProductVariant
from .services import send_order_status_update


class CheckoutFlowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='customer',
            email='customer@example.com',
            password='test-pass-123',
            first_name='Test',
            last_name='Customer',
        )
        category = Category.objects.create(name='Interior Paint', slug='interior-paint')
        product = Product.objects.create(category=category, name='Premium Interior', slug='premium-interior')
        self.variant = ProductVariant.objects.create(
            product=product,
            sku='TCS-INT-WHT-4L',
            color='White',
            size='4L',
            finish='Low Sheen',
            price=Decimal('89.00'),
            stock_quantity=5,
        )

    def test_checkout_requires_login(self):
        response = self.client.get(reverse('checkout'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(settings.LOGIN_URL, response['Location'])

    def test_checkout_creates_pickup_order_and_reduces_stock(self):
        self.client.force_login(self.user)
        session = self.client.session
        session[settings.CART_SESSION_ID] = {str(self.variant.id): 2}
        session.save()

        response = self.client.post(
            reverse('checkout'),
            {
                'customer_name': 'Test Customer',
                'customer_email': 'customer@example.com',
                'customer_phone': '+68525577',
                'pickup_name': 'Family Pickup',
                'pickup_phone': '+68525577',
                'special_instructions': 'Call on arrival.',
            },
            follow=True,
        )

        self.assertContains(response, 'placed for pickup')
        order = Order.objects.get()
        self.assertEqual(order.payment_method, Order.PAYMENT_CASH)
        self.assertEqual(order.status, Order.STATUS_PENDING_PAYMENT)
        self.assertEqual(order.items.get().sku, self.variant.sku)
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_quantity, 3)
        self.assertEqual(EmailLog.objects.get().status, EmailLog.STATUS_SKIPPED)

    def test_status_update_email_is_logged_when_brevo_is_not_configured(self):
        order = Order.objects.create(
            user=self.user,
            customer_name='Test Customer',
            customer_email='customer@example.com',
            pickup_name='Family Pickup',
            pickup_address=settings.STORE_PICKUP_ADDRESS,
            status=Order.STATUS_READY,
        )

        log = send_order_status_update(order)

        self.assertEqual(log.template_key, 'order_status_update')
        self.assertEqual(log.status, EmailLog.STATUS_SKIPPED)
        self.assertIn(order.order_number, log.subject)


class ProductVariantTests(TestCase):
    def test_variant_display_and_stock_state(self):
        category = Category.objects.create(name='Exterior Paint', slug='exterior-paint')
        product = Product.objects.create(category=category, name='Exterior Finish', slug='exterior-finish')
        variant = ProductVariant.objects.create(
            product=product,
            sku='TCS-EXT-BGE-10L',
            color='Beige',
            size='10L',
            finish='Satin',
            price=Decimal('225.00'),
            stock_quantity=2,
            low_stock_threshold=3,
        )

        self.assertEqual(variant.display_name, 'Beige / 10L / Satin')
        self.assertEqual(variant.stock_state, 'low stock')


class ProductSearchApiTests(TestCase):
    def setUp(self):
        self.paint_category = Category.objects.create(name='Interior Paint', slug='interior-paint')
        self.tools_category = Category.objects.create(name='Tools', slug='tools')

        self.paint_product = Product.objects.create(
            category=self.paint_category,
            name='Premium Interior Low Sheen',
            slug='premium-interior-low-sheen',
            description='Durable wall paint for bedrooms and living rooms.',
        )
        ProductVariant.objects.create(
            product=self.paint_product,
            sku='TCS-INT-BLU-4L',
            color='Ocean Blue',
            finish='Low Sheen',
            price=Decimal('89.00'),
            stock_quantity=6,
        )

        self.tools_product = Product.objects.create(
            category=self.tools_category,
            name='Roller Kit',
            slug='roller-kit',
            description='Tray, roller frame, and sleeve.',
        )
        ProductVariant.objects.create(
            product=self.tools_product,
            sku='TCS-TOOL-ROLLER',
            color='',
            finish='',
            price=Decimal('42.00'),
            stock_quantity=4,
        )

    def test_product_search_api_returns_matches_for_query(self):
        response = self.client.get(reverse('product_search_api'), {'q': 'blue'})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['count'], 1)
        self.assertEqual(payload['products'][0]['slug'], self.paint_product.slug)
        self.assertEqual(payload['suggestions'][0]['type'], 'product')

    def test_product_search_api_respects_category_filter(self):
        response = self.client.get(reverse('product_search_api'), {'q': 'kit', 'category': self.tools_category.slug})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['count'], 1)
        self.assertEqual(payload['products'][0]['slug'], self.tools_product.slug)

    def test_product_search_api_returns_empty_for_blank_query_and_category(self):
        response = self.client.get(reverse('product_search_api'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'suggestions': [], 'products': [], 'count': 0})
