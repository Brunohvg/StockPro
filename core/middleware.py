from .models import UserProfile

class TenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Default tenant to None
        request.tenant = None

        if request.user.is_authenticated:
            try:
                # We fetch the tenant from the UserProfile
                profile = UserProfile.objects.select_related('tenant').get(user=request.user)
                request.tenant = profile.tenant
            except UserProfile.DoesNotExist:
                pass

        response = self.get_response(request)
        return response
