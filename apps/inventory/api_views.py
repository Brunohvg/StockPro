"""
Inventory API Views - Mobile-ready endpoints for stock operations.

Endpoints:
  POST /api/v1/inventory/consume/  — Saída de estoque (venda, baixa)
  POST /api/v1/inventory/entry/    — Entrada de estoque (recebimento, compra)
  GET  /api/v1/products/search/    — Busca por nome, SKU ou código de barras

Autenticação: JWT Bearer Token
  POST /api/v1/auth/token/         — Obter token (email + senha)
  POST /api/v1/auth/token/refresh/ — Renovar token
"""
from django.db import transaction
from django.db.models import Q
from rest_framework import status, views
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.services import StockService
from apps.products.models import ProductVariant


def _resolve_tenant(request):
    """Resolve tenant do request (middleware ou fallback por membership)."""
    tenant = getattr(request, 'tenant', None)
    if not tenant and request.user.is_authenticated:
        from apps.accounts.models import TenantMembership
        membership = TenantMembership.objects.filter(
            user=request.user, is_active=True
        ).first()
        if membership:
            tenant = membership.tenant
    return tenant


class ProductSearchView(views.APIView):
    """
    Busca produtos para o app mobile.
    Suporta busca por nome, SKU ou código de barras.

    GET /api/v1/products/search/?q=<termo>

    Retorna até 20 variantes com estoque atual.
    Requer ao menos 2 caracteres.

    Resposta:
    {
        "results": [
            {
                "variant_id": 1,
                "product_id": 1,
                "sku": "SKU-001",
                "barcode": "7891234567890",
                "display_name": "Produto X - Tamanho G",
                "current_stock": 15.0,
                "minimum_stock": 5.0,
                "unit": "UN",
                "avg_unit_cost": 29.90,
                "product_type": "SIMPLE"
            }
        ]
    }
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        query = request.GET.get('q', '').strip()
        tenant = _resolve_tenant(request)

        if not tenant:
            return Response({"error": "Tenant não identificado."}, status=status.HTTP_403_FORBIDDEN)

        if len(query) < 2:
            return Response({"results": [], "hint": "Digite ao menos 2 caracteres."})

        variants = ProductVariant.objects.filter(
            Q(product__name__icontains=query) |
            Q(name__icontains=query) |
            Q(sku__icontains=query) |
            Q(barcode=query),
            tenant=tenant,
            is_active=True
        ).select_related('product', 'product__category', 'product__brand').order_by(
            'product__name', 'name'
        )[:20]

        results = []
        for v in variants:
            results.append({
                "variant_id": v.id,
                "product_id": v.product_id,
                "sku": v.sku,
                "barcode": v.barcode or "",
                "display_name": v.display_name if hasattr(v, 'display_name') else v.name,
                "current_stock": float(v.current_stock),
                "minimum_stock": float(v.minimum_stock) if v.minimum_stock else 0,
                "unit": v.product.uom if hasattr(v.product, 'uom') else "UN",
                "avg_unit_cost": float(v.avg_unit_cost) if v.avg_unit_cost else 0,
                "product_type": v.product.product_type,
                "low_stock": v.current_stock <= (v.minimum_stock or 0),
            })

        return Response({"results": results, "count": len(results)})


class OrderConsumptionView(views.APIView):
    """
    Saída de estoque — baixa de produtos (venda, consumo, expedição).

    POST /api/v1/inventory/consume/

    Body:
    {
        "external_order_id": "PEDIDO-001",
        "platform": "APP_MOBILE",
        "items": [
            {"sku": "SKU-001", "quantity": 2},
            {"sku": "SKU-002", "quantity": 1}
        ]
    }

    Resposta 200 (sem erros):
    {
        "order_id": "PEDIDO-001",
        "processed_items": [{"sku": "SKU-001", "quantity": 2, "status": "success", "movement_id": "uuid"}],
        "errors": []
    }

    Resposta 207 (parcial — alguns itens com erro):
    {
        "order_id": "PEDIDO-001",
        "processed_items": [...],
        "errors": [{"sku": "SKU-999", "error": "Produto não encontrado."}]
    }
    """
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        tenant = _resolve_tenant(request)
        if not tenant:
            return Response({"error": "Tenant não identificado."}, status=status.HTTP_403_FORBIDDEN)

        data = request.data
        items = data.get('items', [])
        platform = data.get('platform', 'APP_MOBILE')
        external_order_id = data.get('external_order_id')

        if not external_order_id:
            return Response(
                {"error": "external_order_id é obrigatório."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not items:
            return Response(
                {"error": "Lista de itens está vazia."},
                status=status.HTTP_400_BAD_REQUEST
            )

        results = []
        errors = []

        for item in items:
            sku = item.get('sku')
            qty = item.get('quantity')

            if not sku or not qty:
                errors.append({"sku": sku or "?", "error": "SKU e quantity são obrigatórios."})
                continue

            try:
                movement = StockService.create_movement(
                    tenant=tenant,
                    user=request.user,
                    movement_type='OUT',
                    quantity=qty,
                    product_sku=sku,
                    reason=f"Saída via App — {platform} #{external_order_id}",
                    source=platform,
                    external_order_id=external_order_id,
                )
                results.append({
                    "sku": sku,
                    "quantity": float(qty),
                    "status": "success",
                    "movement_id": str(movement.id),
                    "balance_after": float(movement.balance_after),
                })
            except Exception as e:
                errors.append({"sku": sku, "error": str(e)})

        http_status = status.HTTP_207_MULTI_STATUS if errors else status.HTTP_200_OK
        return Response({
            "order_id": external_order_id,
            "processed_items": results,
            "errors": errors,
        }, status=http_status)


class StockEntryView(views.APIView):
    """
    Entrada de estoque — recebimento de produtos (compra, devolução, ajuste).

    POST /api/v1/inventory/entry/

    Body:
    {
        "reference": "NF-001",
        "items": [
            {"sku": "SKU-001", "quantity": 10, "unit_cost": 29.90},
            {"sku": "SKU-002", "quantity": 5}
        ]
    }

    - unit_cost: opcional. Se informado, atualiza o custo médio ponderado.
    - reference: identificador da nota, pedido de compra ou motivo.

    Resposta 200:
    {
        "reference": "NF-001",
        "processed_items": [
            {"sku": "SKU-001", "quantity": 10, "status": "success",
             "movement_id": "uuid", "balance_after": 25.0}
        ],
        "errors": []
    }
    """
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        tenant = _resolve_tenant(request)
        if not tenant:
            return Response({"error": "Tenant não identificado."}, status=status.HTTP_403_FORBIDDEN)

        data = request.data
        items = data.get('items', [])
        reference = data.get('reference', 'Entrada via App')

        if not items:
            return Response(
                {"error": "Lista de itens está vazia."},
                status=status.HTTP_400_BAD_REQUEST
            )

        results = []
        errors = []

        for item in items:
            sku = item.get('sku')
            qty = item.get('quantity')
            unit_cost = item.get('unit_cost')

            if not sku or not qty:
                errors.append({"sku": sku or "?", "error": "SKU e quantity são obrigatórios."})
                continue

            try:
                movement = StockService.create_movement(
                    tenant=tenant,
                    user=request.user,
                    movement_type='IN',
                    quantity=qty,
                    product_sku=sku,
                    unit_cost=unit_cost,
                    reason=f"Entrada via App — Ref: {reference}",
                    source='APP_MOBILE',
                )
                results.append({
                    "sku": sku,
                    "quantity": float(qty),
                    "unit_cost": float(unit_cost) if unit_cost else None,
                    "status": "success",
                    "movement_id": str(movement.id),
                    "balance_after": float(movement.balance_after),
                })
            except Exception as e:
                errors.append({"sku": sku, "error": str(e)})

        http_status = status.HTTP_207_MULTI_STATUS if errors else status.HTTP_200_OK
        return Response({
            "reference": reference,
            "processed_items": results,
            "errors": errors,
        }, status=http_status)
