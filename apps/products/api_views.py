from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from apps.core.api.tenant import HasActiveTenant, resolve_api_tenant
from apps.core.api.views import BaseTenantViewSet

from .models import Product, ProductVariant
from .serializers import ProductSerializer, ProductVariantSerializer, StagingItemSerializer, StagingSubmissionSerializer


class ArchiveOnDeleteMixin:
    """
    GET da lista oculta arquivados (use ?include_archived=1 para vê-los).
    DELETE nunca apaga histórico: sem movimentações exclui, com movimentações arquiva.
    Apenas OWNER/ADMIN podem remover.
    """

    def get_queryset(self):
        qs = super().get_queryset()
        if self.action == 'list' and self.request.query_params.get('include_archived') not in ('1', 'true'):
            qs = qs.filter(is_active=True)
        return qs

    def destroy(self, request, *args, **kwargs):
        from .services import ProductArchiveService
        membership = getattr(request, 'membership', None)
        if not membership or membership.role not in ('OWNER', 'ADMIN'):
            return Response({'error': 'Apenas administradores podem remover produtos.'},
                            status=status.HTTP_403_FORBIDDEN)
        obj = self.get_object()
        try:
            if isinstance(obj, Product):
                result = ProductArchiveService.remove_product(obj, request.user)
            else:
                result = ProductArchiveService.remove_variant(obj, request.user)
        except ValueError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        if result == 'deleted':
            return Response(status=status.HTTP_204_NO_CONTENT)
        return Response({'status': 'archived',
                         'detail': 'Item com histórico foi arquivado; movimentações preservadas.'})


class ProductViewSet(ArchiveOnDeleteMixin, BaseTenantViewSet):
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

        if not staged and tenant.products_limit_reached:
            return Response(
                {"error": f"Limite de {tenant.plan.max_products} produtos do plano atingido."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if staged:
            from apps.inventory.models import ImportItem
            submission = StagingSubmissionSerializer(data=request.data)
            submission.is_valid(raise_exception=True)
            data = submission.validated_data

            # Create a pending item in the staging area
            item = ImportItem.objects.create(
                tenant=tenant,
                source='API',
                supplier_sku=data.get('sku', 'N/A'),
                description=data.get('name', 'N/A'),
                ean=data.get('barcode'),
                quantity=0, # Base quantity for creation staging
                unit_cost=data.get('avg_unit_cost', 0),
                raw_data=dict(request.data),
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

class ProductVariantViewSet(ArchiveOnDeleteMixin, BaseTenantViewSet):
    """
    API endpoint that allows variants to be viewed or edited.
    """
    queryset = ProductVariant.objects.all().select_related('product')
    serializer_class = ProductVariantSerializer


class IsTenantAdmin(HasActiveTenant):
    """Exige OWNER/ADMIN da empresa resolvida."""
    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        membership = getattr(request, 'membership', None)
        if not membership or membership.role not in ('OWNER', 'ADMIN'):
            self.message = 'Apenas administradores podem revisar itens em staging.'
            return False
        return True


class StagingItemViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """
    Itens enviados com POST /api/v1/products/?staged=true aguardando revisão.

    GET  /api/v1/staging/                 — lista (filtro ?status=PENDING por padrão)
    POST /api/v1/staging/<id>/approve/    — cria o produto (e a entrada, se houver quantidade)
    POST /api/v1/staging/<id>/reject/     — rejeita
    """
    serializer_class = StagingItemSerializer
    permission_classes = [IsAuthenticated, IsTenantAdmin]

    def get_queryset(self):
        from apps.inventory.models import ImportItem
        tenant = getattr(self.request, 'tenant', None) or resolve_api_tenant(self.request)
        qs = ImportItem.objects.filter(tenant=tenant, source='API').order_by('-created_at')
        item_status = self.request.query_params.get('status', 'PENDING')
        if self.action == 'list' and item_status != 'ALL':
            qs = qs.filter(status=item_status)
        return qs

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        from apps.inventory.services.staging import StagingError, approve_item
        try:
            product = approve_item(self.get_object(), request.user)
        except StagingError as e:
            return Response({'error': str(e)}, status=status.HTTP_409_CONFLICT)
        return Response({'status': 'DONE', 'product_id': product.pk, 'sku': product.sku})

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        from apps.inventory.services.staging import StagingError, reject_item
        try:
            reject_item(self.get_object())
        except StagingError as e:
            return Response({'error': str(e)}, status=status.HTTP_409_CONFLICT)
        return Response({'status': 'REJECTED'})


class ThrottledTokenObtainPairView(TokenObtainPairView):
    throttle_scope = 'auth'

    def finalize_response(self, request, response, *args, **kwargs):
        # O django-axes marca o bloqueio no Request do DRF; o AxesMiddleware só
        # enxerga o HttpRequest original. Repassa a marca para ele responder 429.
        if getattr(request, 'axes_locked_out', False):
            request._request.axes_locked_out = True
            request._request.axes_credentials = getattr(request, 'axes_credentials', None)
        return super().finalize_response(request, response, *args, **kwargs)


class ThrottledTokenRefreshView(TokenRefreshView):
    throttle_scope = 'auth'
