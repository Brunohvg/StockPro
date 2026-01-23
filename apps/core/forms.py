from django import forms
from django.contrib.auth.models import User

from .models import SystemSetting


class SystemSettingForm(forms.ModelForm):
    class Meta:
        model = SystemSetting
        fields = ['company_name', 'logo_url', 'alert_email', 'low_stock_alert_threshold', 'enable_auto_cost_update']


class EmployeeForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput)

    class Meta:
        model = User
        fields = ['username', 'email', 'first_name', 'last_name', 'password']
