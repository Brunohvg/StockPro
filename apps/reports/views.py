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
    low_stock_count = products.filter(current_stock__lte=10).count()
    total_movements_today = StockMovement.objects.filter(tenant=tenant, created_at__date=today).count()

    recent_movements = StockMovement.objects.filter(tenant=tenant).select_related('product', 'user').order_by('-created_at')[:10]

    return render(request, 'reports/dashboard.html', {
        'total_products': total_products,
        'total_stock_value': total_stock_value,
        'low_stock_count': low_stock_count,
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
    movements = StockMovement.objects.filter(tenant=request.tenant, user=employee).order_by('-created_at')[:50]
    return render(request, 'reports/employee_detail.html', {'employee': employee, 'movements': movements})
