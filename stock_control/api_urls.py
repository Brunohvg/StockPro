from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)

from apps.inventory.api_views import OrderConsumptionView, StockEntryView
from apps.products.api_views import ProductVariantViewSet, ProductViewSet
from apps.inventory.api_views import ProductSearchView

router = DefaultRouter()
router.register(r'products', ProductViewSet, basename='api-product')
router.register(r'variants', ProductVariantViewSet, basename='api-variant')

urlpatterns = [
    # Auth
    path('auth/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),

    # Mobile: busca de produtos por nome/SKU/código de barras
    path('products/search/', ProductSearchView.as_view(), name='api-product-search'),

    # Mobile: saída de estoque (venda / baixa)
    path('inventory/consume/', OrderConsumptionView.as_view(), name='api-order-consume'),

    # Mobile: entrada de estoque (recebimento / compra)
    path('inventory/entry/', StockEntryView.as_view(), name='api-stock-entry'),

    # Generic Router
    path('', include(router.urls)),
]
