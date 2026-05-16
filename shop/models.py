import uuid
import mimetypes
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from django.utils import timezone

from .media_utils import convert_image_file_to_webp, should_convert_image


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


class ProductTag(TimeStampedModel):
    name = models.CharField(max_length=80, unique=True)
    slug = models.SlugField(max_length=100, unique=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class StoreLocation(TimeStampedModel):
    name = models.CharField(max_length=120, unique=True)
    address = models.CharField(max_length=255)
    pickup_instructions = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)
    is_pickup_enabled = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'name']

    def __str__(self):
        return self.name

    @classmethod
    def ensure_default_location(cls):
        location, _created = cls.objects.get_or_create(
            name='Apia Store',
            defaults={'address': settings.STORE_PICKUP_ADDRESS, 'sort_order': 1},
        )
        return location


class EmailSettings(TimeStampedModel):
    PROVIDER_SMTP = 'smtp'
    PROVIDER_BREVO = 'brevo'

    PROVIDER_CHOICES = [
        (PROVIDER_SMTP, 'SMTP'),
        (PROVIDER_BREVO, 'Brevo'),
    ]

    email_provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES, default=PROVIDER_SMTP)

    class Meta:
        verbose_name = 'email settings'
        verbose_name_plural = 'email settings'

    def __str__(self):
        return f'Email provider: {self.get_email_provider_display()}'

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_solo(cls):
        settings_obj, _created = cls.objects.get_or_create(pk=1, defaults={'email_provider': cls.PROVIDER_SMTP})
        return settings_obj


class Product(TimeStampedModel):
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name='products')
    name = models.CharField(max_length=180)
    slug = models.SlugField(max_length=200, unique=True)
    description = models.TextField(blank=True)
    meta_title = models.CharField(max_length=180, blank=True)
    meta_description = models.CharField(max_length=320, blank=True)
    image = models.ImageField(upload_to='products/', blank=True)
    is_active = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False)
    tags = models.ManyToManyField(ProductTag, blank=True, related_name='products')
    pickup_locations = models.ManyToManyField(StoreLocation, blank=True, related_name='products')

    class Meta:
        ordering = ['name']
        indexes = [models.Index(fields=['slug']), models.Index(fields=['is_active'])]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('product_detail', kwargs={'slug': self.slug})

    @property
    def seo_page_title(self):
        return self.meta_title or self.name

    @property
    def seo_summary(self):
        return (self.meta_description or self.description or 'Available for pickup from The Color Shop.')[:320]

    @property
    def active_variants(self):
        return self.variants.filter(is_active=True)

    @property
    def starting_price(self):
        prices = [variant.current_price for variant in self.active_variants]
        return min(prices) if prices else None

    @property
    def gallery_media(self):
        prefetched_media = getattr(self, '_prefetched_objects_cache', {}).get('media_assets')
        if prefetched_media is not None:
            return list(prefetched_media)
        return list(self.media_assets.all())

    @property
    def primary_media(self):
        media_items = self.gallery_media
        return media_items[0] if media_items else None

    @property
    def primary_image_url(self):
        for media_item in self.gallery_media:
            if media_item.is_image:
                return media_item.file.url
        return self.image.url if self.image else ''

    @property
    def available_pickup_locations(self):
        prefetched_locations = getattr(self, '_prefetched_objects_cache', {}).get('pickup_locations')
        if prefetched_locations is not None and prefetched_locations:
            return [location for location in prefetched_locations if location.is_active and location.is_pickup_enabled]

        locations = list(self.pickup_locations.filter(is_active=True, is_pickup_enabled=True))
        if locations:
            return locations
        return list(StoreLocation.objects.filter(is_active=True, is_pickup_enabled=True))


class ProductMedia(TimeStampedModel):
    TYPE_IMAGE = 'image'
    TYPE_VIDEO = 'video'
    TYPE_AUDIO = 'audio'
    TYPE_FILE = 'file'

    TYPE_CHOICES = [
        (TYPE_IMAGE, 'Image'),
        (TYPE_VIDEO, 'Video'),
        (TYPE_AUDIO, 'Audio'),
        (TYPE_FILE, 'File'),
    ]

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='media_assets')
    file = models.FileField(upload_to='products/media/')
    media_type = models.CharField(max_length=10, choices=TYPE_CHOICES, blank=True)
    alt_text = models.CharField(max_length=180, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_primary = models.BooleanField(default=False)

    class Meta:
        ordering = ['-is_primary', 'sort_order', 'id']

    def __str__(self):
        return f'{self.product.name} media {self.id or "new"}'

    @staticmethod
    def detect_media_type(file_obj):
        content_type = getattr(file_obj, 'content_type', '') or ''
        guessed_type = mimetypes.guess_type(getattr(file_obj, 'name', ''))[0] or ''
        resolved_type = content_type or guessed_type
        if resolved_type.startswith('image/'):
            return ProductMedia.TYPE_IMAGE
        if resolved_type.startswith('video/'):
            return ProductMedia.TYPE_VIDEO
        if resolved_type.startswith('audio/'):
            return ProductMedia.TYPE_AUDIO
        return ProductMedia.TYPE_FILE

    @property
    def is_image(self):
        return self.media_type == self.TYPE_IMAGE

    @property
    def is_video(self):
        return self.media_type == self.TYPE_VIDEO

    @property
    def is_audio(self):
        return self.media_type == self.TYPE_AUDIO

    @property
    def display_name(self):
        if self.alt_text:
            return self.alt_text
        return self.file.name.rsplit('/', 1)[-1]

    def save(self, *args, **kwargs):
        previous_file_name = ''
        if self.pk:
            previous_file_name = type(self).objects.filter(pk=self.pk).values_list('file', flat=True).first() or ''

        if not self.media_type:
            self.media_type = self.detect_media_type(self.file)

        if self.file and should_convert_image(self.file, self.media_type):
            self.file = convert_image_file_to_webp(self.file, output_name=self.file.name)

        if not self.sort_order:
            max_sort_order = self.product.media_assets.exclude(pk=self.pk).aggregate(models.Max('sort_order'))['sort_order__max'] or 0
            self.sort_order = max_sort_order + 1
        super().save(*args, **kwargs)

        if previous_file_name and previous_file_name != self.file.name:
            self.file.storage.delete(previous_file_name)

        if self.is_primary:
            self.product.media_assets.exclude(pk=self.pk).filter(is_primary=True).update(is_primary=False)
        elif not self.product.media_assets.exclude(pk=self.pk).filter(is_primary=True).exists():
            self.product.media_assets.filter(pk=self.pk).update(is_primary=True)
            self.is_primary = True


class ProductOption(TimeStampedModel):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='options')
    name = models.CharField(max_length=80)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'id']
        constraints = [models.UniqueConstraint(fields=['product', 'name'], name='unique_product_option_name')]

    def __str__(self):
        return f'{self.product.name} - {self.name}'


class ProductOptionValue(TimeStampedModel):
    option = models.ForeignKey(ProductOption, on_delete=models.CASCADE, related_name='option_values')
    value = models.CharField(max_length=80)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['option__sort_order', 'sort_order', 'id']
        constraints = [models.UniqueConstraint(fields=['option', 'value'], name='unique_option_value')]

    def __str__(self):
        return f'{self.option.name}: {self.value}'


class ProductVariant(TimeStampedModel):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='variants')
    sku = models.CharField(max_length=64, unique=True)
    color = models.CharField(max_length=80, blank=True)
    size = models.CharField(max_length=80, blank=True)
    finish = models.CharField(max_length=80, blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    sale_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    stock_quantity = models.PositiveIntegerField(default=0)
    low_stock_threshold = models.PositiveIntegerField(default=5)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['product__name', 'sku']
        indexes = [models.Index(fields=['sku']), models.Index(fields=['is_active'])]

    def __str__(self):
        return f'{self.product.name} - {self.display_name}'

    @property
    def selected_option_items(self):
        if not self.pk:
            return []
        return list(
            self.selected_options.select_related('option', 'option_value').order_by('sort_order', 'option__sort_order', 'id')
        )

    @property
    def option_summary(self):
        selected_items = self.selected_option_items
        if selected_items:
            return [(item.option.name, item.option_value.value) for item in selected_items]
        legacy_pairs = [
            ('Color', self.color),
            ('Size', self.size),
            ('Finish', self.finish),
        ]
        return [(name, value) for name, value in legacy_pairs if value]

    @property
    def display_name(self):
        options = [value for _name, value in self.option_summary]
        return ' / '.join(options) if options else self.sku

    @property
    def current_price(self):
        if self.sale_price is not None and self.sale_price > Decimal('0.00') and self.sale_price < self.price:
            return self.sale_price
        return self.price

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
        if self.price is not None and self.price < Decimal('0.00'):
            raise ValidationError({'price': 'Price cannot be negative.'})
        if self.sale_price is not None:
            if self.sale_price < Decimal('0.00'):
                raise ValidationError({'sale_price': 'Sale price cannot be negative.'})
            if self.price is not None and self.sale_price >= self.price:
                raise ValidationError({'sale_price': 'Sale price must be lower than the regular price.'})

    def quantity_at_location(self, location):
        if not location:
            return self.stock_quantity

        prefetched_levels = getattr(self, '_prefetched_objects_cache', {}).get('inventory_levels')
        if prefetched_levels is not None:
            matching_level = next((level for level in prefetched_levels if level.location_id == location.id), None)
            if matching_level is not None:
                return matching_level.quantity
            return 0 if prefetched_levels else self.stock_quantity

        inventory_level = self.inventory_levels.filter(location=location).first()
        if inventory_level is not None:
            return inventory_level.quantity
        if self.inventory_levels.exists():
            return 0
        return self.stock_quantity

    def sync_stock_quantity_from_inventory_levels(self):
        total_quantity = self.inventory_levels.aggregate(models.Sum('quantity'))['quantity__sum']
        if total_quantity is None:
            return
        if self.stock_quantity != total_quantity:
            self.stock_quantity = total_quantity
            self.save(update_fields=['stock_quantity', 'updated_at'])

    def reserve_stock(self, quantity, location=None):
        if quantity < 1:
            raise ValidationError('Quantity must be at least 1.')

        if location:
            inventory_level = self.inventory_levels.select_for_update().filter(location=location).first()
            if inventory_level is not None:
                if quantity > inventory_level.quantity:
                    raise ValidationError(f'Only {inventory_level.quantity} available for {self.sku} at {location.name}.')
                inventory_level.quantity -= quantity
                inventory_level.save(update_fields=['quantity', 'updated_at'])
                self.sync_stock_quantity_from_inventory_levels()
                return
            if self.inventory_levels.exists():
                raise ValidationError(f'{self.sku} is not stocked at {location.name}.')

        if quantity > self.stock_quantity:
            raise ValidationError(f'Only {self.stock_quantity} available for {self.sku}.')
        self.stock_quantity -= quantity
        self.save(update_fields=['stock_quantity', 'updated_at'])


class VariantInventoryLevel(TimeStampedModel):
    variant = models.ForeignKey(ProductVariant, on_delete=models.CASCADE, related_name='inventory_levels')
    location = models.ForeignKey(StoreLocation, on_delete=models.CASCADE, related_name='inventory_levels')
    quantity = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['location__sort_order', 'location__name', 'id']
        constraints = [models.UniqueConstraint(fields=['variant', 'location'], name='unique_variant_inventory_location')]

    def __str__(self):
        return f'{self.variant.sku} @ {self.location.name}'


class ProductVariantSelectedOption(TimeStampedModel):
    variant = models.ForeignKey(ProductVariant, on_delete=models.CASCADE, related_name='selected_options')
    option = models.ForeignKey(ProductOption, on_delete=models.CASCADE, related_name='variant_selections')
    option_value = models.ForeignKey(ProductOptionValue, on_delete=models.CASCADE, related_name='variant_selections')
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'option__sort_order', 'id']
        constraints = [models.UniqueConstraint(fields=['variant', 'option'], name='unique_variant_option_selection')]

    def __str__(self):
        return f'{self.variant.sku} - {self.option.name}: {self.option_value.value}'

    def clean(self):
        if self.option.product_id != self.variant.product_id:
            raise ValidationError({'option': 'Selected option must belong to the same product as the variant.'})
        if self.option_value.option_id != self.option_id:
            raise ValidationError({'option_value': 'Selected value must belong to the chosen option.'})


class CustomerProfile(TimeStampedModel):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='customer_profile')
    phone_number = models.CharField(max_length=40, blank=True)
    default_pickup_name = models.CharField(max_length=160, blank=True)
    is_email_verified = models.BooleanField(default=False)
    email_verified_at = models.DateTimeField(null=True, blank=True)
    email_verification_sent_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.user.get_full_name() or self.user.get_username()

    def mark_email_verified(self):
        self.is_email_verified = True
        self.email_verified_at = timezone.now()
        self.save(update_fields=['is_email_verified', 'email_verified_at', 'updated_at'])


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
