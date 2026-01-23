from rest_framework import serializers, viewsets
from rest_framework.permissions import IsAuthenticated


class TenantSerializerMixin(metaclass=serializers.SerializerMetaclass):
    """
    Mixin to automatically handle tenant assignment during creation.
    """
    def create(self, validated_data):
        if 'tenant' not in validated_data:
            # Try to get tenant from request (set by middleware or view)
            tenant = getattr(self.context['request'], 'tenant', None)
            if not tenant:
                # Fallback for JWT requests where middleware might skip tenant detection
                from apps.accounts.models import TenantMembership
                membership = TenantMembership.objects.filter(
                    user=self.context['request'].user,
                    is_active=True
                ).first()
                if membership:
                    tenant = membership.tenant

            if tenant:
                validated_data['tenant'] = tenant
        return super().create(validated_data)

class BaseTenantViewSet(viewsets.ModelViewSet):
    """
    Base ViewSet that automatically filters querysets by the request's tenant.
    All API views for multi-tenant models should inherit from this.
    """
    permission_classes = [IsAuthenticated]

    def get_tenant(self):
        """Ensures tenant is resolved and returns it."""
        tenant = getattr(self.request, 'tenant', None)
        if not tenant and self.request.user.is_authenticated:
            from apps.accounts.models import TenantMembership
            membership = TenantMembership.objects.filter(
                user=self.request.user,
                is_active=True
            ).first()
            if membership:
                tenant = membership.tenant
                self.request.tenant = tenant
        return tenant

    def get_queryset(self):
        queryset = super().get_queryset()
        tenant = self.get_tenant()
        if tenant:
            return queryset.filter(tenant=tenant)
        return queryset.none()
