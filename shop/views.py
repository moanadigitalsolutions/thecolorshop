from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import Prefetch, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .cart import Cart
from .forms import CheckoutForm, ProductFilterForm, SignUpForm
from .models import Category, Order, Product, ProductVariant
from .services import create_order_from_cart, send_order_confirmation


def get_product_search_results(query='', category_slug=''):
    products = Product.objects.filter(is_active=True).select_related('category').prefetch_related(
        Prefetch('variants', queryset=ProductVariant.objects.filter(is_active=True).order_by('price'))
    )
    selected_category = None

    if query:
        products = products.filter(
            Q(name__icontains=query)
            | Q(description__icontains=query)
            | Q(variants__sku__icontains=query)
            | Q(variants__color__icontains=query)
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
        image_url = product.image.url if product.image else ''
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

    return render(
        request,
        'shop/product_list.html',
        {'products': products, 'categories': categories, 'filter_form': form, 'selected_category': selected_category},
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
        Product.objects.select_related('category').prefetch_related('variants'),
        slug=slug,
        is_active=True,
    )
    variants = product.variants.filter(is_active=True)
    return render(request, 'shop/product_detail.html', {'product': product, 'variants': variants})


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


def signup(request):
    if request.method == 'POST':
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, 'Your account is ready.')
            return redirect('product_list')
    else:
        form = SignUpForm()
    return render(request, 'registration/signup.html', {'form': form})
