"""
Accounts App Views - Smart Login and Multi-Tenant Auth (V11)
"""
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth.views import LoginView
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.core.models import SystemSetting
from apps.tenants.middleware import plan_limit_required
from apps.tenants.models import Plan, Tenant

from .models import MembershipRole, TenantInvite, TenantMembership


class SmartLoginView(LoginView):
    """
    Custom login view that:
    1. Authenticates user
    2. Checks active company memberships
    3. Redirects appropriately based on company count
    """
    template_name = 'registration/login.html'

    def form_valid(self, form):
        user = form.get_user()

        # Log the user in first (specify backend to avoid ambiguity with multiple backends)
        login(self.request, user, backend='apps.accounts.backends.EmailBackend')

        # Get active memberships
        memberships = TenantMembership.objects.filter(
            user=user,
            is_active=True,
            tenant__is_active=True
        ).exclude(
            tenant__subscription_status__in=['CANCELLED']
        ).select_related('tenant')

        active_count = memberships.count()

        if active_count == 0:
            # No active companies - check if they have any pending invites
            return redirect('accounts:no_company')

        if active_count == 1:
            # Single company - auto-select
            membership = memberships.first()
            self.request.session['active_tenant_id'] = membership.tenant_id
            return redirect(self.get_success_url())

        # Multiple companies - need to select
        return redirect('accounts:select_company')

    def get_success_url(self):
        return self.get_redirect_url() or '/app/'


@login_required
def select_company(request):
    """
    Allow user to select which company to work with.
    Only shown when user has multiple active memberships.
    """
    memberships = TenantMembership.objects.filter(
        user=request.user,
        is_active=True,
        tenant__is_active=True
    ).exclude(
        tenant__subscription_status='CANCELLED'
    ).select_related('tenant', 'tenant__plan')

    if request.method == 'POST':
        tenant_id = request.POST.get('tenant_id')
        if tenant_id:
            # Verify user has access
            membership = memberships.filter(tenant_id=tenant_id).first()
            if membership:
                request.session['active_tenant_id'] = int(tenant_id)
                messages.success(request, f"Acessando {membership.tenant.name}")
                return redirect('reports:dashboard')
            else:
                messages.error(request, "Você não tem acesso a esta empresa.")

    return render(request, 'accounts/select_company.html', {
        'memberships': memberships
    })


@login_required
def switch_company(request, tenant_id):
    """Quick switch to another company"""
    membership = TenantMembership.objects.filter(
        user=request.user,
        tenant_id=tenant_id,
        is_active=True,
        tenant__is_active=True
    ).first()

    if membership:
        request.session['active_tenant_id'] = tenant_id
        messages.success(request, f"Trocado para {membership.tenant.name}")
    else:
        messages.error(request, "Você não tem acesso a esta empresa.")

    return redirect('reports:dashboard')


@login_required
def no_company(request):
    """
    Shown when user has no active company.
    Options: create company or check pending invites.
    """
    # Check if user already has a company (as owner)
    has_owned_company = TenantMembership.objects.filter(
        user=request.user,
        role=MembershipRole.OWNER
    ).exists()

    # Check pending invites
    pending_invites = TenantInvite.objects.filter(
        email=request.user.email,
        accepted_at__isnull=True,
        expires_at__gt=timezone.now()
    ).select_related('tenant')

    return render(request, 'accounts/no_company.html', {
        'can_create_company': not has_owned_company,
        'pending_invites': pending_invites
    })


@login_required
@transaction.atomic
def create_company(request):
    """
    Allow user to create their first company.
    Only allowed if user doesn't already own a company.
    """
    # Check if user already owns a company
    if TenantMembership.objects.filter(user=request.user, role=MembershipRole.OWNER).exists():
        messages.error(request, "Você já possui uma empresa cadastrada.")
        return redirect('reports:dashboard')

    if request.method == 'POST':
        company_name = request.POST.get('company_name', '').strip()
        cnpj = request.POST.get('cnpj', '').strip() or None

        if not company_name:
            messages.error(request, "Nome da empresa é obrigatório.")
            return render(request, 'accounts/create_company.html')

        # Check duplicate CNPJ
        if cnpj and Tenant.objects.filter(cnpj=cnpj).exists():
            messages.error(request, "Já existe uma empresa com este CNPJ.")
            return render(request, 'accounts/create_company.html')

        # Get free plan
        free_plan = Plan.objects.filter(name='GRATUITO').first()
        if not free_plan:
            free_plan = Plan.objects.create(
                name='GRATUITO',
                display_name='Gratuito',
                price=0,
                max_products=50,
                max_users=3
            )

        # Create tenant
        tenant = Tenant.objects.create(
            name=company_name,
            cnpj=cnpj,
            plan=free_plan,
            subscription_status='TRIAL'
        )

        # Create membership as OWNER
        TenantMembership.objects.create(
            user=request.user,
            tenant=tenant,
            role=MembershipRole.OWNER
        )

        # Create default settings
        SystemSetting.objects.create(
            tenant=tenant,
            company_name=company_name
        )

        # Set as active tenant
        request.session['active_tenant_id'] = tenant.id

        messages.success(request, f"Empresa '{company_name}' criada com sucesso!")
        return redirect('reports:dashboard')

    return render(request, 'accounts/create_company.html')


# ============ INVITE SYSTEM ============

@login_required
@plan_limit_required('users')
def invite_user(request):
    """Invite a new user to the current tenant"""
    if not request.membership or not request.membership.can_manage_users:
        messages.error(request, "Você não tem permissão para convidar usuários.")
        return redirect('reports:dashboard')

    if request.method == 'POST':
        email = request.POST.get('email', '').strip().lower()
        role = request.POST.get('role', MembershipRole.OPERATOR)

        if not email:
            messages.error(request, "E-mail é obrigatório.")
            return redirect('accounts:invite_user')

        # Check if already member
        existing_user = User.objects.filter(email=email).first()
        if existing_user:
            if TenantMembership.objects.filter(user=existing_user, tenant=request.tenant).exists():
                messages.error(request, "Este usuário já é membro da empresa.")
                return redirect('accounts:invite_user')

        # Check for existing valid invite
        existing_invite = TenantInvite.objects.filter(
            email=email,
            tenant=request.tenant,
            accepted_at__isnull=True,
            expires_at__gt=timezone.now()
        ).first()

        if existing_invite:
            messages.warning(request, "Já existe um convite pendente para este e-mail.")
            return redirect('accounts:invite_user')

        # Validate role
        if role not in [MembershipRole.ADMIN, MembershipRole.OPERATOR]:
            role = MembershipRole.OPERATOR

        # Can't invite as OWNER
        if role == MembershipRole.OWNER:
            role = MembershipRole.ADMIN

        # Create invite
        invite = TenantInvite.objects.create(
            tenant=request.tenant,
            email=email,
            role=role,
            invited_by=request.user
        )

        # In production, send email here
        # For now, just show the link
        invite_url = request.build_absolute_uri(f'/accounts/accept-invite/{invite.token}/')

        messages.success(
            request,
            f"Convite criado para {email}. Link: {invite_url}"
        )
        return redirect('reports:employee_list')

    return render(request, 'accounts/invite_user.html', {
        'roles': [
            (MembershipRole.ADMIN, 'Administrador'),
            (MembershipRole.OPERATOR, 'Operador'),
        ]
    })


def accept_invite(request, token):
    """Accept an invitation to join a company"""
    invite = get_object_or_404(TenantInvite, token=token)

    if not invite.is_valid:
        if invite.is_expired:
            messages.error(request, "Este convite expirou. Solicite um novo convite.")
        else:
            messages.error(request, "Este convite já foi utilizado.")
        return redirect('login')

    # If user is logged in
    if request.user.is_authenticated:
        if request.user.email.lower() != invite.email.lower():
            messages.error(
                request,
                f"Este convite foi enviado para {invite.email}. "
                f"Você está logado como {request.user.email}."
            )
            return redirect('reports:dashboard')

        try:
            membership = invite.accept(request.user)
            request.session['active_tenant_id'] = membership.tenant_id
            messages.success(request, f"Bem-vindo à {invite.tenant.name}!")
            return redirect('reports:dashboard')
        except ValueError as e:
            messages.error(request, str(e))
            return redirect('reports:dashboard')

    # User not logged in - check if account exists
    existing_user = User.objects.filter(email__iexact=invite.email).first()

    if existing_user:
        messages.info(request, "Faça login para aceitar o convite.")
        return redirect(f'/accounts/login/?next=/accounts/accept-invite/{token}/')

    # Need to create account
    if request.method == 'POST':
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        password = request.POST.get('password', '')

        if len(password) < 6:
            messages.error(request, "Senha deve ter pelo menos 6 caracteres.")
            return render(request, 'accounts/accept_invite.html', {'invite': invite})

        # Create user
        username = invite.email.split('@')[0][:30]
        if User.objects.filter(username=username).exists():
            username = f"{username}_{invite.tenant_id}"

        user = User.objects.create_user(
            username=username,
            email=invite.email,
            password=password,
            first_name=first_name,
            last_name=last_name
        )

        # Accept invite
        membership = invite.accept(user)

        # Login
        login(request, user, backend='apps.accounts.backends.EmailBackend')
        request.session['active_tenant_id'] = membership.tenant_id

        messages.success(request, f"Conta criada! Bem-vindo à {invite.tenant.name}!")
        return redirect('reports:dashboard')

    return render(request, 'accounts/accept_invite.html', {'invite': invite})
