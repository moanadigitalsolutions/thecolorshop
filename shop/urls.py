from django.urls import path

from . import views

urlpatterns = [
    path('', views.product_list, name='product_list'),
    path('products/search/', views.product_search_api, name='product_search_api'),
    path('products/<slug:slug>/', views.product_detail, name='product_detail'),
    path('cart/', views.cart_detail, name='cart_detail'),
    path('cart/add/', views.cart_add, name='cart_add'),
    path('cart/update/', views.cart_update, name='cart_update'),
    path('checkout/', views.checkout, name='checkout'),
    path('orders/', views.order_history, name='order_history'),
    path('orders/<str:order_number>/', views.order_detail, name='order_detail'),
    path('signup/', views.signup, name='signup'),
]
