"""
Reports and Business Intelligence views
"""
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db import models
from django.db.models import Sum, F
from django.utils import timezone

from ..models import Product, StockMovement, Category


@login_required
def inventory_reports(request):
    """Business Intelligence View with Chart.js data"""
    tenant = request.tenant

    # 1. Composition by Category (Value)
    category_qs = Category.objects.filter(tenant=tenant).annotate(
        total_value=Sum(F('products__current_stock') * F('products__avg_unit_cost'), output_field=models.DecimalField())
    ).values('name', 'total_value').order_by('-total_value')

    # 2. Daily Movement Trend (Last 15 days)
    end_date = timezone.now().date()
    start_date = end_date - timezone.timedelta(days=14)

    movements_trend = list(StockMovement.objects.filter(
        tenant=tenant,
        created_at__date__range=[start_date, end_date]
    ).values('created_at__date', 'type').annotate(
        total_qty=Sum('quantity')
    ).order_by('created_at__date'))

    # 3. ABC Analysis (Simplified: Top 10 by Stock Value)
    top_products = Product.objects.filter(tenant=tenant).annotate(
        stock_value=F('current_stock') * F('avg_unit_cost')
    ).order_by('-stock_value')[:10]

    return render(request, 'core/reports.html', {
        'category_labels': [c['name'] for c in category_qs if c['total_value']],
        'category_values': [float(c['total_value'] or 0) for c in category_qs if c['total_value']],
        'top_products': top_products,
        'movements_trend': movements_trend,
    })
