from django.urls import path

from . import staff_views

app_name = 'staff'

urlpatterns = [
    path('login/', staff_views.StaffLoginView.as_view(), name='login'),
    path('', staff_views.dashboard, name='dashboard'),
    path('customers/', staff_views.customer_catalog, name='customers'),
    path('email-logs/', staff_views.email_log_catalog, name='email_logs'),
    path('locations/', staff_views.location_catalog, name='locations'),
    path('locations/<int:pk>/edit/', staff_views.location_edit, name='location_edit'),
    path('orders/', staff_views.order_catalog, name='orders'),
    path('orders/<str:order_number>/', staff_views.order_detail, name='order_detail'),
    path('products/', staff_views.product_catalog, name='products'),
    path('products/new/', staff_views.product_create, name='product_create'),
    path('products/<int:pk>/edit/', staff_views.product_edit, name='product_edit'),
]