from django.contrib import admin, messages

from .models import Category, CustomerProfile, EmailLog, Order, OrderItem, Product, ProductVariant
from .services import send_order_confirmation, send_order_status_update


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'is_active', 'sort_order')
    list_filter = ('is_active',)
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ('name', 'description')


class ProductVariantInline(admin.TabularInline):
    model = ProductVariant
    extra = 0
    fields = ('sku', 'color', 'size', 'finish', 'price', 'stock_quantity', 'low_stock_threshold', 'is_active')


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'is_active', 'is_featured', 'starting_price')
    list_filter = ('category', 'is_active', 'is_featured')
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ('name', 'description', 'variants__sku', 'variants__color', 'variants__size', 'variants__finish')
    inlines = [ProductVariantInline]


@admin.register(ProductVariant)
class ProductVariantAdmin(admin.ModelAdmin):
    list_display = ('sku', 'product', 'display_name', 'price', 'stock_quantity', 'stock_state', 'is_active')
    list_filter = ('is_active', 'product__category', 'finish')
    search_fields = ('sku', 'product__name', 'color', 'size', 'finish')


@admin.register(CustomerProfile)
class CustomerProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'phone_number', 'default_pickup_name')
    search_fields = ('user__username', 'user__email', 'user__first_name', 'user__last_name', 'phone_number')


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ('product_name', 'variant_name', 'sku', 'unit_price', 'quantity', 'line_total')
    can_delete = False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('order_number', 'customer_name', 'pickup_name', 'status', 'payment_method', 'total', 'created_at')
    list_filter = ('status', 'payment_method', 'created_at')
    search_fields = ('order_number', 'customer_name', 'customer_email', 'pickup_name', 'items__sku')
    readonly_fields = ('order_number', 'subtotal', 'total', 'created_at', 'updated_at')
    inlines = [OrderItemInline]
    actions = ('send_confirmation_email', 'send_status_update_email')
    fieldsets = (
        ('Order', {'fields': ('order_number', 'user', 'status', 'payment_method', 'subtotal', 'total')}),
        ('Customer', {'fields': ('customer_name', 'customer_email', 'customer_phone')}),
        ('Pickup', {'fields': ('pickup_name', 'pickup_phone', 'pickup_location', 'pickup_address', 'special_instructions')}),
        ('Dates', {'fields': ('created_at', 'updated_at')}),
    )

    def save_model(self, request, obj, form, change):
        previous_status = None
        if change:
            previous_status = Order.objects.only('status').get(pk=obj.pk).status
        super().save_model(request, obj, form, change)
        if change and 'status' in form.changed_data and previous_status != obj.status:
            send_order_status_update(obj)
            self.message_user(request, f'Status email logged for {obj.order_number}.', level=messages.INFO)

    @admin.action(description='Send order confirmation email')
    def send_confirmation_email(self, request, queryset):
        count = 0
        for order in queryset.prefetch_related('items'):
            send_order_confirmation(order)
            count += 1
        self.message_user(request, f'Confirmation email logged for {count} order(s).', level=messages.INFO)

    @admin.action(description='Send order status update email')
    def send_status_update_email(self, request, queryset):
        count = 0
        for order in queryset:
            send_order_status_update(order)
            count += 1
        self.message_user(request, f'Status email logged for {count} order(s).', level=messages.INFO)


@admin.register(EmailLog)
class EmailLogAdmin(admin.ModelAdmin):
    list_display = ('template_key', 'recipient', 'status', 'order', 'created_at')
    list_filter = ('status', 'template_key', 'created_at')
    search_fields = ('recipient', 'subject', 'brevo_message_id', 'order__order_number')
    readonly_fields = ('order', 'recipient', 'subject', 'template_key', 'brevo_message_id', 'status', 'error_message', 'created_at')
