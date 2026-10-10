from django.conf import settings

from apps.core.models import SystemSetting


def global_settings(request):
    settings_obj = None
    if hasattr(request, 'tenant') and request.tenant:
        settings_obj = SystemSetting.get_settings(request.tenant)
    return {
        'global_settings': settings_obj,
        'tenant': getattr(request, 'tenant', None),
        'ai_active': bool(getattr(settings, 'XAI_API_KEY', None)),
        'tenant_has_ai': _tenant_has_ai(getattr(request, 'tenant', None)),
        # Função: o template só conta (1 consulta) quando mostra o item "Repor estoque" do menu
        'low_stock_count': lambda: _low_stock_count(getattr(request, 'tenant', None)),
    }


def _low_stock_count(tenant):
    if not tenant:
        return 0
    from apps.inventory.services.replenishment import low_stock_qs
    return low_stock_qs(tenant).count()


def _tenant_has_ai(tenant):
    if not tenant:
        return False
    from apps.core.services import AIService
    return AIService.tenant_has_ai(tenant)
