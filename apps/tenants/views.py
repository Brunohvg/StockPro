"""
Tenants App Views - Landing, Billing, Admin Panel
"""
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from apps.core.models import SystemSetting

from .models import Plan, Tenant


def landing_page(request):
    """Public landing page with plans and features"""
    if request.user.is_authenticated:
        return redirect('reports:dashboard')

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
    """Self-service signup that creates Tenant + User + Membership"""
    if request.user.is_authenticated:
        return redirect('reports:dashboard')

    if request.method == 'POST':
        company_name = request.POST.get('company_name', '').strip()
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        email = request.POST.get('email', '').strip().lower()
        password = request.POST.get('password', '')
        plan_name = request.GET.get('plan', 'GRATUITO')

        errors = {}
        if not company_name:
            errors['company_name'] = 'Nome da empresa é obrigatório.'
        if not email:
            errors['email'] = 'E-mail é obrigatório.'
        if email and User.objects.filter(Q(email__iexact=email) | Q(username__iexact=email)).exists():
            errors['email'] = 'Este e-mail já está cadastrado.'
        try:
            validate_password(password)
        except ValidationError as e:
            errors['password'] = ' '.join(e.messages)

        # Check for duplicate CNPJ
        cnpj = request.POST.get('cnpj', '').strip() or None
        if cnpj and Tenant.objects.filter(cnpj=cnpj).exists():
            errors['cnpj'] = 'Já existe uma empresa com este CNPJ.'

        if errors:
            return render(request, 'registration/signup.html', {'form': {'errors': errors}})

        # Get or create plan (only use existing plans, don't auto-create)
        plan = Plan.objects.filter(name=plan_name).first()
        if not plan:
            plan = Plan.objects.filter(name='GRATUITO').first()
        if not plan:
            plan = Plan.objects.create(name='GRATUITO', display_name='Gratuito', price=0, max_products=50, max_users=3)

        tenant = Tenant.objects.create(name=company_name, cnpj=cnpj, plan=plan, subscription_status='TRIAL')

        username = email.split('@')[0][:30]
        if User.objects.filter(username=username).exists():
            username = f"{username}_{tenant.pk}"
        user = User.objects.create_user(username=username, email=email, password=password, first_name=first_name, last_name=last_name)

        # Create membership as OWNER (V11)
        from apps.accounts.models import MembershipRole, TenantMembership
        TenantMembership.objects.create(user=user, tenant=tenant, role=MembershipRole.OWNER)

        SystemSetting.objects.create(tenant=tenant, company_name=company_name)

        login(request, user, backend='apps.accounts.backends.EmailBackend')
        request.session['active_tenant_id'] = tenant.id  # Set active tenant
        messages.success(request, f"Bem-vindo ao StockPro, {first_name}! Sua empresa '{company_name}' está pronta.")
        return redirect('reports:dashboard')

    return render(request, 'registration/signup.html', {})



@login_required
def billing_view(request):
    """View current plan and upgrade options"""
    from django.conf import settings
    from apps.core.models import SystemSetting
    tenant = request.tenant
    plans = Plan.objects.all().order_by('price')
    current_plan = tenant.plan if tenant else None
    global_settings = SystemSetting.get_settings(tenant) if tenant else None
    ai_active = bool(
        getattr(settings, 'GROQ_API_KEY', None) or
        getattr(settings, 'GEMINI_API_KEY', None) or
        getattr(settings, 'OPENAI_API_KEY', None)
    )
    whatsapp_number = getattr(settings, 'WHATSAPP_SUPPORT', '5511999999999')

    return render(request, 'tenants/billing.html', {
        'tenant': tenant,
        'current_plan': current_plan,
        'plans': plans,
        'ai_active': ai_active,
        'whatsapp_number': whatsapp_number,
    })


@login_required
def billing_upgrade(request, plan_id):
    """Upgrade tenant to a new plan.

    Sem integração de pagamento, troca de plano é operação administrativa:
    apenas superusuário pode executar. Clientes devem solicitar via suporte.
    """
    if not request.user.is_superuser:
        messages.info(request, "Para mudar de plano, fale com o suporte pelo WhatsApp.")
        return redirect('tenants:billing')
    if request.method == 'POST':
        tenant = request.tenant
        if tenant is None:
            messages.error(request, "Selecione uma empresa antes de alterar o plano.")
            return redirect('tenants:billing')
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

    from .backup_status import health as backup_health

    return render(request, 'tenants/admin_panel.html', {
        'backup_health': backup_health(),
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


# ─── Backups (só superusuário da plataforma) ─────────────────────────────────
# O backup contém o banco de TODAS as empresas: a tela mostra a situação e
# permite rodar/conferir, mas nunca oferece download pelo navegador.

def _superuser_only(request):
    if not request.user.is_superuser:
        messages.error(request, "Acesso restrito a administradores.")
        return redirect('reports:dashboard')
    return None


@login_required
def admin_backups_view(request):
    denied = _superuser_only(request)
    if denied:
        return denied
    from django.conf import settings as dj_settings

    from . import backup_status
    from .models import BackupRun

    runs = list(BackupRun.objects.all()[:40])
    for run in runs:
        run.is_verify = run.trigger == backup_status.VERIFY
        run.is_stale = backup_status.is_stale_running(run)
    return render(request, 'tenants/admin_backups.html', {
        'health': backup_status.health(),
        'runs': runs,
        'disk': backup_status.local_disk(),
        'cfg': {
            'bucket': getattr(dj_settings, 'BACKUP_S3_BUCKET', ''),
            'endpoint': getattr(dj_settings, 'BACKUP_S3_ENDPOINT_URL', '') or 'AWS S3',
            'prefix': getattr(dj_settings, 'BACKUP_S3_PREFIX', ''),
            'remote_days': getattr(dj_settings, 'BACKUP_REMOTE_RETENTION_DAYS', None),
            'remote_min': getattr(dj_settings, 'BACKUP_REMOTE_MIN_KEEP', None),
            'local_days': getattr(dj_settings, 'BACKUP_RETENTION_DAYS', None),
            'include_media': getattr(dj_settings, 'BACKUP_INCLUDE_MEDIA', False),
            'alert_email': getattr(dj_settings, 'BACKUP_ALERT_EMAIL', '') or ', '.join(
                e for _, e in getattr(dj_settings, 'ADMINS', [])),
        },
    })


def _enqueue(request, task, ok_message):
    try:
        task.delay(requested_by=request.user.email or request.user.username)
    except Exception as exc:  # broker fora do ar
        messages.error(request, f"Não foi possível agendar: a fila de tarefas (Redis/worker) não respondeu ({type(exc).__name__}).")
    else:
        messages.success(request, ok_message)
    return redirect('tenants:admin_backups')


@login_required
def admin_backup_run(request):
    denied = _superuser_only(request)
    if denied:
        return denied
    if request.method != 'POST':
        return redirect('tenants:admin_backups')
    from .backup_status import running_backup
    from .backup_task import manual_backup
    if running_backup():
        messages.warning(request, "Já existe um backup em andamento. Aguarde ele terminar.")
        return redirect('tenants:admin_backups')
    return _enqueue(request, manual_backup,
                    "Backup iniciado. Atualize a página em alguns minutos para ver o resultado.")


@login_required
def admin_backup_verify(request):
    denied = _superuser_only(request)
    if denied:
        return denied
    if request.method != 'POST':
        return redirect('tenants:admin_backups')
    from .backup import s3_enabled
    from .backup_task import verify_backup
    if not s3_enabled():
        messages.error(request, "A conferência baixa o backup do bucket, e o bucket não está configurado (BACKUP_S3_BUCKET).")
        return redirect('tenants:admin_backups')
    return _enqueue(request, verify_backup,
                    "Conferência iniciada: o último backup será baixado, aberto e checado.")
