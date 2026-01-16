"""
Admin Panel views - Superuser only
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q

from ..models import Tenant, Plan


@login_required
def admin_panel_view(request):
    """Admin panel for managing all tenants - superuser only"""
    if not request.user.is_superuser:
        messages.error(request, "Acesso restrito a administradores.")
        return redirect('dashboard')

    tenants = Tenant.objects.select_related('plan').order_by('-created_at')
    plans = Plan.objects.all().order_by('price')

    # Filters
    q = request.GET.get('q', '')
    status = request.GET.get('status', '')
    plan_filter = request.GET.get('plan', '')

    if q:
        tenants = tenants.filter(Q(name__icontains=q) | Q(cnpj__icontains=q))
    if status:
        tenants = tenants.filter(subscription_status=status)
    if plan_filter:
        tenants = tenants.filter(plan_id=plan_filter)

    # Stats
    active_count = Tenant.objects.filter(subscription_status='ACTIVE').count()
    trial_count = Tenant.objects.filter(subscription_status='TRIAL').count()

    return render(request, 'core/admin_panel.html', {
        'tenants': tenants,
        'plans': plans,
        'active_count': active_count,
        'trial_count': trial_count,
    })


@login_required
def admin_tenant_update(request):
    """Update tenant plan and status - superuser only"""
    if not request.user.is_superuser:
        messages.error(request, "Acesso restrito a administradores.")
        return redirect('dashboard')

    if request.method == 'POST':
        tenant_id = request.POST.get('tenant_id')
        plan_id = request.POST.get('plan_id')
        subscription_status = request.POST.get('subscription_status')
        is_active = request.POST.get('is_active') == 'on'

        tenant = get_object_or_404(Tenant, pk=tenant_id)

        if plan_id:
            tenant.plan = get_object_or_404(Plan, pk=plan_id)
        tenant.subscription_status = subscription_status
        tenant.is_active = is_active
        tenant.save()

        messages.success(request, f"Empresa '{tenant.name}' atualizada com sucesso!")

    return redirect('admin_panel')
