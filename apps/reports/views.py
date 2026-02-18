"""
Reports App Views - Dashboard and Business Intelligence
"""
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db import models
from django.db.models import F, Sum
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone

from apps.inventory.models import StockMovement
from apps.products.models import Category, Product


@login_required
def dashboard(request):
    tenant = request.tenant
    today = timezone.now().date()

    from decimal import Decimal

    from apps.products.models import ProductType, ProductVariant

    # Products (including VARIABLE parents and SIMPLE)
    products = Product.objects.filter(tenant=tenant, is_active=True)
    variants = ProductVariant.objects.filter(tenant=tenant, is_active=True)

    # Counting
    simple_products = products.filter(product_type=ProductType.SIMPLE)
    variable_products = products.filter(product_type=ProductType.VARIABLE)
    total_simple = simple_products.count()
    total_variable = variable_products.count()
    total_variants = variants.count()
    total_products = total_simple + total_variable  # Parent products only

    # Stock Value Calculation (SIMPLE + VARIANTS)
    simple_stock_value = sum(
        Decimal(p.current_stock or 0) * Decimal(p.avg_unit_cost or 0)
        for p in simple_products
    )
    variant_stock_value = sum(
        Decimal(v.current_stock or 0) * Decimal(v.avg_unit_cost or 0)
        for v in variants
    )
    total_stock_value = simple_stock_value + variant_stock_value

    # Total Units in Stock
    simple_units = sum(p.current_stock or 0 for p in simple_products)
    variant_units = sum(v.current_stock or 0 for v in variants)
    total_units = simple_units + variant_units

    # Low Stock Alerts (SIMPLE products where stock <= minimum)
    low_stock_simple = simple_products.filter(
        current_stock__lte=models.F('minimum_stock')
    ).exclude(minimum_stock=0)[:8]

    # Low Stock Alerts (VARIANTS where stock <= minimum)
    low_stock_variants = variants.filter(
        current_stock__lte=models.F('minimum_stock')
    ).exclude(minimum_stock=0).select_related('product')[:8]

    low_stock_count = low_stock_simple.count() + low_stock_variants.count()

    # Integrity Health (Divergent variants)
    divergent_count = variants.filter(inventory_status='DIVERGENT').count()

    # Today's Movements
    today_movements = StockMovement.objects.filter(tenant=tenant, created_at__date=today)
    total_movements_today = today_movements.count()
    entries_today = today_movements.filter(type='IN').aggregate(
        total=Sum('quantity')
    )['total'] or 0
    exits_today = today_movements.filter(type='OUT').aggregate(
        total=Sum('quantity')
    )['total'] or 0

    # Recent Movements (with variants support)
    recent_movements = StockMovement.objects.filter(tenant=tenant).select_related(
        'product', 'variant', 'variant__product', 'user', 'location'
    ).order_by('-created_at')[:10]

    return render(request, 'reports/dashboard.html', {
        'total_products': total_products,
        'total_simple': total_simple,
        'total_variable': total_variable,
        'total_variants': total_variants,
        'total_units': total_units,
        'total_stock_value': total_stock_value,
        'simple_stock_value': simple_stock_value,
        'variant_stock_value': variant_stock_value,
        'low_stock_count': low_stock_count,
        'low_stock_products': low_stock_simple,
        'low_stock_variants': low_stock_variants,
        'total_movements_today': total_movements_today,
        'entries_today': entries_today,
        'exits_today': exits_today,
        'recent_movements': recent_movements,
        'divergent_count': divergent_count,
    })


@login_required
def inventory_reports(request):
    """Business Intelligence View with Chart.js data and AI Insights"""
    tenant = request.tenant
    from decimal import Decimal

    from apps.products.models import ProductType, ProductVariant

    # Category breakdown (include variants for VARIABLE products)
    categories = Category.objects.filter(tenant=tenant)
    category_data = []
    for cat in categories:
        # Stock value from SIMPLE products
        simple_val = Product.objects.filter(
            category=cat,
            product_type=ProductType.SIMPLE,
            is_active=True
        ).aggregate(total=Sum(F('current_stock') * F('avg_unit_cost')))['total'] or 0

        # Stock value from VARIANTS of VARIABLE products
        variant_val = ProductVariant.objects.filter(
            product__category=cat,
            is_active=True
        ).aggregate(total=Sum(F('current_stock') * F('avg_unit_cost')))['total'] or 0

        total_cat_value = simple_val + variant_val
        if total_cat_value > 0:
            category_data.append({
                'name': cat.name,
                'total_value': float(total_cat_value)
            })

    category_data.sort(key=lambda x: x['total_value'], reverse=True)
    category_labels = [c['name'] for c in category_data]
    category_values = [c['total_value'] for c in category_data]

    end_date = timezone.now().date()
    start_date = end_date - timezone.timedelta(days=14)

    movements_trend = list(StockMovement.objects.filter(
        tenant=tenant,
        created_at__date__range=[start_date, end_date]
    ).values('created_at__date', 'type').annotate(
        total_qty=Sum('quantity')
    ).order_by('created_at__date'))

    # Collect data for AI insights
    from .services import BIService
    abc_classification = BIService.calculate_abc_analysis(tenant)
    stock_health = BIService.get_inventory_health(tenant)

    # Top products by stock value (include variants for VARIABLE products)
    all_products = Product.objects.filter(tenant=tenant, is_active=True).prefetch_related('variants')
    products_with_value = []
    for p in all_products:
        value = p.total_stock_value  # This property handles both SIMPLE and VARIABLE
        if value and value > 0:
            products_with_value.append({
                'product': p,
                'stock_value': value,
                'name': p.name,
                'sku': p.sku,
                'current_stock': p.total_stock,
                'uom': p.uom,
            })
    products_with_value.sort(key=lambda x: x['stock_value'], reverse=True)
    top_products = products_with_value[:10]

    products = Product.objects.filter(tenant=tenant, is_active=True)
    variants = ProductVariant.objects.filter(tenant=tenant, is_active=True)

    total_products = products.count()
    total_variants = variants.count()

    # Stock value
    simple_value = sum(Decimal(p.current_stock or 0) * Decimal(p.avg_unit_cost or 0)
                       for p in products.filter(product_type=ProductType.SIMPLE))
    variant_value = sum(Decimal(v.current_stock or 0) * Decimal(v.avg_unit_cost or 0)
                        for v in variants)
    total_value = simple_value + variant_value

    # Low stock count
    low_stock_count = products.filter(
        current_stock__lte=models.F('minimum_stock'),
        product_type=ProductType.SIMPLE
    ).exclude(minimum_stock=0).count()

    # Movement stats (last 7 days)
    week_ago = end_date - timezone.timedelta(days=7)
    week_movements = StockMovement.objects.filter(
        tenant=tenant,
        created_at__date__gte=week_ago
    )
    entries_week = week_movements.filter(type='IN').aggregate(total=Sum('quantity'))['total'] or 0
    exits_week = week_movements.filter(type='OUT').aggregate(total=Sum('quantity'))['total'] or 0

    # Prepare prompt-friendly data
    abc_counts = {
        'A': list(abc_classification.values()).count('A'),
        'B': list(abc_classification.values()).count('B'),
        'C': list(abc_classification.values()).count('C'),
    }

    # Generate AI insights
    ai_insights = generate_ai_insights({
        'total_products': total_products,
        'total_variants': total_variants,
        'total_value': float(total_value),
        'low_stock_count': low_stock_count,
        'entries_week': entries_week,
        'exits_week': exits_week,
        'category_data': category_data[:5],
        'abc_counts': abc_counts,
        'dead_stock_count': stock_health['item_count'],
        'dead_stock_value': float(stock_health['dead_stock_value']),
    })

    return render(request, 'reports/reports.html', {
        'category_labels': category_labels,
        'category_values': category_values,
        'top_products': top_products,
        'movements_trend': movements_trend,
        'ai_insights': ai_insights,
        'total_value': total_value,
        'low_stock_count': low_stock_count,
        'entries_week': entries_week,
        'exits_week': exits_week,
        'abc_counts': abc_counts,
        'stock_health': stock_health,
    })


def generate_ai_insights(data):
    """Generate AI-powered insights based on inventory data"""
    import json

    from apps.core.services import AIService

    prompt = f"""Você é um consultor de gestão de estoque. Analise estes dados e forneça 3-4 insights CURTOS e ACIONÁVEIS:

**Dados do Estoque:**
- Total de produtos: {data['total_products']}
- Total de variações: {data['total_variants']}
- Valor total em estoque: R$ {data['total_value']:,.2f}
- Produtos em estoque crítico: {data['low_stock_count']}
- Entradas (últimos 7 dias): {data['entries_week']} unidades
- Saídas (últimos 7 dias): {data['exits_week']} unidades
- Categorias principais: {', '.join([c['name'] for c in data.get('category_data', [])])}
- Curva ABC: {data.get('abc_counts', {})}
- Estoque Parado (>60 dias): {data.get('dead_stock_count', 0)} itens (R$ {data.get('dead_stock_value', 0):,.2f})

**Instruções:**
Analise principalmente o "Estoque Parado" e a "Curva ABC". Se houver muito capital em itens 'C' parados, sugira liquidação. Se itens 'A' estiverem em nível crítico, sugira compra imediata.
Retorne um JSON com insights práticos e SUGESTÕES DE COMPRA. Cada insight deve ter:
- icon: emoji representativo
- title: título curto (max 6 palavras)
- text: descrição CURTA de 1-2 linhas
- type: "success" | "warning" | "info" | "danger"

Exemplo de formato:
{{"insights": [
  {{"icon": "📦", "title": "Estoque saudável", "text": "Seu nível de estoque está adequado.", "type": "success"}}
]}}"""

    try:
        response = AIService.call_ai(prompt, schema="json")
        if response:
            start = response.find('{')
            end = response.rfind('}')
            if start != -1 and end != -1:
                result = json.loads(response[start:end+1])
                return result.get('insights', [])
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"AI insights failed: {e}")

    # Fallback insights
    insights = []
    if data['low_stock_count'] > 0:
        insights.append({
            'icon': '⚠️',
            'title': 'Atenção ao estoque',
            'text': f"{data['low_stock_count']} produto(s) precisam de reposição.",
            'type': 'warning'
        })
    if data['exits_week'] > data['entries_week']:
        insights.append({
            'icon': '📉',
            'title': 'Mais saídas que entradas',
            'text': 'Considere reabastecer o estoque em breve.',
            'type': 'info'
        })
    if data['total_value'] > 0:
        insights.append({
            'icon': '💰',
            'title': 'Capital em estoque',
            'text': f"R$ {data['total_value']:,.0f} investidos em inventário.",
            'type': 'info'
        })
    return insights


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
    employee = get_object_or_404(User, id=user_id)
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

    return render(request, 'reports/export.html', {
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

