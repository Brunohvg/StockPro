"""
Tenant Middleware - Attaches tenant to request
"""
from .models import Tenant


class TenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.tenant = None
        if request.user.is_authenticated:
            try:
                from apps.accounts.models import UserProfile
                profile = UserProfile.objects.select_related('tenant').get(user=request.user)
                request.tenant = profile.tenant
            except:
                pass
        response = self.get_response(request)
        return response
