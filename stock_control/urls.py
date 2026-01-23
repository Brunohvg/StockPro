"""
StockPro URL Configuration
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path(settings.ADMIN_URL, admin.site.urls),

    # Custom Authentication (V11 - Smart Login)
    path('accounts/', include('apps.accounts.urls')),

    # Django Auth (password reset, logout, etc.)
    path('accounts/', include('django.contrib.auth.urls')),

    # Public pages (landing, signup)
    path('', include('apps.tenants.urls')),

    # App routes (authenticated)
    path('app/', include('apps.reports.urls')),
    path('products/', include('apps.products.urls')),
    path('inventory/', include('apps.inventory.urls')),
    path('partners/', include('apps.partners.urls')),
    path('settings/', include('apps.core.urls')),

    # Connect Protocol (Plan B - API)
    path('api/v1/', include('stock_control.api_urls')),
]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
