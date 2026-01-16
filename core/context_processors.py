from .models import SystemSetting

def global_settings(request):
    """Makes system settings available in all templates, filtered by Tenant"""
    if hasattr(request, 'tenant') and request.tenant:
        return {
            'site_settings': SystemSetting.get_settings(request.tenant)
        }
    return {}
