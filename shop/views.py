from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .cart import Cart
from .forms import CheckoutForm, ProductFilterForm, SignUpForm
from .models import Category, Order, Product, ProductVariant
from .services import create_order_from_cart, send_order_confirmation


def product_list(request):
    form = ProductFilterForm(request.GET)
    products = Product.objects.filter(is_active=True).select_related('category').prefetch_related(
        Prefetch('variants', queryset=ProductVariant.objects.filter(is_active=True).order_by('price'))
    )
    categories = Category.objects.filter(is_active=True)
    selected_category = None

    if form.is_valid():
        query = form.cleaned_data.get('q')
        category_slug = form.cleaned_data.get('category')
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

    return render(
        request,
        'shop/product_list.html',
        {'products': products, 'categories': categories, 'filter_form': form, 'selected_category': selected_category},
    )


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
