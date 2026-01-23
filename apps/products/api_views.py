from rest_framework import status
from rest_framework.response import Response

from apps.core.api.views import BaseTenantViewSet

from .models import Product, ProductVariant
from .serializers import ProductSerializer, ProductVariantSerializer


class ProductViewSet(BaseTenantViewSet):
    """
    API endpoint that allows products to be viewed or edited.
    Automatically identifies the tenant and filters results.
    """
    queryset = Product.objects.all().select_related('category', 'brand').prefetch_related('variants')
    serializer_class = ProductSerializer

    def create(self, request, *args, **kwargs):
        """
        Overridden to support Advanced Staging (Plan C).
        If 'staged=true' is passed, the item is sent to the Curatorship Hub (ImportItem)
        instead of being created directly.
        """
        staged = request.query_params.get('staged', 'false').lower() == 'true'
        tenant = self.get_tenant() # Ensure tenant resolution

        if staged:
            from apps.inventory.models import ImportItem
            data = request.data

            # Create a pending item in the staging area
            item = ImportItem.objects.create(
                tenant=tenant,
                source='API',
                supplier_sku=data.get('sku', 'N/A'),
                description=data.get('name', 'N/A'),
                ean=data.get('barcode'),
                quantity=0, # Base quantity for creation staging
                unit_cost=data.get('avg_unit_cost', 0),
                raw_data=data,
                status='PENDING',
                ai_confidence=0.5, # API creates need review
                ai_logic_summary="Item enviado via API em modo de rascunho/staging."
            )

            return Response({
                "message": "Item enviado para curadoria com sucesso.",
                "staging_id": item.pk,
                "status": "staged"
            }, status=status.HTTP_202_ACCEPTED)

        # Normale direct creation with Audit
        response = super().create(request, *args, **kwargs)

        # Log Visual Audit for creation
        from apps.core.models import VisualAuditLog
        VisualAuditLog.objects.create(
            tenant=tenant,
            user=request.user,
            entity_type='PRODUCT',
            entity_id=str(response.data.get('id')),
            action='CREATE',
            source='API',
            after_state=response.data
        )

        return response

class ProductVariantViewSet(BaseTenantViewSet):
    """
    API endpoint that allows variants to be viewed or edited.
    """
    queryset = ProductVariant.objects.all().select_related('product')
    serializer_class = ProductVariantSerializer
