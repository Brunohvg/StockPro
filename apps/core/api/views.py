from rest_framework import serializers, viewsets
from rest_framework.permissions import IsAuthenticated

from .tenant import HasActiveTenant, resolve_api_tenant


class TenantSerializerMixin(metaclass=serializers.SerializerMetaclass):
    """
    Mixin to automatically handle tenant assignment during creation.
    """
    def create(self, validated_data):
        if 'tenant' not in validated_data:
            # Try to get tenant from request (set by middleware or view)
            tenant = getattr(self.context['request'], 'tenant', None) or resolve_api_tenant(self.context['request'])

            if tenant:
                validated_data['tenant'] = tenant
        return super().create(validated_data)

class BaseTenantViewSet(viewsets.ModelViewSet):
    """
    Base ViewSet that automatically filters querysets by the request's tenant.
    All API views for multi-tenant models should inherit from this.
    """
    permission_classes = [IsAuthenticated, HasActiveTenant]

    def get_tenant(self):
        """Ensures tenant is resolved and returns it."""
        return getattr(self.request, 'tenant', None) or resolve_api_tenant(self.request)

    def get_queryset(self):
        queryset = super().get_queryset()
        tenant = self.get_tenant()
        if tenant:
            return queryset.filter(tenant=tenant)
        return queryset.none()
