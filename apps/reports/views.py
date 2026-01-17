"""
Reports App Views - Dashboard and Business Intelligence
"""
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db import models
from django.db.models import Sum, F
from django.utils import timezone

from apps.products.models import Product, Category
from apps.inventory.models import StockMovement


@login_required
def dashboard(request):
    tenant = request.tenant
    today = timezone.now().date()

    from apps.products.models import ProductVariant, ProductType
    from decimal import Decimal

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
    })


@login_required
def inventory_reports(request):
    """Business Intelligence View with Chart.js data and AI Insights"""
    tenant = request.tenant
    from apps.products.models import ProductVariant, ProductType
    from decimal import Decimal

    # Category breakdown
    category_qs = Category.objects.filter(tenant=tenant).annotate(
        total_value=Sum(F('products__current_stock') * F('products__avg_unit_cost'), output_field=models.DecimalField())
    ).values('name', 'total_value').order_by('-total_value')

    end_date = timezone.now().date()
    start_date = end_date - timezone.timedelta(days=14)

    movements_trend = list(StockMovement.objects.filter(
        tenant=tenant,
        created_at__date__range=[start_date, end_date]
    ).values('created_at__date', 'type').annotate(
        total_qty=Sum('quantity')
    ).order_by('created_at__date'))

    top_products = Product.objects.filter(tenant=tenant).annotate(
        stock_value=F('current_stock') * F('avg_unit_cost')
    ).order_by('-stock_value')[:10]

    # Collect data for AI insights
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

    # Generate AI insights
    ai_insights = generate_ai_insights({
        'total_products': total_products,
        'total_variants': total_variants,
        'total_value': float(total_value),
        'low_stock_count': low_stock_count,
        'entries_week': entries_week,
        'exits_week': exits_week,
        'category_data': list(category_qs[:5]),
    })

    return render(request, 'reports/reports.html', {
        'category_labels': [c['name'] for c in category_qs if c['total_value']],
        'category_values': [float(c['total_value'] or 0) for c in category_qs if c['total_value']],
        'top_products': top_products,
        'movements_trend': movements_trend,
        'ai_insights': ai_insights,
        'total_value': total_value,
        'low_stock_count': low_stock_count,
        'entries_week': entries_week,
        'exits_week': exits_week,
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

**Instruções:**
Retorne um JSON com insights práticos. Cada insight deve ter:
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
    employees = User.objects.filter(is_active=True).order_by('username')
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
    """Export products to CSV"""
    from django.http import HttpResponse
    from .exports import ProductExporter

    exporter = ProductExporter(request.tenant)
    include_variants = request.GET.get('variants', 'true').lower() == 'true'
    include_inactive = request.GET.get('inactive', 'false').lower() == 'true'

    csv_content = exporter.export_csv(include_variants=include_variants, include_inactive=include_inactive)

    response = HttpResponse(csv_content, content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="produtos_{timezone.now().strftime("%Y%m%d_%H%M")}.csv"'
    return response


@login_required
def export_products_excel(request):
    """Export products to Excel"""
    from django.http import HttpResponse
    from .exports import ProductExporter

    exporter = ProductExporter(request.tenant)
    include_variants = request.GET.get('variants', 'true').lower() == 'true'
    include_inactive = request.GET.get('inactive', 'false').lower() == 'true'

    try:
        excel_content = exporter.export_excel(include_variants=include_variants, include_inactive=include_inactive)
        response = HttpResponse(
            excel_content,
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = f'attachment; filename="produtos_{timezone.now().strftime("%Y%m%d_%H%M")}.xlsx"'
        return response
    except ImportError as e:
        from django.http import JsonResponse
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def export_products_json(request):
    """Export products to JSON"""
    from django.http import HttpResponse
    from .exports import ProductExporter

    exporter = ProductExporter(request.tenant)
    include_variants = request.GET.get('variants', 'true').lower() == 'true'
    include_inactive = request.GET.get('inactive', 'false').lower() == 'true'

    json_content = exporter.export_json(include_variants=include_variants, include_inactive=include_inactive)

    response = HttpResponse(json_content, content_type='application/json; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="produtos_{timezone.now().strftime("%Y%m%d_%H%M")}.json"'
    return response


@login_required
def export_movements_csv(request):
    """Export stock movements to CSV"""
    from django.http import HttpResponse
    import csv
    import io

    tenant = request.tenant
    days = int(request.GET.get('days', 30))
    start_date = timezone.now().date() - timezone.timedelta(days=days)

    movements = StockMovement.objects.filter(
        tenant=tenant,
        created_at__date__gte=start_date
    ).select_related('product', 'variant', 'variant__product', 'user').order_by('-created_at')

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Data', 'Hora', 'Tipo', 'SKU', 'Produto', 'Quantidade', 'Saldo', 'Custo Unit.', 'Operador', 'Motivo'])

    for mov in movements:
        if mov.variant:
            sku = mov.variant.sku
            name = mov.variant.display_name
        elif mov.product:
            sku = mov.product.sku
            name = mov.product.name
        else:
            sku = '-'
            name = '(Removido)'

        writer.writerow([
            mov.created_at.strftime('%Y-%m-%d'),
            mov.created_at.strftime('%H:%M:%S'),
            mov.get_type_display(),
            sku,
            name,
            mov.quantity,
            mov.balance_after,
            float(mov.unit_cost) if mov.unit_cost else '',
            mov.user.username if mov.user else 'Sistema',
            mov.reason or ''
        ])

    response = HttpResponse(output.getvalue(), content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="movimentacoes_{timezone.now().strftime("%Y%m%d_%H%M")}.csv"'
    return response


@login_required
def export_page(request):
    """Export page with options"""
    return render(request, 'reports/export.html')

