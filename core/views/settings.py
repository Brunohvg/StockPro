"""
System Settings view
"""
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages

from ..models import SystemSetting
from ..forms import SystemSettingForm


@login_required
def system_settings(request):
    """Global system configuration"""
    tenant = request.tenant
    settings_obj = SystemSetting.get_settings(tenant)

    if request.method == 'POST':
        form = SystemSettingForm(request.POST, instance=settings_obj)
        if form.is_valid():
            form.save()
            messages.success(request, "Configurações globais atualizadas.")
            return redirect('system_settings')
    else:
        form = SystemSettingForm(instance=settings_obj)

    return render(request, 'core/settings_form.html', {'form': form, 'settings': settings_obj})
