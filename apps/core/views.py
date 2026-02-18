"""
Core App Views - System settings
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from .forms import EmployeeForm, SystemSettingForm
from .models import SystemSetting


@login_required
def system_settings(request):
    tenant = request.tenant
    settings_obj = SystemSetting.get_settings(tenant)

    if request.method == 'POST':
        form = SystemSettingForm(request.POST, instance=settings_obj)
        if form.is_valid():
            form.save()
            messages.success(request, "Configurações globais atualizadas.")
            return redirect('core:system_settings')
    else:
        form = SystemSettingForm(instance=settings_obj)

    return render(request, 'core/settings_form.html', {'form': form, 'settings': settings_obj})


@login_required
def employee_create(request):
    from apps.accounts.models import MembershipRole, TenantMembership

    if request.method == 'POST':
        form = EmployeeForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.set_password(form.cleaned_data['password'])
            user.save()

            # Respeita o toggle de permissão do formulário
            is_admin_toggle = request.POST.get('is_staff') == 'on'
            role = MembershipRole.ADMIN if is_admin_toggle else MembershipRole.OPERATOR

            TenantMembership.objects.create(
                user=user,
                tenant=request.tenant,
                role=role,
            )

            role_label = 'Administrador' if role == MembershipRole.ADMIN else 'Operador'
            messages.success(request, f"Funcionário '{user.username}' criado como {role_label}!")
            return redirect('reports:employee_list')
    else:
        form = EmployeeForm()
    return render(request, 'core/employee_form.html', {'form': form})
