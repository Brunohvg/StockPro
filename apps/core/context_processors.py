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
        'nav_section': nav_section(request),
        'section_tabs': lambda: section_tabs(request),
    }


# (seção do menu, teste no caminho). A primeira que casar vence.
_NAV_RULES = [
    ('platform', lambda p, m: p.startswith('/admin-panel/')),
    ('labels', lambda p, m: m and m.namespace == 'labels'),
    ('replenish', lambda p, m: '/inventory/repor/' in p),
    ('move', lambda p, m: m and m.url_name in ('create_movement', 'movement_list', 'create_movement_mobile')),
    ('nfe', lambda p, m: '/inventory/nfe/' in p),
    ('imports', lambda p, m: '/inventory/imports/' in p or '/inventory/pending/' in p),
    ('export', lambda p, m: '/export' in p),
    ('locations', lambda p, m: '/inventory/locations/' in p),
    ('suppliers', lambda p, m: '/suppliers/' in p),
    ('team', lambda p, m: '/employees/' in p or '/accounts/invite' in p),
    ('taxonomy', lambda p, m: p.startswith(('/products/settings/', '/products/categories/', '/products/brands/',
                                            '/products/attributes/'))),
    ('bi', lambda p, m: '/analytics/' in p or '/margem/' in p),
    ('dashboard', lambda p, m: m and m.namespace == 'reports' and m.url_name == 'dashboard'),
    ('catalog', lambda p, m: p.startswith('/products/')),
    ('billing', lambda p, m: m and m.url_name == 'billing'),
    ('settings', lambda p, m: m and m.url_name == 'system_settings'),
]
ADMIN_SECTIONS = {'team', 'taxonomy', 'locations', 'export', 'billing', 'settings', 'platform'}


def nav_section(request):
    """Qual item do menu fica marcado (um só, mesmo com abas dentro da tela)."""
    path = getattr(request, 'path', '') or ''
    match = getattr(request, 'resolver_match', None)
    for key, test in _NAV_RULES:
        try:
            if test(path, match):
                return key
        except Exception:
            continue
    return ''


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



def section_tabs(request):
    """Abas da seção atual, para as telas que saíram do menu lateral."""
    from django.urls import reverse
    m = getattr(request, 'resolver_match', None)
    name = m.url_name if m else ''
    membership = getattr(request, 'membership', None)
    groups = [
        [('Visão do período', 'reports:inventory_reports'), ('CMV e margem', 'reports:margin_report')],
        [('Lançar', 'inventory:create_movement'), ('Histórico', 'inventory:movement_list'),
         ('Pelo celular', 'inventory:create_movement_mobile')],
    ]
    if membership and membership.is_admin:
        groups.append([('Planilhas', 'inventory:import_list'), ('Curadoria (API)', 'inventory:pending_product_list')])
    current = f"{m.namespace}:{name}" if m else ''
    for group in groups:
        if any(route == current for _, route in group):
            return [(label, reverse(route), route == current) for label, route in group]
    return []
