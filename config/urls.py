"""Project URL configuration."""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.contrib.sitemaps.views import sitemap
from django.urls import include, path, reverse_lazy
from django_ratelimit.decorators import ratelimit

from shop.forms import PasswordResetRequestForm, PasswordResetSetPasswordForm
from shop.sitemaps import sitemaps
from shop.views import CustomerLoginView, robots_txt

urlpatterns = [
    path('', include('shop.urls')),
    path('staff/', include('shop.staff_urls')),
    path('accounts/login/', CustomerLoginView.as_view(), name='login'),
    path(
        'accounts/password_reset/',
        ratelimit(key='user_or_ip', rate='5/m', method='POST', block=True)(
            auth_views.PasswordResetView.as_view(
                form_class=PasswordResetRequestForm,
                template_name='registration/password_reset_form.html',
                success_url=reverse_lazy('password_reset_done'),
            )
        ),
        name='password_reset',
    ),
    path(
        'accounts/password_reset/done/',
        auth_views.PasswordResetDoneView.as_view(template_name='registration/password_reset_done.html'),
        name='password_reset_done',
    ),
    path(
        'accounts/reset/<uidb64>/<token>/',
        auth_views.PasswordResetConfirmView.as_view(
            form_class=PasswordResetSetPasswordForm,
            template_name='registration/password_reset_confirm.html',
            success_url=reverse_lazy('password_reset_complete'),
        ),
        name='password_reset_confirm',
    ),
    path(
        'accounts/reset/done/',
        auth_views.PasswordResetCompleteView.as_view(template_name='registration/password_reset_complete.html'),
        name='password_reset_complete',
    ),
    path('accounts/', include('django.contrib.auth.urls')),
    path('admin/', admin.site.urls),
    path('robots.txt', robots_txt, name='robots_txt'),
    path('sitemap.xml', sitemap, {'sitemaps': sitemaps}, name='sitemap'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
