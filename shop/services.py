from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.html import escape
import requests

from .models import EmailLog, Order, OrderItem, ProductVariant, StoreLocation


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


def send_order_confirmation(order):
    item_rows = ''.join(
        f'<li>{item.quantity} x {escape(item.product_name)} ({escape(item.variant_name)}) - WST {item.line_total}</li>'
        for item in order.items.all()
    )
    html = f'''
        <p>Talofa {escape(order.customer_name)},</p>
        <p>Your pickup order <strong>{order.order_number}</strong> has been received.</p>
        <ul>{item_rows}</ul>
        <p><strong>Total due at pickup:</strong> WST {order.total}</p>
        <p>Pickup from {escape(order.pickup_address)}. Please pay cash at the store when collecting.</p>
        <p>Contact: {escape(settings.STORE_CONTACT_PHONE)}</p>
    '''
    return send_brevo_email(
        order.customer_email,
        order.customer_name,
        f'Order confirmation {order.order_number}',
        html,
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
    html = f'''
        <p>Talofa {escape(order.customer_name)},</p>
        <p>Your order <strong>{order.order_number}</strong> status is now <strong>{escape(order.get_status_display())}</strong>.</p>
        <p>{escape(status_notes.get(order.status, 'Your order status has been updated.'))}</p>
        <p>Pickup location: {escape(order.pickup_address)}</p>
        <p>Contact: {escape(settings.STORE_CONTACT_PHONE)}</p>
    '''
    return send_brevo_email(
        order.customer_email,
        order.customer_name,
        f'Order status update {order.order_number}',
        html,
        order=order,
        template_key='order_status_update',
    )
