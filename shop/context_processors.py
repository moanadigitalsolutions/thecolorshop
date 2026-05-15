from .cart import Cart


def cart_summary(request):
    if not hasattr(request, 'session'):
        return {'cart_count': 0}
    return {'cart_count': len(Cart(request))}
