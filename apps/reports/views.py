"""
Reports App Views - Dashboard and Business Intelligence
"""
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db import models
from django.db.models import F, Sum
from django.shortcuts import render, redirect, get_object_or_404

from apps.core.models import SystemSetting
from django.utils import timezone

from apps.inventory.models import StockMovement
from apps.products.models import Category, Product


def _greeting(now):
    hour = timezone.localtime(now).hour
    if hour < 12:
        return 'Bom dia'
    if hour < 18:
        return 'Boa tarde'
    return 'Boa noite'


@login_required
def dashboard(request):
    """Visão Geral: o que fazer hoje. Números de apps/reports/metrics.py."""
    from . import metrics

    tenant = request.tenant
    now = timezone.now()
    data = metrics.overview(tenant, now)

    recent_movements = StockMovement.objects.filter(tenant=tenant).select_related(
        'variant', 'variant__product', 'user'
    ).prefetch_related('variant__attribute_values').order_by('-created_at')[:10]

    from apps.inventory.services.expiry import expiring_lots
    settings_obj = SystemSetting.get_settings(tenant) if tenant else None
    expiry_window = settings_obj.expiry_alert_days if settings_obj else 30
    expired_lots, expiring_soon_lots = expiring_lots(tenant, expiry_window)

    onboarding = metrics.onboarding(tenant)
    return render(request, 'reports/dashboard.html', {
        **data,
        'greeting': _greeting(now),
        'now_local': timezone.localtime(now),
        'recent_movements': recent_movements,
        'expired_lots': expired_lots[:10],
        'expired_lots_count': len(expired_lots),
        'expiring_lots': expiring_soon_lots[:10],
        'expiring_lots_count': len(expiring_soon_lots),
        'expiry_window': expiry_window,
        'onboarding': onboarding,
        'is_new_company': data['stock']['skus'] == 0,
        'checked_at': timezone.localtime(now),
    })


@login_required
def inventory_reports(request):
    """Inteligência: como está indo o negócio no período, comparado com o anterior."""
    from apps.core.services import AIService

    from . import metrics

    tenant = request.tenant
    per = metrics.period(request.GET.get('periodo', '30'))
    data = metrics.intelligence(tenant, per)
    rule_insights = metrics.insights(data)

    ai_ready = metrics.has_history(tenant) and data['sales']['units'] > 0
    insights = rule_insights
    if ai_ready and AIService.tenant_has_ai(tenant):
        insights = generate_ai_insights(tenant=tenant, refresh=request.GET.get('refresh_ai') == '1',
                                        fallback=rule_insights, data={
            'period_days': per.days,
            'skus': data['stock']['skus'],
            'stock_value': float(data['stock']['value']),
            'units': float(data['sales']['units']),
            'revenue': float(data['sales']['revenue']),
            'margin_pct': data['sales']['margin_pct'],
            'units_change': data['changes']['units'],
            'coverage_days': data['coverage_days'],
            'low_count': data['low_count'],
            'stalled_count': data['stalled']['count'],
            'stalled_value': float(data['stalled']['value']),
            'abc_a': data['abc']['A']['count'],
            'top': [r['variant'].display_name for r in data['top'][:5]],
            'categories': [c['name'] for c in data['categories'][:5]],
        })

    # Formato único para o template (regras usam "tone"; a IA devolve "type" e "icon")
    insights = [{'icon': i.get('icon', ''), 'title': i.get('title', ''), 'text': i.get('text', ''),
                 'source': i.get('source', ''), 'tone': i.get('tone') or i.get('type') or 'info'}
                for i in insights]

    series = data['series']
    chart = {
        'labels': [d['label'] for d in series],
        'in': [d['in'] for d in series],
        'out': [d['out'] for d in series],
        'cat_labels': [c['name'] for c in data['categories'][:8]],
        'cat_values': [float(c['value']) for c in data['categories'][:8]],
    }
    return render(request, 'reports/reports.html', {
        **data,
        'periods': metrics.PERIODS,
        'abc_rows': [(g, data['abc'][g]) for g in 'ABC'],
        'chart': chart,
        'has_series': any(d['in'] or d['out'] for d in series),
        'ai_insights': insights,
        'ai_insights_from_ai': any(i.get('source') == 'ai' for i in insights),
        'ai_ready': ai_ready,
        'stalled_days': metrics.STALLED_DAYS,
    })


AI_INSIGHTS_CACHE_SECONDS = 6 * 60 * 60


def generate_ai_insights(data, tenant=None, refresh=False, fallback=None):
    """
    Insights com IA (plano com IA, dentro do limite diário), guardados por 6 h por
    empresa: abrir a página várias vezes custa uma chamada. Sem IA ou se a IA
    falhar, devolve `fallback` (as regras de apps/reports/metrics.py).
    """
    import json

    from django.core.cache import cache

    from apps.core.services import AIService, AIUnavailable

    fallback = fallback or []
    if tenant is None or not AIService.tenant_has_ai(tenant):
        return fallback
    cache_key = f"ai-insights:{tenant.pk}"
    if not refresh:
        cached = cache.get(cache_key)
        if cached:
            return cached

    prompt = f"""Você é um consultor de gestão de estoque de uma loja pequena. Analise os números e escreva 3 ou 4 insights CURTOS e ACIONÁVEIS, sem repetir os números à toa e sem frases que se contradigam.

Período: últimos {data['period_days']} dias.
- Itens ativos: {data['skus']}
- Valor em estoque (custo): R$ {data['stock_value']:,.2f}
- Vendido no período: {data['units']:,.0f} unidades, R$ {data['revenue']:,.2f} pelo preço de venda
- Margem bruta: {data['margin_pct'] if data['margin_pct'] is not None else 'sem preço de venda'}
- Variação das vendas contra o período anterior: {data['units_change'] if data['units_change'] is not None else 'sem base'}
- Cobertura (dias que o estoque dura no ritmo atual): {data['coverage_days'] if data['coverage_days'] is not None else 'sem vendas'}
- Itens no estoque mínimo: {data['low_count']}
- Parados há 60+ dias: {data['stalled_count']} itens, R$ {data['stalled_value']:,.2f}
- Itens da classe A (80% do faturamento): {data['abc_a']}
- Mais vendidos: {', '.join(data['top']) or 'nenhum'}
- Categorias com mais valor: {', '.join(data['categories']) or 'nenhuma'}

Retorne JSON: {{"insights": [{{"icon": "emoji", "title": "até 6 palavras", "text": "1 ou 2 linhas", "type": "success|warning|info|danger"}}]}}"""

    try:
        response = AIService.call_for_tenant(tenant, prompt, schema="json")
        if response:
            start = response.find('{')
            end = response.rfind('}')
            if start != -1 and end != -1:
                result = json.loads(response[start:end+1])
                insights = [dict(i, source='ai') for i in result.get('insights', []) if isinstance(i, dict)]
                if insights:
                    cache.set(cache_key, insights, AI_INSIGHTS_CACHE_SECONDS)
                    return insights
    except AIUnavailable:
        pass
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"AI insights failed: {e}")
    return fallback


@login_required
def employee_list(request):
    employees = User.objects.filter(
        memberships__tenant=request.tenant,
        memberships__is_active=True,
        is_active=True
    ).distinct().order_by('username')
    return render(request, 'reports/employee_list.html', {'employees': employees})


@login_required
def employee_detail(request, user_id):
    from django.shortcuts import get_object_or_404
    employee = get_object_or_404(
        User.objects.filter(memberships__tenant=request.tenant).distinct(), id=user_id
    )
    movements = StockMovement.objects.filter(
        tenant=request.tenant, user=employee
    ).select_related('product', 'variant', 'variant__product').order_by('-created_at')[:50]
    return render(request, 'reports/employee_detail.html', {'employee': employee, 'movements': movements})


# ============ EXPORT VIEWS ============

@login_required
def export_products_csv(request):
    """Trigger Async CSV Export"""
    from apps.inventory.models import ExportBatch
    from apps.inventory.tasks import process_export_catalog

    batch = ExportBatch.objects.create(
        tenant=request.tenant,
        user=request.user,
        status='PENDING',
        export_type='CSV',
        resource='PRODUCTS'
    )
    process_export_catalog.delay(str(batch.id))
    return redirect('reports:export_page')


@login_required
def export_products_excel(request):
    """Trigger Async Excel Export"""
    from apps.inventory.models import ExportBatch
    from apps.inventory.tasks import process_export_catalog

    batch = ExportBatch.objects.create(
        tenant=request.tenant,
        user=request.user,
        status='PENDING',
        export_type='EXCEL',
        resource='PRODUCTS'
    )
    process_export_catalog.delay(str(batch.id))
    return redirect('reports:export_page')


@login_required
def export_products_json(request):
    """Trigger Async JSON Export"""
    from apps.inventory.models import ExportBatch
    from apps.inventory.tasks import process_export_catalog

    batch = ExportBatch.objects.create(
        tenant=request.tenant,
        user=request.user,
        status='PENDING',
        export_type='JSON',
        resource='PRODUCTS'
    )
    process_export_catalog.delay(str(batch.id))
    return redirect('reports:export_page')


@login_required
def export_movements_csv(request):
    """Trigger Async Movements Export"""
    from apps.inventory.models import ExportBatch
    from apps.inventory.tasks import process_export_catalog
    import json

    days = int(request.GET.get('days', 30))
    params = {'days': days}

    batch = ExportBatch.objects.create(
        tenant=request.tenant,
        user=request.user,
        status='PENDING',
        export_type='CSV',
        resource='MOVEMENTS',
        params=json.dumps(params)
    )
    process_export_catalog.delay(str(batch.id))
    return redirect('reports:export_page')


@login_required
def export_page(request):
    """Export page with options and history"""
    from apps.inventory.models import ExportBatch

    exports = ExportBatch.objects.filter(tenant=request.tenant).order_by('-created_at')

    completed_count = exports.filter(status='COMPLETED').count()
    error_count = exports.filter(status='FAILED').count()

    from apps.tenants.backup_status import last_success_for_clients

    return render(request, 'reports/export.html', {
        'last_backup_at': last_success_for_clients(),
        'exports': exports,
        'completed_count': completed_count,
        'error_count': error_count
    })


@login_required
def delete_export(request, pk):
    """Delete a single export batch"""
    from apps.inventory.models import ExportBatch
    if request.method == 'POST':
        export = get_object_or_404(ExportBatch, pk=pk, tenant=request.tenant)
        export.delete()
    return redirect('reports:export_page')


@login_required
def delete_exports_batch(request):
    """Delete multiple exports"""
    from apps.inventory.models import ExportBatch
    if request.method == 'POST':
        ids = request.POST.getlist('selected_ids')
        if ids:
            ExportBatch.objects.filter(
                tenant=request.tenant,
                id__in=ids
            ).delete()
    return redirect('reports:export_page')



@login_required
def margin_report(request):
    """
    Relatório de CMV e Margem por produto.
    Cruza avg_unit_cost com sale_price para calcular margem bruta.
    """
    from decimal import Decimal
    from apps.products.models import ProductVariant, ProductType

    tenant = request.tenant

    # Buscar todas as variantes com preço de custo
    variants = ProductVariant.objects.filter(
        tenant=tenant,
        is_active=True,
        avg_unit_cost__isnull=False,
    ).select_related('product', 'product__category').order_by('product__name', 'name')

    items = []
    total_stock_value = Decimal('0')
    total_sale_value = Decimal('0')
    sem_preco_venda = 0

    for v in variants:
        custo = Decimal(str(v.avg_unit_cost or 0))
        preco_venda = None

        # Tenta pegar preço de venda da variante, depois do produto pai
        if hasattr(v, 'sale_price') and v.sale_price:
            preco_venda = Decimal(str(v.sale_price))
        elif hasattr(v.product, 'sale_price') and v.product.sale_price:
            preco_venda = Decimal(str(v.product.sale_price))

        estoque = Decimal(str(v.current_stock or 0))
        valor_estoque = estoque * custo

        if preco_venda and preco_venda > 0:
            margem_unit = preco_venda - custo
            margem_pct = (margem_unit / preco_venda * 100) if preco_venda else Decimal('0')
            valor_venda_estoque = estoque * preco_venda
        else:
            margem_unit = None
            margem_pct = None
            valor_venda_estoque = None
            sem_preco_venda += 1

        total_stock_value += valor_estoque
        if valor_venda_estoque:
            total_sale_value += valor_venda_estoque

        items.append({
            'variant': v,
            'product_name': v.product.name,
            'category': v.product.category.name if v.product.category else '—',
            'sku': v.sku,
            'custo': custo,
            'preco_venda': preco_venda,
            'margem_unit': margem_unit,
            'margem_pct': margem_pct,
            'estoque': estoque,
            'valor_estoque': valor_estoque,
            'valor_venda_estoque': valor_venda_estoque,
            'alert': margem_pct is not None and margem_pct < 20,
        })

    # Ordenar por margem (sem preço de venda no final)
    items.sort(key=lambda x: (x['margem_pct'] is None, x['margem_pct'] or 0))

    lucro_potencial = total_sale_value - total_stock_value if total_sale_value else None

    return render(request, 'reports/margin_report.html', {
        'items': items,
        'total_stock_value': total_stock_value,
        'total_sale_value': total_sale_value,
        'lucro_potencial': lucro_potencial,
        'sem_preco_venda': sem_preco_venda,
        'total_produtos': len(items),
    })
