from datetime import timedelta
import shutil
import tempfile
from io import BytesIO
from decimal import Decimal
from unittest.mock import Mock, patch

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.test.utils import override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from PIL import Image

from .models import (
    Category,
    EmailLog,
    EmailSettings,
    Order,
    OrderItem,
    Product,
    ProductMedia,
    ProductOption,
    ProductOptionValue,
    ProductTag,
    ProductVariant,
    ProductVariantSelectedOption,
    StoreLocation,
    VariantInventoryLevel,
)
from .services import send_order_status_update
from .services import build_platform_url, get_logo_url, render_email_html, site_base_url_supports_remote_assets
from .tokens import email_verification_token_generator


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
        self.pickup_location = StoreLocation.ensure_default_location()
        self.secondary_location = StoreLocation.objects.create(name='Warehouse', address='Tafuna back lot', sort_order=2)
        product.pickup_locations.add(self.pickup_location, self.secondary_location)
        self.variant = ProductVariant.objects.create(
            product=product,
            sku='TCS-INT-WHT-4L',
            color='White',
            size='4L',
            finish='Low Sheen',
            price=Decimal('89.00'),
            stock_quantity=5,
        )
        VariantInventoryLevel.objects.create(variant=self.variant, location=self.pickup_location, quantity=3)
        VariantInventoryLevel.objects.create(variant=self.variant, location=self.secondary_location, quantity=2)

    def test_checkout_requires_login(self):
        response = self.client.get(reverse('checkout'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(settings.LOGIN_URL, response['Location'])

    @override_settings(EMAIL_HOST='', EMAIL_HOST_USER='', EMAIL_HOST_PASSWORD='')
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
                'pickup_location_choice': str(self.pickup_location.pk),
                'special_instructions': 'Call on arrival.',
            },
            follow=True,
        )

        self.assertContains(response, 'placed for pickup')
        order = Order.objects.get()
        self.assertEqual(order.payment_method, Order.PAYMENT_CASH)
        self.assertEqual(order.status, Order.STATUS_PENDING_PAYMENT)
        self.assertEqual(order.pickup_location, self.pickup_location.name)
        self.assertEqual(order.items.get().sku, self.variant.sku)
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_quantity, 3)
        self.assertEqual(self.variant.inventory_levels.get(location=self.pickup_location).quantity, 1)
        log = EmailLog.objects.get()
        self.assertEqual(log.status, EmailLog.STATUS_SKIPPED)
        self.assertIn('SMTP is selected', log.error_message)

    @override_settings(EMAIL_HOST='', EMAIL_HOST_USER='', EMAIL_HOST_PASSWORD='')
    def test_status_update_email_is_logged_when_smtp_is_not_configured(self):
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
        self.assertIn('SMTP is selected', log.error_message)

    @override_settings(
        EMAIL_HOST='srv1104890.hstgr.cloud',
        EMAIL_HOST_USER='customer@colourshop.ws',
        EMAIL_HOST_PASSWORD='test-secret',
        DEFAULT_FROM_EMAIL='customer@colourshop.ws',
    )
    @patch('shop.services.EmailMultiAlternatives.send', return_value=1)
    def test_status_update_email_is_sent_through_smtp_by_default(self, mocked_send):
        order = Order.objects.create(
            user=self.user,
            customer_name='Test Customer',
            customer_email='customer@example.com',
            pickup_name='Family Pickup',
            pickup_address=settings.STORE_PICKUP_ADDRESS,
            status=Order.STATUS_READY,
        )

        log = send_order_status_update(order)

        self.assertEqual(log.status, EmailLog.STATUS_SENT)
        mocked_send.assert_called_once_with(fail_silently=False)

    @patch('shop.services.requests.post')
    def test_status_update_email_can_use_brevo_when_selected(self, mocked_post):
        email_settings = EmailSettings.get_solo()
        email_settings.email_provider = EmailSettings.PROVIDER_BREVO
        email_settings.save()
        mocked_response = Mock()
        mocked_response.content = b'{"messageId": "brevo-123"}'
        mocked_response.json.return_value = {'messageId': 'brevo-123'}
        mocked_response.raise_for_status.return_value = None
        mocked_post.return_value = mocked_response

        with override_settings(BREVO_API_KEY='brevo-test-key'):
            order = Order.objects.create(
                user=self.user,
                customer_name='Test Customer',
                customer_email='customer@example.com',
                pickup_name='Family Pickup',
                pickup_address=settings.STORE_PICKUP_ADDRESS,
                status=Order.STATUS_READY,
            )

            log = send_order_status_update(order)

        self.assertEqual(log.status, EmailLog.STATUS_SENT)
        self.assertEqual(log.brevo_message_id, 'brevo-123')
        mocked_post.assert_called_once()


class AccountVerificationTests(TestCase):
    signup_payload = {
        'username': 'verify-user',
        'first_name': 'Verify',
        'last_name': 'User',
        'email': 'verify@example.com',
        'phone_number': '+68525577',
        'password1': 'test-pass-12345',
        'password2': 'test-pass-12345',
    }

    @override_settings(
        EMAIL_HOST='srv1104890.hstgr.cloud',
        EMAIL_HOST_USER='customer@colourshop.ws',
        EMAIL_HOST_PASSWORD='test-secret',
        DEFAULT_FROM_EMAIL='customer@colourshop.ws',
    )
    @patch('shop.services.EmailMultiAlternatives.send', return_value=1)
    def test_signup_creates_unverified_account_and_sends_verification_email(self, mocked_send):
        response = self.client.post(reverse('signup'), self.signup_payload, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Verify your email address')
        user = User.objects.get(username='verify-user')
        self.assertFalse(user.customer_profile.is_email_verified)
        self.assertNotIn('_auth_user_id', self.client.session)
        log = EmailLog.objects.get(template_key='email_verification')
        self.assertEqual(log.status, EmailLog.STATUS_SENT)
        mocked_send.assert_called_once_with(fail_silently=False)

    def test_unverified_user_cannot_log_in(self):
        user = User.objects.create_user(username='pending-user', email='pending@example.com', password='test-pass-12345')

        response = self.client.post(reverse('login'), {'username': 'pending-user', 'password': 'test-pass-12345'})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Please verify your email address before logging in.')

    def test_verified_user_can_log_in(self):
        user = User.objects.create_user(username='verified-user', email='verified@example.com', password='test-pass-12345')
        user.customer_profile.is_email_verified = True
        user.customer_profile.email_verified_at = timezone.now()
        user.customer_profile.save(update_fields=['is_email_verified', 'email_verified_at', 'updated_at'])

        response = self.client.post(reverse('login'), {'username': 'verified-user', 'password': 'test-pass-12345'})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], reverse('product_list'))

    def test_verification_link_marks_profile_verified(self):
        user = User.objects.create_user(username='link-user', email='link@example.com', password='test-pass-12345')
        uidb64 = urlsafe_base64_encode(force_bytes(user.pk))
        token = email_verification_token_generator.make_token(user)

        response = self.client.get(reverse('verify_email', kwargs={'uidb64': uidb64, 'token': token}), follow=True)

        self.assertEqual(response.status_code, 200)
        user.customer_profile.refresh_from_db()
        self.assertTrue(user.customer_profile.is_email_verified)
        self.assertContains(response, 'Email verified')

    def test_resend_verification_respects_cooldown(self):
        user = User.objects.create_user(username='cooldown-user', email='cooldown@example.com', password='test-pass-12345')
        user.customer_profile.email_verification_sent_at = timezone.now()
        user.customer_profile.save(update_fields=['email_verification_sent_at', 'updated_at'])

        response = self.client.post(reverse('resend_verification'), {'email': 'cooldown@example.com'})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Please wait about')


class PasswordResetFlowTests(TestCase):
    @override_settings(
        EMAIL_HOST='srv1104890.hstgr.cloud',
        EMAIL_HOST_USER='customer@colourshop.ws',
        EMAIL_HOST_PASSWORD='test-secret',
        DEFAULT_FROM_EMAIL='customer@colourshop.ws',
    )
    @patch('shop.services.EmailMultiAlternatives.send', return_value=1)
    def test_password_reset_request_logs_and_sends_email(self, mocked_send):
        user = User.objects.create_user(
            username='reset-user',
            email='reset@example.com',
            password='old-password-123',
            first_name='Reset',
            last_name='User',
        )

        response = self.client.post(reverse('password_reset'), {'email': user.email}, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Check your inbox')
        log = EmailLog.objects.get(template_key='password_reset')
        self.assertEqual(log.recipient, user.email)
        self.assertEqual(log.status, EmailLog.STATUS_SENT)
        mocked_send.assert_called_once_with(fail_silently=False)

    def test_password_reset_confirm_accepts_new_password(self):
        user = User.objects.create_user(username='reset-confirm', email='confirm@example.com', password='old-password-123')
        uidb64 = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)

        response = self.client.get(reverse('password_reset_confirm', kwargs={'uidb64': uidb64, 'token': token}), follow=True)

        self.assertEqual(response.status_code, 200)
        post_response = self.client.post(
            response.request['PATH_INFO'],
            {'new_password1': 'new-pass-12345', 'new_password2': 'new-pass-12345'},
            follow=True,
        )

        self.assertEqual(post_response.status_code, 200)
        self.assertContains(post_response, 'Password updated')
        user.refresh_from_db()
        self.assertTrue(user.check_password('new-pass-12345'))


class EmailTemplateBrandingTests(TestCase):
    @override_settings(SITE_BASE_URL='https://thecolorshop.ws')
    def test_build_platform_url_uses_site_base_url(self):
        self.assertEqual(build_platform_url('/orders/test-order/'), 'https://thecolorshop.ws/orders/test-order/')
        self.assertTrue(site_base_url_supports_remote_assets())
        self.assertEqual(get_logo_url(), 'https://thecolorshop.ws/static/img/tcs-logo-light.jpg')

    @override_settings(SITE_BASE_URL='http://127.0.0.1:8000')
    def test_local_site_base_url_hides_hosted_logo(self):
        self.assertFalse(site_base_url_supports_remote_assets())
        self.assertEqual(get_logo_url(), '')

        html = render_email_html('emails/base.html', {'email_title': 'Preview'})

        self.assertNotIn('<img', html)

    @override_settings(SITE_BASE_URL='https://thecolorshop.ws')
    def test_order_confirmation_template_includes_logo_and_cta_link(self):
        html = render_email_html(
            'emails/order_confirmation.html',
            {
                'email_title': 'Order confirmation',
                'customer_name': 'Mathew Fesili',
                'order': type('OrderPreview', (), {'total': '149.00', 'pickup_address': settings.STORE_PICKUP_ADDRESS})(),
                'order_items': [type('OrderItemPreview', (), {'quantity': 1, 'product_name': 'Premium Interior Paint', 'variant_name': 'White / 4L', 'line_total': '149.00'})()],
                'cta_label': 'View order details',
                'cta_url': 'https://thecolorshop.ws/orders/TCS-123/',
            },
        )

        self.assertIn('https://thecolorshop.ws/static/img/tcs-logo-light.jpg', html)
        self.assertIn('https://thecolorshop.ws/orders/TCS-123/', html)
        self.assertIn('View order details', html)


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

    def test_variant_display_prefers_selected_options_and_syncs_legacy_fields(self):
        category = Category.objects.create(name='Primers', slug='primers')
        product = Product.objects.create(category=category, name='Grip Primer', slug='grip-primer')
        variant = ProductVariant.objects.create(product=product, sku='TCS-PRIMER-MED', price=Decimal('29.00'))
        size_option = ProductOption.objects.create(product=product, name='Size', sort_order=1)
        size_value = ProductOptionValue.objects.create(option=size_option, value='Medium', sort_order=1)
        finish_option = ProductOption.objects.create(product=product, name='Finish', sort_order=2)
        finish_value = ProductOptionValue.objects.create(option=finish_option, value='Matte', sort_order=1)

        ProductVariantSelectedOption.objects.create(
            variant=variant,
            option=size_option,
            option_value=size_value,
            sort_order=1,
        )
        ProductVariantSelectedOption.objects.create(
            variant=variant,
            option=finish_option,
            option_value=finish_value,
            sort_order=2,
        )

        variant.refresh_from_db()
        self.assertEqual(variant.display_name, 'Medium / Matte')
        self.assertEqual(variant.size, 'Medium')
        self.assertEqual(variant.finish, 'Matte')
        self.assertEqual(variant.color, '')

    def test_variant_current_price_prefers_sale_price(self):
        category = Category.objects.create(name='Sealants', slug='sealants')
        product = Product.objects.create(category=category, name='Roof Seal', slug='roof-seal')
        variant = ProductVariant.objects.create(
            product=product,
            sku='TCS-SEAL-1',
            price=Decimal('50.00'),
            sale_price=Decimal('39.00'),
            stock_quantity=2,
        )

        self.assertEqual(variant.current_price, Decimal('39.00'))


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

    def test_product_search_api_matches_selected_option_values(self):
        size_option = ProductOption.objects.create(product=self.paint_product, name='Size', sort_order=1)
        size_value = ProductOptionValue.objects.create(option=size_option, value='Large', sort_order=1)
        variant = self.paint_product.variants.get(sku='TCS-INT-BLU-4L')
        ProductVariantSelectedOption.objects.create(
            variant=variant,
            option=size_option,
            option_value=size_value,
            sort_order=1,
        )

        response = self.client.get(reverse('product_search_api'), {'q': 'large'})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['count'], 1)
        self.assertEqual(payload['products'][0]['slug'], self.paint_product.slug)

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


class ProductListPaginationTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name='Interior Paint', slug='interior-paint')
        for index in range(13):
            product = Product.objects.create(
                category=self.category,
                name=f'Paginated Product {index:02d}',
                slug=f'paginated-product-{index:02d}',
                is_active=True,
            )
            ProductVariant.objects.create(
                product=product,
                sku=f'PAG-{index:02d}',
                price=Decimal('20.00'),
                stock_quantity=3,
                is_active=True,
            )

    def test_product_list_uses_second_page(self):
        response = self.client.get(reverse('product_list'), {'page': 2})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['page_obj'].number, 2)
        self.assertContains(response, 'Paginated Product 12')
        self.assertNotContains(response, 'Paginated Product 00')
        self.assertContains(response, 'Page 2 of 2')


class SeoEndpointTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name='Exterior Paint', slug='exterior-paint')
        self.active_product = Product.objects.create(
            category=self.category,
            name='Sitemap Product',
            slug='sitemap-product',
            is_active=True,
        )
        self.inactive_product = Product.objects.create(
            category=self.category,
            name='Hidden Product',
            slug='hidden-product',
            is_active=False,
        )

    def test_robots_txt_disallows_private_routes_and_links_sitemap(self):
        response = self.client.get(reverse('robots_txt'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/plain')
        self.assertContains(response, 'Disallow: /staff/')
        self.assertContains(response, 'Disallow: /checkout/')
        self.assertContains(response, 'Sitemap: http://testserver/sitemap.xml')

    def test_sitemap_lists_public_catalog_and_active_products(self):
        response = self.client.get(reverse('sitemap'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'http://testserver/')
        self.assertContains(response, self.active_product.get_absolute_url())
        self.assertNotContains(response, self.inactive_product.get_absolute_url())


class StaffProductEditorTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp()
        self.media_override = override_settings(MEDIA_ROOT=self.media_root)
        self.media_override.enable()
        self.addCleanup(self.media_override.disable)
        self.addCleanup(lambda: shutil.rmtree(self.media_root, ignore_errors=True))
        self.staff_user = User.objects.create_user(username='staff', password='test-pass-123', is_staff=True)
        self.category = Category.objects.create(name='Accessories', slug='accessories')
        self.pickup_location = StoreLocation.ensure_default_location()
        self.secondary_location = StoreLocation.objects.create(name='Warehouse', address='Tafuna back lot', sort_order=2)

    def make_test_image_upload(self, name='test-image.jpg', color='navy'):
        image_buffer = BytesIO()
        Image.new('RGB', (12, 12), color=color).save(image_buffer, format='JPEG')
        image_buffer.seek(0)
        return SimpleUploadedFile(name, image_buffer.read(), content_type='image/jpeg')

    def test_staff_product_editor_saves_option_driven_variant_selection(self):
        self.client.force_login(self.staff_user)

        response = self.client.post(
            reverse('staff:product_create'),
            {
                'name': 'Staff Variant Product',
                'slug': '',
                'description': 'Option-driven product editor validation.',
                'meta_title': 'Staff Variant Product SEO',
                'meta_description': 'Search description for staff-created product.',
                'tags_input': 'feature, primer',
                'category': str(self.category.pk),
                'pickup_locations': [str(self.pickup_location.pk), str(self.secondary_location.pk)],
                'is_active': 'on',
                'options-TOTAL_FORMS': '1',
                'options-INITIAL_FORMS': '0',
                'options-MIN_NUM_FORMS': '0',
                'options-MAX_NUM_FORMS': '1000',
                'options-0-name': 'Size',
                'options-0-option_values': 'Small, Medium, Large',
                'options-0-sort_order': '1',
                'variants-TOTAL_FORMS': '1',
                'variants-INITIAL_FORMS': '0',
                'variants-MIN_NUM_FORMS': '0',
                'variants-MAX_NUM_FORMS': '1000',
                'variants-0-sku': 'STAFF-VARIANT-MED',
                'variants-0-option_choice_1': 'Medium',
                'variants-0-price': '18.50',
                'variants-0-sale_price': '15.00',
                'variants-0-stock_quantity': '5',
                'variants-0-low_stock_threshold': '2',
                'variants-0-inventory_breakdown': 'Apia Store: 3; Warehouse: 2',
                'variants-0-is_active': 'on',
                'save_action': 'continue',
            },
        )

        self.assertEqual(response.status_code, 302)
        product = Product.objects.get(name='Staff Variant Product')
        variant = product.variants.get(sku='STAFF-VARIANT-MED')

        self.assertEqual(product.meta_title, 'Staff Variant Product SEO')
        self.assertEqual(product.meta_description, 'Search description for staff-created product.')
        self.assertEqual(list(product.tags.order_by('name').values_list('name', flat=True)), ['feature', 'primer'])
        self.assertEqual(
            list(product.pickup_locations.order_by('sort_order', 'name').values_list('name', flat=True)),
            ['Apia Store', 'Warehouse'],
        )
        self.assertEqual(variant.display_name, 'Medium')
        self.assertEqual(variant.size, 'Medium')
        self.assertEqual(variant.current_price, Decimal('15.00'))
        self.assertEqual(variant.stock_quantity, 5)
        self.assertEqual(
            list(variant.inventory_levels.order_by('location__sort_order', 'location__name').values_list('location__name', 'quantity')),
            [('Apia Store', 3), ('Warehouse', 2)],
        )
        self.assertEqual(
            list(variant.selected_options.values_list('option__name', 'option_value__value')),
            [('Size', 'Medium')],
        )

    def test_staff_product_editor_saves_gallery_uploads_and_detail_gallery_renders(self):
        self.client.force_login(self.staff_user)

        response = self.client.post(
            reverse('staff:product_create'),
            {
                'name': 'Media Product',
                'slug': '',
                'description': 'Product with gallery uploads.',
                'category': str(self.category.pk),
                'is_active': 'on',
                'options-TOTAL_FORMS': '0',
                'options-INITIAL_FORMS': '0',
                'options-MIN_NUM_FORMS': '0',
                'options-MAX_NUM_FORMS': '1000',
                'variants-TOTAL_FORMS': '1',
                'variants-INITIAL_FORMS': '0',
                'variants-MIN_NUM_FORMS': '0',
                'variants-MAX_NUM_FORMS': '1000',
                'variants-0-sku': 'MEDIA-PRODUCT-1',
                'variants-0-price': '25.00',
                'variants-0-stock_quantity': '2',
                'variants-0-low_stock_threshold': '1',
                'variants-0-is_active': 'on',
                'save_action': 'continue',
                'media_files': [
                    self.make_test_image_upload('gallery-shot.jpg'),
                    SimpleUploadedFile('paint-demo.mp4', b'fake-video-content', content_type='video/mp4'),
                ],
            },
        )

        self.assertEqual(response.status_code, 302)
        product = Product.objects.get(name='Media Product')
        media_items = list(product.media_assets.order_by('-is_primary', 'sort_order', 'id'))

        self.assertEqual(len(media_items), 2)
        self.assertEqual(media_items[0].media_type, ProductMedia.TYPE_IMAGE)
        self.assertTrue(media_items[0].is_primary)
        self.assertTrue(media_items[0].file.name.endswith('.webp'))
        self.assertEqual(media_items[1].media_type, ProductMedia.TYPE_VIDEO)
        self.assertTrue(media_items[1].file.name.endswith('.mp4'))

        detail_response = self.client.get(product.get_absolute_url())
        self.assertContains(detail_response, '.webp')
        self.assertContains(detail_response, 'paint-demo')

    def test_staff_product_editor_updates_saved_media_order_and_deletes_items(self):
        self.client.force_login(self.staff_user)
        product = Product.objects.create(
            category=self.category,
            name='Editable Media Product',
            slug='editable-media-product',
            description='Saved media controls.',
            is_active=True,
        )
        product.pickup_locations.add(self.pickup_location)
        variant = ProductVariant.objects.create(
            product=product,
            sku='EDITABLE-MEDIA-1',
            price=Decimal('19.00'),
            stock_quantity=2,
            low_stock_threshold=1,
            is_active=True,
        )
        first_media = ProductMedia.objects.create(
            product=product,
            file=self.make_test_image_upload('first-shot.jpg', color='green'),
            media_type=ProductMedia.TYPE_IMAGE,
            alt_text='First shot',
            sort_order=1,
            is_primary=True,
        )
        second_media = ProductMedia.objects.create(
            product=product,
            file=SimpleUploadedFile('second-clip.mp4', b'second-video', content_type='video/mp4'),
            media_type=ProductMedia.TYPE_VIDEO,
            alt_text='Second clip',
            sort_order=2,
            is_primary=False,
        )
        third_media = ProductMedia.objects.create(
            product=product,
            file=self.make_test_image_upload('third-shot.jpg', color='orange'),
            media_type=ProductMedia.TYPE_IMAGE,
            alt_text='Third shot',
            sort_order=3,
            is_primary=False,
        )

        response = self.client.post(
            reverse('staff:product_edit', kwargs={'pk': product.pk}),
            {
                'name': product.name,
                'slug': product.slug,
                'description': product.description,
                'meta_title': '',
                'meta_description': '',
                'tags_input': '',
                'category': str(self.category.pk),
                'pickup_locations': [str(self.pickup_location.pk)],
                'is_active': 'on',
                f'media_sort_{first_media.pk}': '2',
                f'media_sort_{second_media.pk}': '3',
                f'media_sort_{third_media.pk}': '1',
                'primary_media_id': str(third_media.pk),
                'delete_media': [str(second_media.pk)],
                'options-TOTAL_FORMS': '0',
                'options-INITIAL_FORMS': '0',
                'options-MIN_NUM_FORMS': '0',
                'options-MAX_NUM_FORMS': '1000',
                'variants-TOTAL_FORMS': '1',
                'variants-INITIAL_FORMS': '1',
                'variants-MIN_NUM_FORMS': '0',
                'variants-MAX_NUM_FORMS': '1000',
                'variants-0-id': str(variant.pk),
                'variants-0-sku': variant.sku,
                'variants-0-price': '19.00',
                'variants-0-sale_price': '',
                'variants-0-stock_quantity': '2',
                'variants-0-low_stock_threshold': '1',
                'variants-0-inventory_breakdown': '',
                'variants-0-is_active': 'on',
                'save_action': 'continue',
            },
        )

        self.assertEqual(response.status_code, 302)
        product.refresh_from_db()
        media_items = list(product.media_assets.order_by('-is_primary', 'sort_order', 'id'))

        self.assertEqual([media.pk for media in media_items], [third_media.pk, first_media.pk])
        self.assertTrue(media_items[0].is_primary)
        self.assertEqual(media_items[0].sort_order, 1)
        self.assertEqual(media_items[1].sort_order, 2)
        self.assertTrue(all(media.file.name.endswith('.webp') or media.file.name.endswith('.mp4') for media in media_items))
        self.assertFalse(ProductMedia.objects.filter(pk=second_media.pk).exists())


class StaffImportExportTests(TestCase):
    def setUp(self):
        self.staff_user = User.objects.create_user(username='bulk-staff', password='test-pass-123', is_staff=True)
        self.category = Category.objects.create(name='Bulk Paint', slug='bulk-paint')
        self.primary_location = StoreLocation.ensure_default_location()
        self.secondary_location = StoreLocation.objects.create(name='Warehouse', address='Tafuna back lot', sort_order=2)
        self.product = Product.objects.create(
            category=self.category,
            name='Bulk Ready Paint',
            slug='bulk-ready-paint',
            description='Prepared for bulk updates.',
            is_active=True,
        )
        self.product.pickup_locations.add(self.primary_location, self.secondary_location)

        self.size_option = ProductOption.objects.create(product=self.product, name='Size', sort_order=1)
        self.medium_value = ProductOptionValue.objects.create(option=self.size_option, value='Medium', sort_order=1)
        self.large_value = ProductOptionValue.objects.create(option=self.size_option, value='Large', sort_order=2)
        self.finish_option = ProductOption.objects.create(product=self.product, name='Finish', sort_order=2)
        self.matte_value = ProductOptionValue.objects.create(option=self.finish_option, value='Matte', sort_order=1)
        self.gloss_value = ProductOptionValue.objects.create(option=self.finish_option, value='Gloss', sort_order=2)

        self.variant = ProductVariant.objects.create(
            product=self.product,
            sku='BULK-SKU-1',
            price=Decimal('25.00'),
            sale_price=Decimal('20.00'),
            stock_quantity=5,
            low_stock_threshold=2,
            is_active=True,
        )
        ProductVariantSelectedOption.objects.create(
            variant=self.variant,
            option=self.size_option,
            option_value=self.medium_value,
            sort_order=1,
        )
        ProductVariantSelectedOption.objects.create(
            variant=self.variant,
            option=self.finish_option,
            option_value=self.matte_value,
            sort_order=2,
        )
        VariantInventoryLevel.objects.create(variant=self.variant, location=self.primary_location, quantity=3)
        VariantInventoryLevel.objects.create(variant=self.variant, location=self.secondary_location, quantity=2)

    def test_bulk_tools_exports_variant_csv(self):
        self.client.force_login(self.staff_user)

        response = self.client.get(
            reverse('staff:product_import_export'),
            {'export': '1', 'resource': 'variants'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv; charset=utf-8')
        csv_output = response.content.decode('utf-8')
        self.assertIn('product,sku,option_values,color,size,finish,price,sale_price,stock_quantity,low_stock_threshold,is_active', csv_output)
        self.assertIn('bulk-ready-paint,BULK-SKU-1,Size=Medium|Finish=Matte,', csv_output)

    def test_bulk_variant_import_updates_option_driven_variant(self):
        self.client.force_login(self.staff_user)
        csv_payload = '\n'.join(
            [
                'product,sku,option_values,color,size,finish,price,sale_price,stock_quantity,low_stock_threshold,is_active',
                'bulk-ready-paint,BULK-SKU-1,Size=Large|Finish=Gloss,,, ,28.00,24.00,7,3,True'.replace(',,, ,', ',,,,'),
            ]
        )

        response = self.client.post(
            reverse('staff:product_import_export'),
            {
                'resource': 'variants',
                'import_file': SimpleUploadedFile('variants.csv', csv_payload.encode('utf-8'), content_type='text/csv'),
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Variants import completed.')
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.display_name, 'Large / Gloss')
        self.assertEqual(self.variant.size, 'Large')
        self.assertEqual(self.variant.finish, 'Gloss')
        self.assertEqual(self.variant.current_price, Decimal('24.00'))
        self.assertEqual(
            list(self.variant.selected_options.order_by('sort_order').values_list('option__name', 'option_value__value')),
            [('Size', 'Large'), ('Finish', 'Gloss')],
        )

    def test_bulk_inventory_import_updates_location_quantities(self):
        self.client.force_login(self.staff_user)
        csv_payload = '\n'.join(
            [
                'variant,location,quantity',
                'BULK-SKU-1,Apia Store,5',
                'BULK-SKU-1,Warehouse,4',
            ]
        )

        response = self.client.post(
            reverse('staff:product_import_export'),
            {
                'resource': 'inventory',
                'import_file': SimpleUploadedFile('inventory.csv', csv_payload.encode('utf-8'), content_type='text/csv'),
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Inventory by location import completed.')
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_quantity, 9)
        self.assertEqual(
            list(self.variant.inventory_levels.order_by('location__sort_order', 'location__name').values_list('location__name', 'quantity')),
            [('Apia Store', 5), ('Warehouse', 4)],
        )


class StaffAuthenticationTests(TestCase):
    def setUp(self):
        self.staff_user = User.objects.create_user(username='staff-gate', password='test-pass-123', is_staff=True)
        self.customer_user = User.objects.create_user(username='customer-gate', password='test-pass-123')

    def test_staff_route_redirects_anonymous_users_to_staff_login(self):
        response = self.client.get(reverse('staff:dashboard'))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('staff:login'), response['Location'])
        self.assertIn('next=/staff/', response['Location'])

    def test_staff_login_redirects_staff_user_to_dashboard(self):
        response = self.client.post(
            reverse('staff:login'),
            {'username': 'staff-gate', 'password': 'test-pass-123'},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], reverse('staff:dashboard'))

    def test_staff_login_rejects_non_staff_user(self):
        response = self.client.post(
            reverse('staff:login'),
            {'username': 'customer-gate', 'password': 'test-pass-123'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'This account does not have staff portal access.')

    def test_staff_route_redirects_logged_in_non_staff_users_to_storefront(self):
        self.client.force_login(self.customer_user)

        response = self.client.get(reverse('staff:dashboard'), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertRedirects(response, reverse('product_list'))
        messages = list(response.context['messages'])
        self.assertTrue(any('does not have access to the staff portal' in str(message) for message in messages))

    @override_settings(AXES_FAILURE_LIMIT=2, AXES_COOLOFF_TIME=timedelta(minutes=30))
    def test_staff_login_locks_after_repeated_failed_attempts(self):
        self.client.post(reverse('staff:login'), {'username': 'staff-gate', 'password': 'wrong-pass'})
        self.client.post(reverse('staff:login'), {'username': 'staff-gate', 'password': 'wrong-pass'})

        response = self.client.post(
            reverse('staff:login'),
            {'username': 'staff-gate', 'password': 'wrong-pass'},
        )

        self.assertEqual(response.status_code, 429)


class StaffPageRenderTests(TestCase):
    def setUp(self):
        self.staff_user = User.objects.create_user(username='staff-pages', password='test-pass-123', is_staff=True)
        self.customer_user = User.objects.create_user(username='page-customer', password='test-pass-123')
        self.category = Category.objects.create(name='Paint', slug='paint')
        self.location = StoreLocation.ensure_default_location()
        self.product = Product.objects.create(
            category=self.category,
            name='Render Product',
            slug='render-product',
            description='Render coverage product.',
            is_active=True,
        )
        self.product.pickup_locations.add(self.location)
        ProductVariant.objects.create(
            product=self.product,
            sku='RENDER-1',
            price=Decimal('12.00'),
            stock_quantity=4,
            low_stock_threshold=1,
            is_active=True,
        )
        self.order = Order.objects.create(
            user=self.customer_user,
            customer_name='Render Customer',
            customer_email='render@example.com',
            pickup_name='Render Pickup',
            pickup_location=self.location.name,
            pickup_address=self.location.address,
            total=Decimal('12.00'),
            subtotal=Decimal('12.00'),
        )
        OrderItem.objects.create(
            order=self.order,
            product_name=self.product.name,
            variant_name='Standard',
            sku='RENDER-1',
            unit_price=Decimal('12.00'),
            quantity=1,
            line_total=Decimal('12.00'),
        )
        EmailLog.objects.create(
            order=self.order,
            recipient='render@example.com',
            subject='Render order confirmation',
            template_key='order_confirmation',
            status=EmailLog.STATUS_SENT,
        )

    def test_staff_index_pages_render_for_staff_user(self):
        self.client.force_login(self.staff_user)

        page_checks = [
            (reverse('staff:dashboard'), 'Dashboard Overview'),
            (reverse('staff:products'), 'Product Maintenance'),
            (reverse('staff:product_import_export'), 'Bulk Product Tools'),
            (reverse('staff:locations'), 'Pickup Locations'),
            (reverse('staff:orders'), 'Order Maintenance'),
            (reverse('staff:customers'), 'Customer Lookup'),
            (reverse('staff:email_settings'), 'Email Delivery Settings'),
            (reverse('staff:email_logs'), 'Email Log Review'),
        ]

        for url, marker in page_checks:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, marker)

    def test_staff_detail_and_editor_pages_render_for_staff_user(self):
        self.client.force_login(self.staff_user)

        page_checks = [
            (reverse('staff:order_detail', kwargs={'order_number': self.order.order_number}), self.order.order_number),
            (reverse('staff:product_create'), 'Add product'),
            (reverse('staff:product_edit', kwargs={'pk': self.product.pk}), self.product.name),
            (reverse('staff:location_edit', kwargs={'pk': self.location.pk}), 'Edit location'),
        ]

        for url, marker in page_checks:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, marker)


class StaffLocationManagementTests(TestCase):
        def setUp(self):
                self.staff_user = User.objects.create_user(username='location-staff', password='test-pass-123', is_staff=True)

        def test_staff_locations_page_renders(self):
                self.client.force_login(self.staff_user)

                response = self.client.get(reverse('staff:locations'))

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'Pickup Locations')

        def test_staff_locations_page_creates_location(self):
                self.client.force_login(self.staff_user)

                response = self.client.post(
                        reverse('staff:locations'),
                        {
                                'name': 'West Side Counter',
                                'address': 'Main Cross Island Rd',
                                'pickup_instructions': 'Collect beside the tint desk.',
                                'sort_order': '3',
                                'is_active': 'on',
                                'is_pickup_enabled': 'on',
                        },
                )

                self.assertEqual(response.status_code, 302)
                self.assertTrue(StoreLocation.objects.filter(name='West Side Counter', is_pickup_enabled=True).exists())




class StaffEmailSettingsTests(TestCase):
        def setUp(self):
                self.staff_user = User.objects.create_user(username='email-settings-staff', password='test-pass-123', is_staff=True)
                EmailSettings.get_solo()

        def test_staff_email_settings_page_updates_provider(self):
                self.client.force_login(self.staff_user)

                response = self.client.post(
                        reverse('staff:email_settings'),
                        {'email_provider': EmailSettings.PROVIDER_BREVO},
                        follow=True,
                )

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'Brevo is now active.')
                self.assertEqual(EmailSettings.get_solo().email_provider, EmailSettings.PROVIDER_BREVO)


class StaffOrderManagementTests(TestCase):
        def setUp(self):
                self.staff_user = User.objects.create_user(username='order-staff', password='test-pass-123', is_staff=True)
                self.customer_user = User.objects.create_user(username='order-customer', password='test-pass-123')
                self.order = Order.objects.create(
                        user=self.customer_user,
                        customer_name='Order Customer',
                        customer_email='order@example.com',
                        pickup_name='Pickup Person',
                        pickup_location='Apia Store',
                        pickup_address=settings.STORE_PICKUP_ADDRESS,
                        total=Decimal('42.00'),
                        subtotal=Decimal('42.00'),
                )
                OrderItem.objects.create(
                        order=self.order,
                        product_name='Roller Kit',
                        variant_name='Standard',
                        sku='ROLLER-1',
                        unit_price=Decimal('42.00'),
                        quantity=1,
                        line_total=Decimal('42.00'),
                )

        def test_staff_orders_page_renders(self):
                self.client.force_login(self.staff_user)

                response = self.client.get(reverse('staff:orders'))

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, self.order.order_number)

        def test_staff_order_detail_updates_status_and_logs_email(self):
                self.client.force_login(self.staff_user)

                response = self.client.post(
                        reverse('staff:order_detail', kwargs={'order_number': self.order.order_number}),
                        {
                                'status': Order.STATUS_READY,
                                'special_instructions': 'Packed and ready at front desk.',
                        },
                        follow=True,
                )

                self.assertEqual(response.status_code, 200)
                self.order.refresh_from_db()
                self.assertEqual(self.order.status, Order.STATUS_READY)
                self.assertEqual(self.order.special_instructions, 'Packed and ready at front desk.')
                self.assertEqual(EmailLog.objects.filter(order=self.order, template_key='order_status_update').count(), 1)




class StaffCustomerAndEmailLogTests(TestCase):
        def setUp(self):
                self.staff_user = User.objects.create_user(username='support-staff', password='test-pass-123', is_staff=True)
                self.customer_user = User.objects.create_user(
                        username='lookup-customer',
                        email='lookup@example.com',
                        password='test-pass-123',
                        first_name='Lookup',
                        last_name='Customer',
                )
                profile = self.customer_user.customer_profile
                profile.phone_number = '+68570000'
                profile.default_pickup_name = 'Family Pickup'
                profile.save(update_fields=['phone_number', 'default_pickup_name', 'updated_at'])
                self.order = Order.objects.create(
                        user=self.customer_user,
                        customer_name='Lookup Customer',
                        customer_email='lookup@example.com',
                        pickup_name='Family Pickup',
                        pickup_location='Apia Store',
                        pickup_address=settings.STORE_PICKUP_ADDRESS,
                        total=Decimal('15.00'),
                        subtotal=Decimal('15.00'),
                )
                self.email_log = EmailLog.objects.create(
                        order=self.order,
                        recipient='lookup@example.com',
                        subject='Order confirmation',
                        template_key='order_confirmation',
                        status=EmailLog.STATUS_SKIPPED,
                        error_message='BREVO_API_KEY is not configured.',
                )

        def test_staff_customers_page_renders_lookup_data(self):
                self.client.force_login(self.staff_user)

                response = self.client.get(reverse('staff:customers'), {'q': 'lookup'})

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'lookup@example.com')
                self.assertContains(response, 'Family Pickup')

        def test_staff_email_logs_page_renders_review_data(self):
                self.client.force_login(self.staff_user)

                response = self.client.get(reverse('staff:email_logs'), {'status': EmailLog.STATUS_SKIPPED})

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'Order confirmation')
                self.assertContains(response, self.order.order_number)


class StaffPaginationTests(TestCase):
        def setUp(self):
            self.staff_user = User.objects.create_user(username='pagination-staff', password='test-pass-123', is_staff=True)
            self.customer_user = User.objects.create_user(username='pagination-customer', password='test-pass-123')

            for index in range(51):
                order = Order.objects.create(
                    user=self.customer_user,
                    customer_name=f'Pagination Customer {index:02d}',
                    customer_email=f'pagination-{index:02d}@example.com',
                    pickup_name='Pickup Person',
                    pickup_location='Apia Store',
                    pickup_address=settings.STORE_PICKUP_ADDRESS,
                    total=Decimal('18.00'),
                    subtotal=Decimal('18.00'),
                )
                OrderItem.objects.create(
                    order=order,
                    product_name='Roller Kit',
                    variant_name='Standard',
                    sku=f'ROLL-{index:02d}',
                    unit_price=Decimal('18.00'),
                    quantity=1,
                    line_total=Decimal('18.00'),
                )

        def test_staff_orders_page_uses_second_page(self):
            self.client.force_login(self.staff_user)

            response = self.client.get(reverse('staff:orders'), {'page': 2})

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.context['page_obj'].number, 2)
            self.assertEqual(len(response.context['orders']), 1)
            self.assertContains(response, 'Page 2 of 2')


class FormRateLimitTests(TestCase):
    def test_resend_verification_is_rate_limited(self):
        for _index in range(5):
            response = self.client.post(reverse('resend_verification'), {'email': 'rate-limit@example.com'})
            self.assertIn(response.status_code, [200, 302])

        limited_response = self.client.post(reverse('resend_verification'), {'email': 'rate-limit@example.com'})

        self.assertEqual(limited_response.status_code, 429)
        self.assertIn('Too many requests', limited_response.content.decode())
