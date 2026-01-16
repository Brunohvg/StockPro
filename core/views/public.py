"""
Public views - Landing page and Signup
"""
from django.shortcuts import render, redirect
from django.contrib.auth import login
from django.contrib.auth.models import User
from django.db import transaction
from django.contrib import messages

from ..models import Plan, Tenant, UserProfile, SystemSetting


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
    return render(request, 'core/landing.html', {'plans': plans, 'features': features})


@transaction.atomic
def signup_view(request):
    """Self-service signup that creates Tenant + User"""
    if request.user.is_authenticated:
        return redirect('dashboard')

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

        # Get or create the plan
        plan, _ = Plan.objects.get_or_create(name=plan_name, defaults={'display_name': plan_name.title(), 'price': 0})

        # Get CNPJ (optional field)
        cnpj = request.POST.get('cnpj', '').strip() or None

        # Create Tenant
        tenant = Tenant.objects.create(name=company_name, cnpj=cnpj, plan=plan)

        # Create User
        username = email.split('@')[0][:30]
        if User.objects.filter(username=username).exists():
            username = f"{username}_{tenant.pk}"
        user = User.objects.create_user(username=username, email=email, password=password, first_name=first_name, last_name=last_name, is_staff=True)

        # Link User to Tenant
        UserProfile.objects.create(user=user, tenant=tenant)

        # Create default SystemSetting for the tenant
        SystemSetting.objects.create(tenant=tenant, company_name=company_name)

        # Auto-login
        login(request, user)
        messages.success(request, f"Bem-vindo ao StockPro, {first_name}! Sua empresa '{company_name}' está pronta.")
        return redirect('dashboard')

    return render(request, 'registration/signup.html', {})
