"""
Billing and Plan Management views
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages

from ..models import Plan


@login_required
def billing_view(request):
    """View current plan and upgrade options"""
    tenant = request.tenant
    plans = Plan.objects.all().order_by('price')
    current_plan = tenant.plan if tenant else None

    return render(request, 'core/billing.html', {
        'tenant': tenant,
        'current_plan': current_plan,
        'plans': plans,
    })


@login_required
def billing_upgrade(request, plan_id):
    """Upgrade tenant to a new plan"""
    if request.method == 'POST':
        tenant = request.tenant
        new_plan = get_object_or_404(Plan, pk=plan_id)

        # Update tenant plan
        tenant.plan = new_plan
        tenant.subscription_status = 'ACTIVE'
        tenant.save()

        messages.success(request, f"Plano atualizado para {new_plan.display_name}!")
        return redirect('billing')

    return redirect('billing')
