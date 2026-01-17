"""
Tenant Middleware V11 - Smart validation with multi-tenant support

Responsibilities:
1. Attach active tenant to request
2. Block access if no active company
3. Block if company is SUSPENDED/CANCELLED
4. Detect expired trial
5. Support tenant switching via session
"""
from django.shortcuts import redirect
from django.contrib import messages
from django.urls import reverse

from .models import Tenant


class TenantMiddleware:
    """
    Middleware that:
    - Injects request.tenant based on user's active membership
    - Validates tenant status (active, not suspended/cancelled)
    - Detects and flags expired trials
    - Supports multi-tenant users via session-based tenant switching
    """

    # Paths that don't require tenant context
    EXEMPT_PATHS = [
        '/accounts/',
        '/signup/',
        '/admin/',
        '/static/',
        '/media/',
        '/favicon.ico',
        '/select-company/',
        '/accept-invite/',
    ]

    # Paths allowed for suspended/cancelled tenants (billing only)
    BILLING_PATHS = [
        '/billing/',
        '/upgrade/',
    ]

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Initialize request attributes
        request.tenant = None
        request.membership = None
        request.trial_expired = False
        request.tenant_blocked = False

        # Check if path is exempt
        if self._is_exempt_path(request.path):
            return self.get_response(request)

        # Anonymous users pass through (will be handled by @login_required)
        if not request.user.is_authenticated:
            return self.get_response(request)

        # Superusers bypass tenant checks for admin access
        if request.user.is_superuser and request.path.startswith('/admin/'):
            return self.get_response(request)

        # Get active membership
        membership = self._get_active_membership(request)

        if not membership:
            # User has no active company - redirect to "no company" page
            if not request.path.startswith('/no-company/'):
                messages.warning(request, "Você não está vinculado a nenhuma empresa ativa.")
                return redirect('accounts:no_company')
            return self.get_response(request)

        tenant = membership.tenant

        # Check tenant status
        if tenant.subscription_status in ['SUSPENDED', 'CANCELLED']:
            if not self._is_billing_path(request.path):
                request.tenant_blocked = True
                messages.error(
                    request,
                    f"Sua empresa está {tenant.get_subscription_status_display().lower()}. "
                    "Por favor, regularize sua assinatura."
                )
                return redirect('tenants:billing')

        # Check if tenant is inactive
        if not tenant.is_active:
            messages.error(request, "Esta empresa foi desativada.")
            return redirect('accounts:no_company')

        # Check trial expiration
        if tenant.is_trial_expired:
            request.trial_expired = True
            # Don't block, but flag for views to handle

        # Set request attributes
        request.tenant = tenant
        request.membership = membership

        return self.get_response(request)

    def _is_exempt_path(self, path):
        """Check if path is exempt from tenant requirements"""
        return any(path.startswith(exempt) for exempt in self.EXEMPT_PATHS)

    def _is_billing_path(self, path):
        """Check if path is allowed for suspended tenants"""
        return any(path.startswith(bp) for bp in self.BILLING_PATHS)

    def _get_active_membership(self, request):
        """
        Get user's active membership.
        Priority:
        1. Session-stored active_tenant_id
        2. Single active membership (auto-select)
        3. First active membership if multiple exist
        """
        from apps.accounts.models import TenantMembership

        # Get all active memberships for this user
        memberships = TenantMembership.objects.filter(
            user=request.user,
            is_active=True,
            tenant__is_active=True
        ).select_related('tenant', 'tenant__plan')

        if not memberships.exists():
            return None

        # Check if user has selected a specific tenant
        active_tenant_id = request.session.get('active_tenant_id')

        if active_tenant_id:
            # Try to get the specific membership
            membership = memberships.filter(tenant_id=active_tenant_id).first()
            if membership:
                return membership
            # If not found, clear session and fall through
            del request.session['active_tenant_id']

        # If only one membership, use it
        if memberships.count() == 1:
            return memberships.first()

        # Multiple memberships - need to select
        # For now, use first one, but ideally should redirect to selection
        # The SmartLoginView will handle this properly
        return memberships.first()


def tenant_required(view_func):
    """
    Decorator that ensures a tenant is available in request.
    Use in addition to @login_required.
    """
    from functools import wraps

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.tenant:
            messages.error(request, "Acesso requer contexto de empresa.")
            return redirect('accounts:no_company')
        return view_func(request, *args, **kwargs)

    return wrapper


def trial_allows_read(view_func):
    """
    Decorator that blocks write operations when trial is expired.
    Read operations (GET) are allowed, write operations (POST, PUT, DELETE) are blocked.
    """
    from functools import wraps
    from django.http import JsonResponse

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if request.trial_expired and request.method in ['POST', 'PUT', 'DELETE', 'PATCH']:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'error': 'Período de teste expirado. Faça upgrade para continuar.',
                    'upgrade_url': reverse('tenants:billing')
                }, status=403)

            messages.warning(
                request,
                "Seu período de teste expirou. Operações de escrita estão bloqueadas. "
                "Faça upgrade do plano para continuar."
            )
            return redirect('tenants:billing')

        return view_func(request, *args, **kwargs)

    return wrapper


def owner_required(view_func):
    """Decorator that requires OWNER role"""
    from functools import wraps
    from apps.accounts.models import MembershipRole

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.membership or request.membership.role != MembershipRole.OWNER:
            messages.error(request, "Acesso restrito ao proprietário da empresa.")
            return redirect('reports:dashboard')
        return view_func(request, *args, **kwargs)

    return wrapper


def admin_required(view_func):
    """Decorator that requires OWNER or ADMIN role"""
    from functools import wraps
    from apps.accounts.models import MembershipRole

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.membership or request.membership.role not in [MembershipRole.OWNER, MembershipRole.ADMIN]:
            messages.error(request, "Acesso restrito a administradores.")
            return redirect('reports:dashboard')
        return view_func(request, *args, **kwargs)

    return wrapper


def plan_limit_required(limit_type):
    """
    Decorator that blocks creation if plan limits are reached.
    limit_type: 'products' or 'users'
    """
    from functools import wraps

    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not request.tenant:
                return view_func(request, *args, **kwargs)

            if limit_type == 'products' and request.tenant.products_limit_reached:
                if request.method in ['POST', 'PUT']:
                    messages.error(
                        request,
                        f"Limite de produtos do seu plano '{request.tenant.plan.display_name}' atingido ({request.tenant.plan.max_products}). Faça upgrade para cadastrar mais."
                    )
                    return redirect('products:product_list')

            if limit_type == 'users' and request.tenant.users_limit_reached:
                if request.method in ['POST', 'PUT']:
                    messages.error(
                        request,
                        f"Limite de usuários do seu plano '{request.tenant.plan.display_name}' atingido ({request.tenant.plan.max_users}). Faça upgrade para convidar mais membros."
                    )
                    return redirect('accounts:invite_user')

            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator
