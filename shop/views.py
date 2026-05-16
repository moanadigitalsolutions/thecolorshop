from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.paginator import Paginator
from django.core.exceptions import ValidationError
from django.db.models import Prefetch, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django_ratelimit.decorators import ratelimit

from .cart import Cart
from .forms import CheckoutForm, CustomerAuthenticationForm, ProductFilterForm, ResendVerificationForm, SignUpForm
from .models import Category, EmailLog, Order, Product, ProductVariant
from .services import create_order_from_cart, send_email_verification, send_order_confirmation
from .tokens import email_verification_token_generator


PRODUCT_LIST_PAGE_SIZE = 12


class CustomerLoginView(LoginView):
    authentication_form = CustomerAuthenticationForm
    redirect_authenticated_user = True
    template_name = 'registration/login.html'

    def get_success_url(self):
        return self.get_redirect_url() or reverse_lazy('product_list')


def build_email_verification_url(request, user):
    uidb64 = urlsafe_base64_encode(force_bytes(user.pk))
    token = email_verification_token_generator.make_token(user)
    return request.build_absolute_uri(reverse('verify_email', kwargs={'uidb64': uidb64, 'token': token}))


def build_page_query(request):
    params = request.GET.copy()
    params.pop('page', None)
    return params.urlencode()


def robots_txt(request):
    content = '\n'.join(
        [
            'User-agent: *',
            'Allow: /',
            'Disallow: /admin/',
            'Disallow: /accounts/',
            'Disallow: /staff/',
            'Disallow: /cart/',
            'Disallow: /checkout/',
            'Disallow: /orders/',
            f'Sitemap: {request.build_absolute_uri(reverse("sitemap"))}',
        ]
    )
    return HttpResponse(content, content_type='text/plain')


def ratelimit_exceeded(request, exception):
    return render(request, 'rate_limited.html', status=429)


def get_product_search_results(query='', category_slug=''):
    products = Product.objects.filter(is_active=True).select_related('category').prefetch_related(
        'media_assets',
        'pickup_locations',
        Prefetch('variants', queryset=ProductVariant.objects.filter(is_active=True).order_by('price'))
    )
    selected_category = None

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
        selected_category = get_object_or_404(Category, slug=category_slug, is_active=True)
        products = products.filter(category=selected_category)

    return products, selected_category


def serialize_product_search_results(products):
    suggestions = []
    product_cards = []

    for product in products:
        image_url = product.primary_image_url
        product_cards.append(
            {
                'name': product.name,
                'slug': product.slug,
                'url': product.get_absolute_url(),
                'description': (product.description or 'Available for pickup from The Color Shop.')[:118],
                'category_name': product.category.name,
                'starting_price': str(product.starting_price) if product.starting_price is not None else '',
                'image_url': image_url,
                'has_stock': product.starting_price is not None,
            }
        )

        suggestions.append(
            {
                'label': product.name,
                'meta': product.category.name,
                'url': product.get_absolute_url(),
                'type': 'product',
            }
        )

        for variant in product.active_variants[:2]:
            suggestions.append(
                {
                    'label': f'{product.name} - {variant.display_name}',
                    'meta': variant.sku,
                    'url': product.get_absolute_url(),
                    'type': 'variant',
                }
            )

    return {'suggestions': suggestions[:8], 'products': product_cards}


def product_list(request):
    form = ProductFilterForm(request.GET)
    categories = Category.objects.filter(is_active=True)
    products, selected_category = get_product_search_results()

    if form.is_valid():
        query = form.cleaned_data.get('q')
        category_slug = form.cleaned_data.get('category')
        products, selected_category = get_product_search_results(query=query, category_slug=category_slug)

    paginator = Paginator(products, PRODUCT_LIST_PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(
        request,
        'shop/product_list.html',
        {
            'products': page_obj.object_list,
            'categories': categories,
            'filter_form': form,
            'is_paginated': page_obj.has_other_pages(),
            'page_obj': page_obj,
            'page_query': build_page_query(request),
            'product_count': paginator.count,
            'selected_category': selected_category,
        },
    )


def product_search_api(request):
    form = ProductFilterForm(request.GET)
    if not form.is_valid():
        return JsonResponse({'suggestions': [], 'products': [], 'count': 0})

    query = form.cleaned_data.get('q', '').strip()
    category_slug = form.cleaned_data.get('category', '').strip()

    if not query and not category_slug:
        return JsonResponse({'suggestions': [], 'products': [], 'count': 0})

    products, _selected_category = get_product_search_results(query=query, category_slug=category_slug)
    payload = serialize_product_search_results(products[:12])
    payload['count'] = products.count()
    return JsonResponse(payload)


def product_detail(request, slug):
    product = get_object_or_404(
        Product.objects.select_related('category').prefetch_related('media_assets', 'pickup_locations', 'variants__inventory_levels__location', 'variants'),
        slug=slug,
        is_active=True,
    )
    variants = product.variants.filter(is_active=True)
    return render(
        request,
        'shop/product_detail.html',
        {'product': product, 'variants': variants, 'gallery_media': product.gallery_media},
    )


def cart_detail(request):
    cart = Cart(request)
    return render(request, 'shop/cart_detail.html', {'cart': cart})


def cart_add(request):
    if request.method != 'POST':
        return redirect('product_list')
    variant = get_object_or_404(ProductVariant.objects.select_related('product'), id=request.POST.get('variant_id'), is_active=True)
    quantity = request.POST.get('quantity', 1)
    cart = Cart(request)
    try:
        cart.add(variant, quantity=quantity)
        messages.success(request, f'Added {variant.product.name} to your cart.')
    except (ValueError, TypeError):
        messages.error(request, f'Not enough stock available for {variant.product.name}.')
    return redirect(request.POST.get('next') or variant.product.get_absolute_url())


def cart_update(request):
    if request.method != 'POST':
        return redirect('cart_detail')
    variant = get_object_or_404(ProductVariant, id=request.POST.get('variant_id'))
    cart = Cart(request)
    quantity = int(request.POST.get('quantity', 0))
    if quantity <= 0:
        cart.remove(variant)
        messages.info(request, f'Removed {variant.product.name} from your cart.')
    else:
        try:
            cart.add(variant, quantity=quantity, override_quantity=True)
            messages.success(request, 'Cart updated.')
        except ValueError:
            messages.error(request, f'Only {variant.stock_quantity} available for {variant.sku}.')
    return redirect('cart_detail')


@login_required
def checkout(request):
    cart = Cart(request)
    if cart.is_empty():
        messages.info(request, 'Your cart is empty.')
        return redirect('product_list')

    profile = getattr(request.user, 'customer_profile', None)
    initial = {
        'customer_name': request.user.get_full_name() or request.user.username,
        'customer_email': request.user.email,
        'customer_phone': getattr(profile, 'phone_number', ''),
        'pickup_name': getattr(profile, 'default_pickup_name', '') or request.user.get_full_name() or request.user.username,
        'pickup_phone': getattr(profile, 'phone_number', ''),
    }

    if request.method == 'POST':
        form = CheckoutForm(request.POST)
        if form.is_valid():
            try:
                order = create_order_from_cart(request.user, cart, form.cleaned_data)
            except (ValidationError, ProductVariant.DoesNotExist) as exc:
                messages.error(request, exc.messages[0] if hasattr(exc, 'messages') else str(exc))
            else:
                send_order_confirmation(order)
                cart.clear()
                messages.success(request, f'Order {order.order_number} placed for pickup.')
                return redirect(reverse('order_detail', kwargs={'order_number': order.order_number}))
    else:
        form = CheckoutForm(initial=initial)

    return render(request, 'shop/checkout.html', {'cart': cart, 'form': form})


@login_required
def order_history(request):
    orders = Order.objects.filter(user=request.user).prefetch_related('items')
    return render(request, 'shop/order_history.html', {'orders': orders})


@login_required
def order_detail(request, order_number):
    order = get_object_or_404(Order.objects.prefetch_related('items'), order_number=order_number, user=request.user)
    return render(request, 'shop/order_detail.html', {'order': order})


@ratelimit(key='user_or_ip', rate='5/m', method='POST', block=True)
def signup(request):
    if request.method == 'POST':
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save()
            verification_url = build_email_verification_url(request, user)
            email_log = send_email_verification(user, verification_url)
            if email_log.status == EmailLog.STATUS_SENT:
                messages.success(request, 'Your account has been created. Check your inbox to verify your email address.')
            else:
                messages.warning(request, 'Your account has been created, but we could not confirm email delivery yet. You can resend the verification link from the next page.')
            query = urlencode({'email': user.email})
            return redirect(f"{reverse('verification_pending')}?{query}")
    else:
        form = SignUpForm()
    return render(request, 'registration/signup.html', {'form': form})


def verification_pending(request):
    return render(request, 'registration/verification_pending.html', {'email': request.GET.get('email', '').strip()})


def verification_success(request):
    return render(request, 'registration/verification_success.html')


def verify_email(request, uidb64, token):
    user_model = get_user_model()
    try:
        user_id = force_str(urlsafe_base64_decode(uidb64))
        user = user_model.objects.get(pk=user_id)
    except (TypeError, ValueError, OverflowError, user_model.DoesNotExist):
        user = None

    if not user:
        return render(request, 'registration/verification_invalid.html', status=400)

    profile = getattr(user, 'customer_profile', None)
    if not profile:
        return render(request, 'registration/verification_invalid.html', status=400)

    if profile.is_email_verified:
        messages.info(request, 'Your email address is already verified. Please log in.')
        return redirect('login')

    if not email_verification_token_generator.check_token(user, token):
        return render(request, 'registration/verification_invalid.html', status=400)

    profile.mark_email_verified()
    messages.success(request, 'Your email address has been verified. You can now log in.')
    return redirect('verification_success')


@ratelimit(key='user_or_ip', rate='5/m', method='POST', block=True)
def resend_verification(request):
    initial = {'email': request.GET.get('email', '').strip()}
    form = ResendVerificationForm(request.POST or None, initial=initial if request.method != 'POST' else None)

    if request.method == 'POST' and form.is_valid():
        user_model = get_user_model()
        email = form.cleaned_data['email'].strip().lower()
        user = user_model.objects.filter(email__iexact=email).select_related('customer_profile').first()

        if not user or not hasattr(user, 'customer_profile'):
            messages.success(request, 'If an unverified account exists for this email address, a new verification link has been sent.')
            return redirect('resend_verification')

        profile = user.customer_profile
        if profile.is_email_verified:
            messages.info(request, 'This email address is already verified. Please log in.')
            return redirect('login')

        cooldown_seconds = settings.EMAIL_VERIFICATION_RESEND_COOLDOWN_SECONDS
        if profile.email_verification_sent_at:
            elapsed_seconds = int((timezone.now() - profile.email_verification_sent_at).total_seconds())
            if elapsed_seconds < cooldown_seconds:
                remaining_seconds = cooldown_seconds - elapsed_seconds
                remaining_minutes = max(1, (remaining_seconds + 59) // 60)
                messages.info(request, f'Please wait about {remaining_minutes} minute(s) before requesting another verification email.')
                return render(request, 'registration/resend_verification.html', {'form': form})

        verification_url = build_email_verification_url(request, user)
        email_log = send_email_verification(user, verification_url)
        if email_log.status == EmailLog.STATUS_SENT:
            messages.success(request, 'A new verification link has been sent to your email address.')
        else:
            messages.warning(request, 'We attempted to resend the verification email, but delivery could not be confirmed yet.')
        query = urlencode({'email': user.email})
        return redirect(f"{reverse('verification_pending')}?{query}")

    return render(request, 'registration/resend_verification.html', {'form': form})
