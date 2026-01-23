from django.db import transaction
from rest_framework import status, views
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.services import StockService


class OrderConsumptionView(views.APIView):
    """
    API endpoint to consume stock from an external order (Plan C).
    POST /api/v1/inventory/consume/
    """
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        data = request.data
        tenant = getattr(request, 'tenant', None)

        # Guard for tenant context (Fallback if middleware skipped)
        if not tenant:
            from apps.accounts.models import TenantMembership
            membership = TenantMembership.objects.filter(user=request.user, is_active=True).first()
            if membership:
                tenant = membership.tenant

        items = data.get('items', [])
        platform = data.get('platform', 'API')
        external_order_id = data.get('external_order_id')

        if not external_order_id:
            return Response({"error": "external_order_id is required"}, status=status.HTTP_400_BAD_REQUEST)

        results = []
        errors = []

        for item in items:
            sku = item.get('sku')
            qty = item.get('quantity')

            if not sku or not qty:
                errors.append(f"Missing SKU or quantity for item: {item}")
                continue

            try:
                movement = StockService.create_movement(
                    tenant=tenant,
                    user=request.user,
                    movement_type='OUT',
                    quantity=qty,
                    product_sku=sku,
                    reason=f"Order {platform} #{external_order_id}",
                    source=platform,
                    external_order_id=external_order_id
                )
                results.append({
                    "sku": sku,
                    "quantity": qty,
                    "status": "success",
                    "movement_id": str(movement.id)
                })
            except Exception as e:
                errors.append({
                    "sku": sku,
                    "error": str(e)
                })

        return Response({
            "order_id": external_order_id,
            "processed_items": results,
            "errors": errors
        }, status=status.HTTP_207_MULTI_STATUS if errors else status.HTTP_200_OK)
