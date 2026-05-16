import shutil
import tempfile
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.test.utils import override_settings
from django.urls import reverse

from .models import (
    Category,
    EmailLog,
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
                    SimpleUploadedFile('gallery-shot.jpg', b'fake-image-content', content_type='image/jpeg'),
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
        self.assertEqual(media_items[1].media_type, ProductMedia.TYPE_VIDEO)

        detail_response = self.client.get(product.get_absolute_url())
        self.assertContains(detail_response, 'gallery-shot')
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
            file=SimpleUploadedFile('first-shot.jpg', b'first-image', content_type='image/jpeg'),
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
            file=SimpleUploadedFile('third-shot.jpg', b'third-image', content_type='image/jpeg'),
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
        self.assertFalse(ProductMedia.objects.filter(pk=second_media.pk).exists())


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
            (reverse('staff:locations'), 'Pickup Locations'),
            (reverse('staff:orders'), 'Order Maintenance'),
            (reverse('staff:customers'), 'Customer Lookup'),
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
