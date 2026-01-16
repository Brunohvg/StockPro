"""
Context Processors for global template variables
"""
from apps.core.models import SystemSetting


def global_settings(request):
    settings_obj = None
    if hasattr(request, 'tenant') and request.tenant:
        settings_obj = SystemSetting.get_settings(request.tenant)
    return {
        'global_settings': settings_obj,
        'tenant': getattr(request, 'tenant', None),
    }
