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
    if request.method == 'POST':
        form = EmployeeForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.set_password(form.cleaned_data['password'])
            user.save()

            # Create membership (V11 fix)
            from apps.accounts.models import MembershipRole, TenantMembership
            TenantMembership.objects.create(
                user=user,
                tenant=request.tenant,
                role=MembershipRole.OPERATOR
            )

            messages.success(request, f"Funcionário '{user.username}' criado!")
            return redirect('reports:employee_list')
    else:
        form = EmployeeForm()
    return render(request, 'core/employee_form.html', {'form': form})
