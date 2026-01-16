from django import forms
from django.contrib.auth.models import User
from .models import Product, StockMovement, ImportBatch, SystemSetting


class ModernInput(forms.TextInput):
    template_name = 'core/widgets/modern_input.html'

class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ['sku', 'name', 'category', 'brand', 'uom', 'minimum_stock', 'avg_unit_cost', 'is_active']
        widgets = {
            'sku': forms.TextInput(attrs={'placeholder': 'Ex: SKU-001'}),
            'name': forms.TextInput(attrs={'placeholder': 'Nome descritivo'}),
            'uom': forms.TextInput(attrs={'placeholder': 'UN, KG, LT...'}),
            'minimum_stock': forms.NumberInput(attrs={'placeholder': '0'}),
            'avg_unit_cost': forms.NumberInput(attrs={'placeholder': '0.00', 'step': '0.01'}),
        }

class ImportBatchForm(forms.ModelForm):
    class Meta:
        model = ImportBatch
        fields = ['file', 'type']
        widgets = {
            'file': forms.FileInput(attrs={'class': 'block w-full text-sm text-gray-500 file:mr-4 file:py-2 file:px-4 file:rounded-full file:border-0 file:text-sm file:font-semibold file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100'}),
            'type': forms.Select(attrs={'class': 'block w-full rounded-md border-0 py-1.5 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 focus:ring-2 focus:ring-inset focus:ring-blue-600 sm:text-sm sm:leading-6'}),
        }

class EmployeeForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'peer block w-full rounded-md border-0 py-1.5 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 placeholder:text-gray-400 focus:ring-2 focus:ring-inset focus:ring-blue-600 sm:text-sm sm:leading-6 pl-10', 'placeholder': '••••••••'}), required=True)

    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email', 'password', 'is_staff']
        widgets = {
            'username': forms.TextInput(attrs={'placeholder': 'Nome de Usuário'}),
            'password': forms.PasswordInput(attrs={'placeholder': 'Senha'}),
            'first_name': forms.TextInput(attrs={'placeholder': 'Primeiro Nome'}),
            'last_name': forms.TextInput(attrs={'placeholder': 'Sobrenome'}),
            'email': forms.EmailInput(attrs={'placeholder': 'email@exemplo.com'}),
        }

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password"])
        if commit:
            user.save()
        return user

class SystemSettingForm(forms.ModelForm):
    class Meta:
        model = SystemSetting
        fields = ['company_name', 'company_logo_url', 'prevent_negative_stock', 'low_stock_threshold_global', 'enable_notifications']
        widgets = {
            'company_name': forms.TextInput(attrs={'placeholder': 'Ex: StockPro enterprise'}),
            'company_logo_url': forms.URLInput(attrs={'placeholder': 'https://...'}),
        }
