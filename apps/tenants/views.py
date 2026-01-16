"""
Tenants App Views - Landing, Billing, Admin Panel
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login
from django.contrib.auth.models import User
from django.contrib import messages
from django.db import transaction
from django.db.models import Q

from .models import Plan, Tenant
from apps.accounts.models import UserProfile
from apps.core.models import SystemSetting


def landing_page(request):
    """Public landing page with plans and features"""
    plans = Plan.objects.all().order_by('price')
    features = [
        {'icon': 'smartphone', 'title': 'Operação Mobile', 'description': 'Escaneie códigos de barras direto do celular para entradas e saídas.'},
        {'icon': 'bar-chart-2', 'title': 'Business Intelligence', 'description': 'Gráficos de tendência, Curva ABC e composição de valor por categoria.'},
        {'icon': 'building-2', 'title': 'Multi-Empresa', 'description': 'Gerencie várias unidades de negócio com isolamento total de dados.'},
        {'icon': 'upload-cloud', 'title': 'Importação XML/CSV', 'description': 'Importe produtos e notas fiscais eletrônicas automaticamente.'},
        {'icon': 'shield-check', 'title': 'Auditoria Completa', 'description': 'Histórico imutável de todas as movimentações com rastreio de usuário.'},
        {'icon': 'settings', 'title': 'Configurações Flexíveis', 'description': 'Personalize alertas, regras de estoque e identidade visual.'},
    ]
    return render(request, 'tenants/landing.html', {'plans': plans, 'features': features})


@transaction.atomic
def signup_view(request):
    """Self-service signup that creates Tenant + User"""
    if request.user.is_authenticated:
        return redirect('reports:dashboard')

    if request.method == 'POST':
        company_name = request.POST.get('company_name', '').strip()
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        plan_name = request.GET.get('plan', 'FREE')

        errors = {}
        if not company_name:
            errors['company_name'] = 'Nome da empresa é obrigatório.'
        if not email:
            errors['email'] = 'E-mail é obrigatório.'
        if User.objects.filter(email=email).exists():
            errors['email'] = 'Este e-mail já está cadastrado.'
        if len(password) < 6:
            errors['password'] = 'Senha deve ter pelo menos 6 caracteres.'

        if errors:
            return render(request, 'registration/signup.html', {'form': {'errors': errors}})

        plan, _ = Plan.objects.get_or_create(name=plan_name, defaults={'display_name': plan_name.title(), 'price': 0})
        cnpj = request.POST.get('cnpj', '').strip() or None

        tenant = Tenant.objects.create(name=company_name, cnpj=cnpj, plan=plan)

        username = email.split('@')[0][:30]
        if User.objects.filter(username=username).exists():
            username = f"{username}_{tenant.pk}"
        user = User.objects.create_user(username=username, email=email, password=password, first_name=first_name, last_name=last_name, is_staff=True)

        UserProfile.objects.create(user=user, tenant=tenant)
        SystemSetting.objects.create(tenant=tenant, company_name=company_name)

        login(request, user)
        messages.success(request, f"Bem-vindo ao StockPro, {first_name}! Sua empresa '{company_name}' está pronta.")
        return redirect('reports:dashboard')

    return render(request, 'registration/signup.html', {})


@login_required
def billing_view(request):
    """View current plan and upgrade options"""
    tenant = request.tenant
    plans = Plan.objects.all().order_by('price')
    current_plan = tenant.plan if tenant else None

    return render(request, 'tenants/billing.html', {
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
        tenant.plan = new_plan
        tenant.subscription_status = 'ACTIVE'
        tenant.save()
        messages.success(request, f"Plano atualizado para {new_plan.display_name}!")
        return redirect('tenants:billing')
    return redirect('tenants:billing')


@login_required
def admin_panel_view(request):
    """Admin panel for managing all tenants - superuser only"""
    if not request.user.is_superuser:
        messages.error(request, "Acesso restrito a administradores.")
        return redirect('reports:dashboard')

    tenants = Tenant.objects.select_related('plan').order_by('-created_at')
    plans = Plan.objects.all().order_by('price')

    q = request.GET.get('q', '')
    status = request.GET.get('status', '')
    plan_filter = request.GET.get('plan', '')

    if q:
        tenants = tenants.filter(Q(name__icontains=q) | Q(cnpj__icontains=q))
    if status:
        tenants = tenants.filter(subscription_status=status)
    if plan_filter:
        tenants = tenants.filter(plan_id=plan_filter)

    active_count = Tenant.objects.filter(subscription_status='ACTIVE').count()
    trial_count = Tenant.objects.filter(subscription_status='TRIAL').count()

    return render(request, 'tenants/admin_panel.html', {
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
        return redirect('reports:dashboard')

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

    return redirect('tenants:admin_panel')
