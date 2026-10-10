from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.db.models import Q

from .models import SystemSetting


class SystemSettingForm(forms.ModelForm):
    class Meta:
        model = SystemSetting
        fields = ['company_name', 'logo_url', 'alert_email', 'expiry_alert_days', 'enable_auto_cost_update',
                  'low_stock_alerts_enabled', 'weekly_summary_enabled']


class EmployeeForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput)

    class Meta:
        model = User
        fields = ['username', 'email', 'first_name', 'last_name', 'password']

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip().lower()
        if not email:
            raise forms.ValidationError("E-mail é obrigatório.")
        if User.objects.filter(Q(email__iexact=email) | Q(username__iexact=email)).exists():
            raise forms.ValidationError("Já existe um usuário com este e-mail.")
        return email

    def clean_username(self):
        username = (self.cleaned_data.get('username') or '').strip()
        if '@' in username:
            raise forms.ValidationError("O nome de usuário não pode conter '@'.")
        if User.objects.filter(Q(username__iexact=username) | Q(email__iexact=username)).exists():
            raise forms.ValidationError("Este nome de usuário já está em uso.")
        return username

    def clean_password(self):
        password = self.cleaned_data.get('password')
        validate_password(password)
        return password
