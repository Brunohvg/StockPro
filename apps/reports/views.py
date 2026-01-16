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
    products = Product.objects.filter(tenant=tenant)
    today = timezone.now().date()

    total_products = products.count()
    total_stock_value = sum(
        (p.current_stock or 0) * (p.avg_unit_cost or 0) for p in products
    )
    low_stock_products = products.filter(current_stock__lte=models.F('minimum_stock'))[:10]
    low_stock_count = low_stock_products.count()
    total_movements_today = StockMovement.objects.filter(tenant=tenant, created_at__date=today).count()

    recent_movements = StockMovement.objects.filter(tenant=tenant).select_related(
        'product', 'variant', 'variant__product', 'user'
    ).order_by('-created_at')[:10]

    return render(request, 'reports/dashboard.html', {
        'total_products': total_products,
        'total_stock_value': total_stock_value,
        'low_stock_count': low_stock_count,
        'low_stock_products': low_stock_products,
        'total_movements_today': total_movements_today,
        'recent_movements': recent_movements,
    })


@login_required
def inventory_reports(request):
    """Business Intelligence View with Chart.js data"""
    tenant = request.tenant

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

    return render(request, 'reports/reports.html', {
        'category_labels': [c['name'] for c in category_qs if c['total_value']],
        'category_values': [float(c['total_value'] or 0) for c in category_qs if c['total_value']],
        'top_products': top_products,
        'movements_trend': movements_trend,
    })


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

