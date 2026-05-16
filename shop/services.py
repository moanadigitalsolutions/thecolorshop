from decimal import Decimal
import ipaddress
from urllib.parse import urlparse

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.templatetags.static import static
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.html import strip_tags
import requests

from .models import EmailLog, EmailSettings, Order, OrderItem, ProductVariant, StoreLocation


def create_order_from_cart(user, cart, cleaned_data):
    if cart.is_empty():
        raise ValidationError('Your cart is empty.')

    with transaction.atomic():
        order_items = []
        subtotal = Decimal('0.00')
        pickup_location = cleaned_data.get('pickup_location_object') or StoreLocation.ensure_default_location()

        for variant_id, quantity in cart.quantities().items():
            variant = ProductVariant.objects.select_for_update().select_related('product').get(
                id=variant_id,
                is_active=True,
                product__is_active=True,
            )
            available_quantity = variant.quantity_at_location(pickup_location)
            if quantity > available_quantity:
                raise ValidationError(f'Only {available_quantity} available for {variant.sku} at {pickup_location.name}.')
            subtotal += variant.current_price * quantity
            order_items.append((variant, quantity))

        order = Order.objects.create(
            user=user,
            customer_name=cleaned_data['customer_name'],
            customer_email=cleaned_data['customer_email'],
            customer_phone=cleaned_data.get('customer_phone', ''),
            pickup_name=cleaned_data['pickup_name'],
            pickup_phone=cleaned_data.get('pickup_phone', ''),
            pickup_location=pickup_location.name,
            pickup_address=pickup_location.address,
            special_instructions=cleaned_data.get('special_instructions', ''),
            subtotal=subtotal,
            total=subtotal,
        )

        for variant, quantity in order_items:
            variant.reserve_stock(quantity, location=pickup_location)
            OrderItem.objects.create(
                order=order,
                product_variant=variant,
                product_name=variant.product.name,
                variant_name=variant.display_name,
                sku=variant.sku,
                unit_price=variant.current_price,
                quantity=quantity,
                line_total=variant.current_price * quantity,
            )

    return order


def get_active_email_provider():
    return EmailSettings.get_solo().email_provider


def build_platform_url(path=''):
    base_url = settings.SITE_BASE_URL.rstrip('/')
    if not path:
        return base_url
    normalized_path = path if path.startswith('/') else f'/{path}'
    return f'{base_url}{normalized_path}'


def site_base_url_supports_remote_assets():
    parsed_url = urlparse(build_platform_url())
    hostname = (parsed_url.hostname or '').strip().lower()
    if not hostname or hostname == 'localhost':
        return False

    try:
        ip_address = ipaddress.ip_address(hostname)
    except ValueError:
        return True

    return not (ip_address.is_loopback or ip_address.is_private)


def get_logo_url():
    if not site_base_url_supports_remote_assets():
        return ''
    return build_platform_url(static('img/tcs-logo-light.jpg'))


def get_order_detail_url(order):
    return build_platform_url(reverse('order_detail', kwargs={'order_number': order.order_number}))


def render_email_html(template_name, context=None):
    base_context = {
        'store_name': 'The Color Shop',
        'store_contact_phone': settings.STORE_CONTACT_PHONE,
        'store_pickup_address': settings.STORE_PICKUP_ADDRESS,
        'site_base_url': build_platform_url(),
        'platform_home_url': build_platform_url('/'),
        'logo_url': get_logo_url(),
    }
    if context:
        base_context.update(context)
    return render_to_string(template_name, base_context)


def send_templated_email(recipient, recipient_name, subject, template_name, context=None, order=None, template_key='generic'):
    html_content = render_email_html(template_name, context=context)
    return send_email(
        recipient,
        recipient_name,
        subject,
        html_content,
        order=order,
        template_key=template_key,
    )


def send_smtp_email(recipient, recipient_name, subject, html_content, order=None, template_key='generic'):
    log = EmailLog.objects.create(
        order=order,
        recipient=recipient,
        subject=subject,
        template_key=template_key,
    )

    missing_settings = [
        setting_name
        for setting_name in ('EMAIL_HOST', 'EMAIL_HOST_USER', 'EMAIL_HOST_PASSWORD')
        if not getattr(settings, setting_name, '')
    ]
    if missing_settings:
        log.status = EmailLog.STATUS_SKIPPED
        log.error_message = f"SMTP is selected but {', '.join(missing_settings)} is not configured."
        log.save(update_fields=['status', 'error_message'])
        return log

    message = EmailMultiAlternatives(
        subject=subject,
        body=strip_tags(html_content),
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[recipient],
    )
    message.attach_alternative(html_content, 'text/html')

    try:
        message.send(fail_silently=False)
    except Exception as exc:
        log.status = EmailLog.STATUS_FAILED
        log.error_message = str(exc)
        log.save(update_fields=['status', 'error_message'])
        return log

    log.status = EmailLog.STATUS_SENT
    log.save(update_fields=['status'])
    return log


def send_brevo_email(recipient, recipient_name, subject, html_content, order=None, template_key='generic'):
    log = EmailLog.objects.create(
        order=order,
        recipient=recipient,
        subject=subject,
        template_key=template_key,
    )

    if not settings.BREVO_API_KEY:
        log.status = EmailLog.STATUS_SKIPPED
        log.error_message = 'BREVO_API_KEY is not configured.'
        log.save(update_fields=['status', 'error_message'])
        return log

    payload = {
        'sender': {'name': settings.BREVO_SENDER_NAME, 'email': settings.BREVO_SENDER_EMAIL},
        'to': [{'email': recipient, 'name': recipient_name}],
        'subject': subject,
        'htmlContent': html_content,
    }
    headers = {
        'accept': 'application/json',
        'api-key': settings.BREVO_API_KEY,
        'content-type': 'application/json',
    }

    try:
        response = requests.post('https://api.brevo.com/v3/smtp/email', json=payload, headers=headers, timeout=10)
        response.raise_for_status()
    except requests.RequestException as exc:
        log.status = EmailLog.STATUS_FAILED
        log.error_message = str(exc)
        log.save(update_fields=['status', 'error_message'])
        return log

    data = response.json() if response.content else {}
    log.status = EmailLog.STATUS_SENT
    log.brevo_message_id = data.get('messageId', '')
    log.save(update_fields=['status', 'brevo_message_id'])
    return log


def send_email(recipient, recipient_name, subject, html_content, order=None, template_key='generic'):
    active_provider = get_active_email_provider()
    if active_provider == EmailSettings.PROVIDER_BREVO:
        return send_brevo_email(
            recipient,
            recipient_name,
            subject,
            html_content,
            order=order,
            template_key=template_key,
        )
    return send_smtp_email(
        recipient,
        recipient_name,
        subject,
        html_content,
        order=order,
        template_key=template_key,
    )


def send_order_confirmation(order):
    return send_templated_email(
        order.customer_email,
        order.customer_name,
        f'Order confirmation {order.order_number}',
        'emails/order_confirmation.html',
        context={
            'email_title': 'Order confirmation',
            'email_preheader': f'Your pickup order {order.order_number} has been received.',
            'customer_name': order.customer_name,
            'order': order,
            'order_items': order.items.all(),
            'cta_label': 'View order details',
            'cta_url': get_order_detail_url(order),
        },
        order=order,
        template_key='order_confirmation',
    )


def send_order_status_update(order):
    status_notes = {
        Order.STATUS_PENDING_PAYMENT: 'Your order is confirmed. Please pay cash at the store when collecting.',
        Order.STATUS_READY: 'Your order is ready for pickup from The Color Shop.',
        Order.STATUS_COMPLETED: 'Your order has been marked as completed. Thank you for shopping with us.',
        Order.STATUS_CANCELLED: 'Your order has been cancelled. Please contact the store if this looks incorrect.',
    }
    return send_templated_email(
        order.customer_email,
        order.customer_name,
        f'Order status update {order.order_number}',
        'emails/order_status_update.html',
        context={
            'email_title': 'Order status update',
            'email_preheader': f'Your order {order.order_number} is now {order.get_status_display()}.',
            'customer_name': order.customer_name,
            'order': order,
            'status_note': status_notes.get(order.status, 'Your order status has been updated.'),
            'cta_label': 'View order details',
            'cta_url': get_order_detail_url(order),
        },
        order=order,
        template_key='order_status_update',
    )


def send_email_verification(user, verification_url):
    profile = user.customer_profile
    profile.email_verification_sent_at = timezone.now()
    profile.save(update_fields=['email_verification_sent_at', 'updated_at'])
    return send_templated_email(
        user.email,
        user.get_full_name() or user.get_username(),
        'Verify your email address for The Color Shop',
        'emails/email_verification.html',
        context={
            'email_title': 'Verify your email address',
            'email_preheader': 'Complete your account setup and confirm your email address.',
            'customer_name': user.get_full_name() or user.get_username(),
            'verification_url': verification_url,
            'cta_label': 'Verify email address',
            'cta_url': verification_url,
        },
        template_key='email_verification',
    )


def send_password_reset_email(user, reset_url):
    return send_templated_email(
        user.email,
        user.get_full_name() or user.get_username(),
        'Reset your password for The Color Shop',
        'emails/password_reset_email.html',
        context={
            'email_title': 'Reset your password',
            'email_preheader': 'Use the secure link below to choose a new password for your account.',
            'customer_name': user.get_full_name() or user.get_username(),
            'reset_url': reset_url,
            'cta_label': 'Reset password',
            'cta_url': reset_url,
        },
        template_key='password_reset',
    )
