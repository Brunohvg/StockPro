"""
Core App Views - System settings
"""
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages

from .models import SystemSetting
from .forms import SystemSettingForm, EmployeeForm


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
            messages.success(request, f"Funcionário '{user.username}' criado!")
            return redirect('reports:employee_list')
    else:
        form = EmployeeForm()
    return render(request, 'core/employee_form.html', {'form': form})
