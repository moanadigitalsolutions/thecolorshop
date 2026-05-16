from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.views import LoginView, redirect_to_login
from django.http import HttpResponse
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, F, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from tablib import Dataset

from .forms import EmailSettingsStaffForm, OrderStaffStatusForm, ProductOptionStaffFormSet, ProductStaffForm, ProductVariantStaffFormSet, StaffAuthenticationForm, StaffCatalogExportForm, StaffCatalogImportForm, StoreLocationStaffForm, build_product_option_definitions
from .import_export_resources import IMPORT_EXPORT_DEFINITIONS, get_import_export_definition
from .models import Category, CustomerProfile, EmailLog, EmailSettings, Order, Product, ProductVariant, StoreLocation
from .services import send_order_status_update


STAFF_PRODUCTS_PAGE_SIZE = 20
STAFF_ORDERS_PAGE_SIZE = 50
STAFF_CUSTOMERS_PAGE_SIZE = 50
STAFF_EMAIL_LOGS_PAGE_SIZE = 75


class StaffLoginView(LoginView):
    authentication_form = StaffAuthenticationForm
    redirect_authenticated_user = True
    template_name = 'staff/login.html'

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.user.is_staff:
            return redirect('staff:dashboard')
        return super().dispatch(request, *args, **kwargs)

    def get_success_url(self):
        return self.get_redirect_url() or reverse_lazy('staff:dashboard')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['staff_portal_entry_url'] = reverse('staff:dashboard')
        return context


def staff_required(view_func):
    @wraps(view_func)
    def wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path(), login_url=reverse('staff:login'))
        if not request.user.is_staff:
            messages.error(request, 'Your account does not have access to the staff portal.')
            return redirect('product_list')
        return view_func(request, *args, **kwargs)

    return wrapped_view


def build_page_query(request):
    params = request.GET.copy()
    params.pop('page', None)
    return params.urlencode()


@staff_required
def dashboard(request):
    recent_orders = Order.objects.select_related('user').prefetch_related('items')[:6]
    low_stock_variants = ProductVariant.objects.select_related('product').filter(
        is_active=True,
        stock_quantity__gt=0,
        stock_quantity__lte=F('low_stock_threshold'),
    )[:6]
    pending_emails = EmailLog.objects.select_related('order').filter(
        status__in=[EmailLog.STATUS_FAILED, EmailLog.STATUS_SKIPPED]
    )[:6]

    context = {
        'metrics': {
            'active_products': Product.objects.filter(is_active=True).count(),
            'active_variants': ProductVariant.objects.filter(is_active=True).count(),
            'low_stock_variants': ProductVariant.objects.filter(
                is_active=True,
                stock_quantity__gt=0,
                stock_quantity__lte=F('low_stock_threshold'),
            ).count(),
            'out_of_stock_variants': ProductVariant.objects.filter(is_active=True, stock_quantity=0).count(),
            'pending_orders': Order.objects.filter(status=Order.STATUS_PENDING_PAYMENT).count(),
            'ready_orders': Order.objects.filter(status=Order.STATUS_READY).count(),
            'customer_profiles': CustomerProfile.objects.count(),
            'email_attention': EmailLog.objects.filter(
                status__in=[EmailLog.STATUS_FAILED, EmailLog.STATUS_SKIPPED]
            ).count(),
        },
        'recent_orders': recent_orders,
        'low_stock_variants': low_stock_variants,
        'email_attention_logs': pending_emails,
        'order_groups': [
            {
                'label': 'Pending pickup payment',
                'count': Order.objects.filter(status=Order.STATUS_PENDING_PAYMENT).count(),
                'helper': 'Orders waiting for payment at pickup',
                'status_class': 'pending',
            },
            {
                'label': 'Ready for pickup',
                'count': Order.objects.filter(status=Order.STATUS_READY).count(),
                'helper': 'Orders staff can release today',
                'status_class': 'ready',
            },
            {
                'label': 'Completed today',
                'count': Order.objects.filter(status=Order.STATUS_COMPLETED).count(),
                'helper': 'Closed pickup orders in the system',
                'status_class': 'completed',
            },
        ],
        'inventory_alerts': [
            {
                'label': 'Low stock',
                'count': ProductVariant.objects.filter(
                    is_active=True,
                    stock_quantity__gt=0,
                    stock_quantity__lte=F('low_stock_threshold'),
                ).count(),
                'helper': 'Variants at or below their threshold',
                'tone': 'warning',
            },
            {
                'label': 'Out of stock',
                'count': ProductVariant.objects.filter(is_active=True, stock_quantity=0).count(),
                'helper': 'Variants unavailable for pickup orders',
                'tone': 'danger',
            },
            {
                'label': 'Featured products',
                'count': Product.objects.filter(is_active=True, is_featured=True).count(),
                'helper': 'Products highlighted on the storefront',
                'tone': 'info',
            },
        ],
    }
    return render(request, 'staff/dashboard.html', context)


@staff_required
def product_catalog(request):
    query = request.GET.get('q', '').strip()
    category_slug = request.GET.get('category', '').strip()
    status_filter = request.GET.get('status', '').strip()

    categories = list(Category.objects.filter(is_active=True))
    products = Product.objects.select_related('category').prefetch_related('variants').order_by('name')

    if query:
        products = products.filter(
            Q(name__icontains=query)
            | Q(description__icontains=query)
            | Q(variants__sku__icontains=query)
            | Q(variants__color__icontains=query)
            | Q(variants__selected_options__option__name__icontains=query)
            | Q(variants__selected_options__option_value__value__icontains=query)
            | Q(variants__finish__icontains=query)
        ).distinct()

    if category_slug:
        products = products.filter(category__slug=category_slug)

    if status_filter == 'active':
        products = products.filter(is_active=True)
    elif status_filter == 'inactive':
        products = products.filter(is_active=False)
    elif status_filter == 'featured':
        products = products.filter(is_featured=True)

    product_rows = []
    for product in products:
        active_variants = [variant for variant in product.variants.all() if variant.is_active]
        low_stock_count = sum(
            1
            for variant in active_variants
            if variant.stock_quantity > 0 and variant.stock_quantity <= variant.low_stock_threshold
        )
        out_of_stock_count = sum(1 for variant in active_variants if variant.stock_quantity == 0)
        product_rows.append(
            {
                'product': product,
                'active_variant_count': len(active_variants),
                'low_stock_count': low_stock_count,
                'out_of_stock_count': out_of_stock_count,
                'variant_preview': active_variants[:3],
                'stock_state': 'at-risk' if low_stock_count or out_of_stock_count else 'healthy',
            }
        )

    paginator = Paginator(product_rows, STAFF_PRODUCTS_PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get('page'))

    context = {
        'categories': categories,
        'filters': {'q': query, 'category': category_slug, 'status': status_filter},
        'is_paginated': page_obj.has_other_pages(),
        'page_obj': page_obj,
        'page_query': build_page_query(request),
        'product_rows': page_obj.object_list,
        'product_metrics': {
            'visible': len(product_rows),
            'featured': sum(1 for row in product_rows if row['product'].is_featured),
            'inactive': sum(1 for row in product_rows if not row['product'].is_active),
            'attention': sum(1 for row in product_rows if row['stock_state'] == 'at-risk'),
        },
        'at_risk_products': [row for row in product_rows if row['stock_state'] == 'at-risk'][:5],
    }
    return render(request, 'staff/products.html', context)


def _serialize_import_errors(result):
    error_rows = []

    for row in result.invalid_rows:
        messages_for_row = []
        for field_name, field_errors in row.error.error_dict.items():
            messages_for_row.append(f'{field_name}: {"; ".join(str(error) for error in field_errors)}')
        error_rows.append({'number': row.number, 'messages': messages_for_row, 'values': row.values})

    for row in result.error_rows:
        if hasattr(row.error, 'error_dict'):
            messages_for_row = []
            for field_name, field_errors in row.error.error_dict.items():
                messages_for_row.append(f'{field_name}: {"; ".join(str(error) for error in field_errors)}')
        else:
            messages_for_row = [str(row.error)]
        error_rows.append({'number': row.number, 'messages': messages_for_row, 'values': getattr(row, 'values', {})})

    return error_rows


@staff_required
def product_import_export(request):
    export_form = StaffCatalogExportForm(request.GET or None)
    import_form = StaffCatalogImportForm(request.POST or None, request.FILES or None)
    import_errors = []

    if request.method == 'GET' and request.GET.get('export') and export_form.is_valid():
        resource_definition = get_import_export_definition(export_form.cleaned_data['resource'])
        resource = resource_definition['resource_class']()
        dataset = resource.export()
        response = HttpResponse(dataset.csv, content_type='text/csv; charset=utf-8')
        timestamp = timezone.now().strftime('%Y%m%d-%H%M%S')
        response['Content-Disposition'] = f'attachment; filename="tcs-{resource_definition["filename"]}-{timestamp}.csv"'
        return response

    if request.method == 'POST' and import_form.is_valid():
        resource_definition = get_import_export_definition(import_form.cleaned_data['resource'])
        resource = resource_definition['resource_class']()
        uploaded_text = import_form.cleaned_data['import_file'].read().decode('utf-8-sig')
        dataset = Dataset().load(uploaded_text, format='csv')
        preview = resource.import_data(
            dataset,
            dry_run=True,
            raise_errors=False,
            use_transactions=True,
            rollback_on_validation_errors=True,
            collect_failed_rows=True,
        )
        if preview.has_errors() or preview.has_validation_errors():
            import_errors = _serialize_import_errors(preview)
            messages.error(request, 'Import validation failed. Fix the rows below and try again.')
        else:
            result = resource.import_data(
                dataset,
                dry_run=False,
                raise_errors=False,
                use_transactions=True,
                rollback_on_validation_errors=True,
            )
            messages.success(
                request,
                (
                    f'{resource_definition["label"]} import completed. '
                    f'Added {result.totals.get("new", 0)}, '
                    f'updated {result.totals.get("update", 0)}, '
                    f'skipped {result.totals.get("skip", 0)}.'
                ),
            )
            return redirect('staff:product_import_export')

    context = {
        'export_form': export_form,
        'import_form': import_form,
        'import_errors': import_errors,
        'resource_definitions': IMPORT_EXPORT_DEFINITIONS,
    }
    return render(request, 'staff/product_import_export.html', context)


@staff_required
def location_catalog(request):
    StoreLocation.ensure_default_location()
    locations = StoreLocation.objects.order_by('sort_order', 'name')
    form = StoreLocationStaffForm(request.POST or None)

    if request.method == 'POST' and form.is_valid():
        location = form.save()
        messages.success(request, f'{location.name} saved successfully.')
        return redirect('staff:locations')

    context = {
        'location_form': form,
        'locations': locations,
        'editing_location': None,
        'location_metrics': {
            'total': locations.count(),
            'pickup_enabled': locations.filter(is_pickup_enabled=True, is_active=True).count(),
            'inactive': locations.filter(is_active=False).count(),
        },
    }
    return render(request, 'staff/locations.html', context)


@staff_required
def location_edit(request, pk):
    StoreLocation.ensure_default_location()
    location = get_object_or_404(StoreLocation, pk=pk)
    form = StoreLocationStaffForm(request.POST or None, instance=location)

    if request.method == 'POST' and form.is_valid():
        saved_location = form.save()
        messages.success(request, f'{saved_location.name} updated successfully.')
        return redirect('staff:locations')

    locations = StoreLocation.objects.order_by('sort_order', 'name')
    context = {
        'location_form': form,
        'locations': locations,
        'editing_location': location,
        'location_metrics': {
            'total': locations.count(),
            'pickup_enabled': locations.filter(is_pickup_enabled=True, is_active=True).count(),
            'inactive': locations.filter(is_active=False).count(),
        },
    }
    return render(request, 'staff/locations.html', context)


@staff_required
def email_settings(request):
    settings_record = EmailSettings.get_solo()
    form = EmailSettingsStaffForm(request.POST or None, instance=settings_record)

    if request.method == 'POST' and form.is_valid():
        saved_settings = form.save()
        messages.success(request, f'Email delivery updated. {saved_settings.get_email_provider_display()} is now active.')
        return redirect('staff:email_settings')

    smtp_ready = all(getattr(settings, setting_name, '') for setting_name in ('EMAIL_HOST', 'EMAIL_HOST_USER', 'EMAIL_HOST_PASSWORD'))
    context = {
        'email_settings_form': form,
        'settings_record': settings_record,
        'provider_metrics': {
            'active_provider': settings_record.get_email_provider_display(),
            'smtp_ready': smtp_ready,
            'brevo_ready': bool(settings.BREVO_API_KEY),
        },
        'provider_details': {
            'smtp_host': settings.EMAIL_HOST,
            'smtp_port': settings.EMAIL_PORT,
            'smtp_username': settings.EMAIL_HOST_USER,
            'brevo_sender': settings.BREVO_SENDER_EMAIL,
        },
    }
    return render(request, 'staff/email_settings.html', context)


@staff_required
def order_catalog(request):
    query = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', '').strip()

    orders = Order.objects.select_related('user').prefetch_related('items').order_by('-created_at')
    if query:
        orders = orders.filter(
            Q(order_number__icontains=query)
            | Q(customer_name__icontains=query)
            | Q(customer_email__icontains=query)
            | Q(pickup_name__icontains=query)
            | Q(items__sku__icontains=query)
        ).distinct()
    if status_filter:
        orders = orders.filter(status=status_filter)

    paginator = Paginator(orders, STAFF_ORDERS_PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get('page'))

    context = {
        'is_paginated': page_obj.has_other_pages(),
        'orders': page_obj.object_list,
        'filters': {'q': query, 'status': status_filter},
        'page_obj': page_obj,
        'page_query': build_page_query(request),
        'order_metrics': {
            'visible': orders.count(),
            'pending': orders.filter(status=Order.STATUS_PENDING_PAYMENT).count(),
            'ready': orders.filter(status=Order.STATUS_READY).count(),
            'completed': orders.filter(status=Order.STATUS_COMPLETED).count(),
        },
        'status_choices': Order.STATUS_CHOICES,
    }
    return render(request, 'staff/orders.html', context)


@staff_required
def order_detail(request, order_number):
    order = get_object_or_404(Order.objects.select_related('user').prefetch_related('items'), order_number=order_number)
    form = OrderStaffStatusForm(request.POST or None, instance=order)
    previous_status = order.status

    if request.method == 'POST' and form.is_valid():
        updated_order = form.save()
        if previous_status != updated_order.status:
            send_order_status_update(updated_order)
            messages.success(request, f'{updated_order.order_number} updated and status email logged.')
        else:
            messages.success(request, f'{updated_order.order_number} updated successfully.')
        return redirect('staff:order_detail', order_number=updated_order.order_number)

    return render(request, 'staff/order_detail.html', {'order': order, 'order_form': form})


@staff_required
def customer_catalog(request):
    query = request.GET.get('q', '').strip()

    customers = CustomerProfile.objects.select_related('user').annotate(order_count=Count('user__orders')).order_by('-updated_at')
    if query:
        customers = customers.filter(
            Q(user__username__icontains=query)
            | Q(user__first_name__icontains=query)
            | Q(user__last_name__icontains=query)
            | Q(user__email__icontains=query)
            | Q(phone_number__icontains=query)
            | Q(default_pickup_name__icontains=query)
        )

    paginator = Paginator(customers, STAFF_CUSTOMERS_PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get('page'))

    context = {
        'customers': page_obj.object_list,
        'filters': {'q': query},
        'is_paginated': page_obj.has_other_pages(),
        'customer_metrics': {
            'visible': customers.count(),
            'with_phone': customers.exclude(phone_number='').count(),
            'with_pickup_name': customers.exclude(default_pickup_name='').count(),
        },
        'page_obj': page_obj,
        'page_query': build_page_query(request),
    }
    return render(request, 'staff/customers.html', context)


@staff_required
def email_log_catalog(request):
    query = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', '').strip()
    template_filter = request.GET.get('template', '').strip()

    email_logs = EmailLog.objects.select_related('order').order_by('-created_at')
    if query:
        email_logs = email_logs.filter(
            Q(recipient__icontains=query)
            | Q(subject__icontains=query)
            | Q(order__order_number__icontains=query)
            | Q(error_message__icontains=query)
        )
    if status_filter:
        email_logs = email_logs.filter(status=status_filter)
    if template_filter:
        email_logs = email_logs.filter(template_key=template_filter)

    paginator = Paginator(email_logs, STAFF_EMAIL_LOGS_PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get('page'))

    template_choices = list(EmailLog.objects.order_by().values_list('template_key', flat=True).distinct())
    context = {
        'email_logs': page_obj.object_list,
        'filters': {'q': query, 'status': status_filter, 'template': template_filter},
        'is_paginated': page_obj.has_other_pages(),
        'page_obj': page_obj,
        'page_query': build_page_query(request),
        'status_choices': EmailLog.STATUS_CHOICES,
        'template_choices': template_choices,
        'email_metrics': {
            'visible': email_logs.count(),
            'failed': email_logs.filter(status=EmailLog.STATUS_FAILED).count(),
            'skipped': email_logs.filter(status=EmailLog.STATUS_SKIPPED).count(),
            'sent': email_logs.filter(status=EmailLog.STATUS_SENT).count(),
        },
    }
    return render(request, 'staff/email_logs.html', context)


def _save_product_editor(request, product=None):
    product_form = ProductStaffForm(request.POST or None, request.FILES or None, instance=product)
    option_formset = ProductOptionStaffFormSet(request.POST or None, instance=product, prefix='options')
    option_definitions = build_product_option_definitions(product=product, data=request.POST if request.method == 'POST' else None)
    variant_formset = ProductVariantStaffFormSet(
        request.POST or None,
        instance=product,
        prefix='variants',
        option_definitions=option_definitions,
    )

    if request.method == 'POST' and product_form.is_valid() and option_formset.is_valid() and variant_formset.is_valid():
        with transaction.atomic():
            saved_product = product_form.save()
            product_form.save_existing_media_state(saved_product, request.POST)
            product_form.save_media_files(saved_product)
            option_formset.instance = saved_product
            option_formset.save()
            variant_formset.instance = saved_product
            variant_formset.save()
        messages.success(request, f'{saved_product.name} saved successfully.')
        if request.POST.get('save_action') == 'continue':
            return redirect('staff:product_edit', pk=saved_product.pk), None, None, None
        return redirect('staff:products'), None, None, None

    return None, product_form, option_formset, variant_formset


def _build_product_editor_context(product, product_form, option_formset, variant_formset):
    variants = list(product.variants.all()) if product and product.pk else []
    active_variants = [variant for variant in variants if variant.is_active]
    return {
        'product': product,
        'product_media_items': product.gallery_media if product and product.pk else [],
        'product_form': product_form,
        'option_formset': option_formset,
        'variant_formset': variant_formset,
        'product_page_mode': 'edit' if product and product.pk else 'create',
        'product_editor_stats': {
            'option_count': product.options.count() if product and product.pk else 0,
            'variant_count': len(variants),
            'active_variant_count': len(active_variants),
            'starting_price': product.starting_price if product else None,
        },
        'variant_option_labels': variant_formset.option_labels,
    }


@staff_required
def product_create(request):
    redirect_response, product_form, option_formset, variant_formset = _save_product_editor(request)
    if redirect_response:
        return redirect_response

    context = _build_product_editor_context(None, product_form, option_formset, variant_formset)
    return render(request, 'staff/product_form.html', context)


@staff_required
def product_edit(request, pk):
    product = get_object_or_404(
        Product.objects.select_related('category').prefetch_related('media_assets', 'variants', 'options__option_values'),
        pk=pk,
    )
    redirect_response, product_form, option_formset, variant_formset = _save_product_editor(request, product=product)
    if redirect_response:
        return redirect_response

    context = _build_product_editor_context(product, product_form, option_formset, variant_formset)
    return render(request, 'staff/product_form.html', context)