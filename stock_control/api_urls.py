from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)

from apps.inventory.api_views import OrderConsumptionView
from apps.products.api_views import ProductVariantViewSet, ProductViewSet

router = DefaultRouter()
router.register(r'products', ProductViewSet, basename='api-product')
router.register(r'variants', ProductVariantViewSet, basename='api-variant')

urlpatterns = [
    # Auth
    path('auth/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),

    # Inventory & Consumption (Plan C)
    path('inventory/consume/', OrderConsumptionView.as_view(), name='api-order-consume'),

    # Generic Router
    path('', include(router.urls)),
]
