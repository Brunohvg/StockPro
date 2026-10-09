"""
Resolução de empresa (tenant) e permissões para a API REST.

Com JWT o TenantMiddleware não enxerga o usuário (a autenticação acontece
dentro da view do DRF), então a API precisa resolver e validar o tenant aqui.
"""
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import SAFE_METHODS, BasePermission

TENANT_HEADER = 'HTTP_X_TENANT_ID'


def resolve_api_membership(request):
    """Retorna a TenantMembership ativa do usuário para esta requisição.

    - Se o header X-Tenant-ID vier, usa essa empresa (se o usuário for membro).
    - Senão, se o usuário tiver uma única empresa ativa, usa ela.
    - Com várias empresas e sem header, exige o header.
    """
    cached = getattr(request, '_api_membership', None)
    if cached is not None:
        return cached

    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return None

    from apps.accounts.models import TenantMembership
    memberships = TenantMembership.objects.filter(
        user=user, is_active=True, tenant__is_active=True
    ).select_related('tenant', 'tenant__plan')

    tenant_id = request.META.get(TENANT_HEADER)
    if tenant_id:
        try:
            membership = memberships.filter(tenant_id=tenant_id).first()
        except (ValueError, TypeError, DjangoValidationError):
            raise ValidationError({'error': 'X-Tenant-ID inválido.'})
    else:
        # JWT exige header em múltiplas empresas, mesmo com cookie de sessão.
        from rest_framework.authentication import SessionAuthentication
        if isinstance(getattr(request, 'successful_authenticator', None), SessionAuthentication):
            active_id = request.session.get('active_tenant_id')
            if active_id is not None:
                try:
                    membership = memberships.filter(tenant_id=active_id).first()
                except (ValueError, TypeError, DjangoValidationError):
                    raise ValidationError({'error': 'Empresa da sessão inválida. Selecione novamente.'})
                request._api_membership = membership
                return membership
        count = memberships.count()
        if count > 1:
            raise ValidationError({'error': 'Usuário pertence a várias empresas. Envie o header X-Tenant-ID.'})
        membership = memberships.first()

    request._api_membership = membership
    return membership


def resolve_api_tenant(request):
    membership = resolve_api_membership(request)
    if membership:
        request.tenant = membership.tenant
        request.membership = membership
        return membership.tenant
    return None


class HasActiveTenant(BasePermission):
    """Bloqueia empresa suspensa/cancelada e escrita com trial expirado."""
    message = 'Empresa sem acesso à API.'

    def has_permission(self, request, view):
        tenant = resolve_api_tenant(request)
        if tenant is None:
            self.message = 'Tenant não identificado.'
            return False
        if tenant.subscription_status in ('SUSPENDED', 'CANCELLED'):
            self.message = 'Assinatura suspensa ou cancelada.'
            return False
        if tenant.is_trial_expired and request.method not in SAFE_METHODS:
            self.message = 'Período de teste expirado. Faça upgrade para continuar.'
            return False
        return True
