import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from django.utils import timezone


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Category(TimeStampedModel):
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'name']
        verbose_name_plural = 'categories'

    def __str__(self):
        return self.name


class Product(TimeStampedModel):
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name='products')
    name = models.CharField(max_length=180)
    slug = models.SlugField(max_length=200, unique=True)
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to='products/', blank=True)
    is_active = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False)

    class Meta:
        ordering = ['name']
        indexes = [models.Index(fields=['slug']), models.Index(fields=['is_active'])]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('product_detail', kwargs={'slug': self.slug})

    @property
    def active_variants(self):
        return self.variants.filter(is_active=True)

    @property
    def starting_price(self):
        variant = self.active_variants.order_by('price').first()
        return variant.price if variant else None


class ProductVariant(TimeStampedModel):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='variants')
    sku = models.CharField(max_length=64, unique=True)
    color = models.CharField(max_length=80, blank=True)
    size = models.CharField(max_length=80, blank=True)
    finish = models.CharField(max_length=80, blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    stock_quantity = models.PositiveIntegerField(default=0)
    low_stock_threshold = models.PositiveIntegerField(default=5)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['product__name', 'color', 'size', 'finish', 'sku']
        indexes = [models.Index(fields=['sku']), models.Index(fields=['is_active'])]

    def __str__(self):
        return f'{self.product.name} - {self.display_name}'

    @property
    def display_name(self):
        options = [value for value in [self.color, self.size, self.finish] if value]
        return ' / '.join(options) if options else self.sku

    @property
    def is_in_stock(self):
        return self.is_active and self.stock_quantity > 0

    @property
    def stock_state(self):
        if not self.is_active:
            return 'inactive'
        if self.stock_quantity == 0:
            return 'out of stock'
        if self.stock_quantity <= self.low_stock_threshold:
            return 'low stock'
        return 'in stock'

    def clean(self):
        if self.price < Decimal('0.00'):
            raise ValidationError({'price': 'Price cannot be negative.'})

    def reserve_stock(self, quantity):
        if quantity < 1:
            raise ValidationError('Quantity must be at least 1.')
        if quantity > self.stock_quantity:
            raise ValidationError(f'Only {self.stock_quantity} available for {self.sku}.')
        self.stock_quantity -= quantity
        self.save(update_fields=['stock_quantity', 'updated_at'])


class CustomerProfile(TimeStampedModel):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='customer_profile')
    phone_number = models.CharField(max_length=40, blank=True)
    default_pickup_name = models.CharField(max_length=160, blank=True)

    def __str__(self):
        return self.user.get_full_name() or self.user.get_username()


class Order(TimeStampedModel):
    STATUS_PENDING_PAYMENT = 'pending_pickup_payment'
    STATUS_READY = 'ready_for_pickup'
    STATUS_COMPLETED = 'completed'
    STATUS_CANCELLED = 'cancelled'

    STATUS_CHOICES = [
        (STATUS_PENDING_PAYMENT, 'Pending pickup payment'),
        (STATUS_READY, 'Ready for pickup'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]

    PAYMENT_CASH = 'cash_at_store'
    PAYMENT_CHOICES = [(PAYMENT_CASH, 'Cash at store')]

    order_number = models.CharField(max_length=32, unique=True, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='orders')
    customer_name = models.CharField(max_length=160)
    customer_email = models.EmailField()
    customer_phone = models.CharField(max_length=40, blank=True)
    pickup_name = models.CharField(max_length=160)
    pickup_phone = models.CharField(max_length=40, blank=True)
    pickup_location = models.CharField(max_length=160, default='The Color Shop')
    pickup_address = models.CharField(max_length=255, default="569J+3VH, Togafu'afu'a Rd, Apia, Samoa")
    payment_method = models.CharField(max_length=30, choices=PAYMENT_CHOICES, default=PAYMENT_CASH)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default=STATUS_PENDING_PAYMENT)
    special_instructions = models.TextField(blank=True)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    total = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['order_number']), models.Index(fields=['status'])]

    def __str__(self):
        return self.order_number

    def save(self, *args, **kwargs):
        if not self.order_number:
            today = timezone.localtime().strftime('%Y%m%d')
            self.order_number = f'TCS-{today}-{uuid.uuid4().hex[:6].upper()}'
        super().save(*args, **kwargs)


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product_variant = models.ForeignKey(ProductVariant, on_delete=models.SET_NULL, null=True, blank=True)
    product_name = models.CharField(max_length=180)
    variant_name = models.CharField(max_length=220, blank=True)
    sku = models.CharField(max_length=64, blank=True)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveIntegerField()
    line_total = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f'{self.quantity} x {self.product_name}'

    def save(self, *args, **kwargs):
        self.line_total = self.unit_price * self.quantity
        super().save(*args, **kwargs)


class EmailLog(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_SENT = 'sent'
    STATUS_FAILED = 'failed'
    STATUS_SKIPPED = 'skipped'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_SENT, 'Sent'),
        (STATUS_FAILED, 'Failed'),
        (STATUS_SKIPPED, 'Skipped'),
    ]

    order = models.ForeignKey(Order, on_delete=models.SET_NULL, null=True, blank=True, related_name='email_logs')
    recipient = models.EmailField()
    subject = models.CharField(max_length=255)
    template_key = models.CharField(max_length=80)
    brevo_message_id = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.template_key} to {self.recipient}'
