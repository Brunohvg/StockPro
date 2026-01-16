"""
Dashboard view
"""
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.utils import timezone

from ..models import Product, StockMovement


@login_required
def dashboard(request):
    tenant = request.tenant
    products = Product.objects.filter(tenant=tenant)
    today = timezone.now().date()

    # Quick stats
    total_products = products.count()
    total_stock_value = sum(
        (p.current_stock or 0) * (p.avg_unit_cost or 0) for p in products
    )
    low_stock_count = products.filter(current_stock__lte=10).count()
    total_movements_today = StockMovement.objects.filter(tenant=tenant, created_at__date=today).count()

    recent_movements = StockMovement.objects.filter(tenant=tenant).select_related('product', 'user').order_by('-created_at')[:10]

    context = {
        'total_products': total_products,
        'total_stock_value': total_stock_value,
        'low_stock_count': low_stock_count,
        'total_movements_today': total_movements_today,
        'recent_movements': recent_movements,
    }
    return render(request, 'core/dashboard.html', context)
