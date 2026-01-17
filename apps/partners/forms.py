from django import forms
from .models import Supplier

class SupplierForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        self.tenant = kwargs.pop('tenant', None)
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        cnpj = cleaned_data.get('cnpj')

        if cnpj and self.tenant:
            # Normaliza CNPJ (remove formatação)
            import re
            cnpj_clean = re.sub(r'[^0-9]', '', cnpj)

            # Verifica se já existe fornecedor com este CNPJ para este tenant
            qs = Supplier.objects.filter(tenant=self.tenant, cnpj=cnpj_clean)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)

            if qs.exists():
                raise forms.ValidationError(
                    f"Já existe um fornecedor cadastrado com o CNPJ {cnpj}."
                )
        return cleaned_data

    class Meta:
        model = Supplier
        fields = [
            'company_name', 'trade_name', 'cnpj', 'state_registration',
            'email', 'phone', 'contact_name',
            'zip_code', 'address', 'city', 'state',
            'payment_terms', 'lead_time_days', 'minimum_order', 'notes',
            'is_active'
        ]
        widgets = {
            'company_name': forms.TextInput(attrs={'class': 'w-full px-4 py-4 bg-slate-50 border-2 border-transparent rounded-2xl text-sm font-bold focus:bg-white focus:border-indigo-600 transition-all outline-none'}),
            'trade_name': forms.TextInput(attrs={'class': 'w-full px-4 py-4 bg-slate-50 border-2 border-transparent rounded-2xl text-sm font-bold focus:bg-white focus:border-indigo-600 transition-all outline-none'}),
            'cnpj': forms.TextInput(attrs={'class': 'w-full px-4 py-4 bg-slate-50 border-2 border-transparent rounded-2xl text-sm font-bold focus:bg-white focus:border-indigo-600 transition-all outline-none', 'placeholder': '00.000.000/0000-00'}),
            'state_registration': forms.TextInput(attrs={'class': 'w-full px-4 py-4 bg-slate-50 border-2 border-transparent rounded-2xl text-sm font-bold focus:bg-white focus:border-indigo-600 transition-all outline-none'}),

            'email': forms.EmailInput(attrs={'class': 'w-full px-4 py-4 bg-slate-50 border-2 border-transparent rounded-2xl text-sm font-bold focus:bg-white focus:border-indigo-600 transition-all outline-none'}),
            'phone': forms.TextInput(attrs={'class': 'w-full px-4 py-4 bg-slate-50 border-2 border-transparent rounded-2xl text-sm font-bold focus:bg-white focus:border-indigo-600 transition-all outline-none'}),
            'contact_name': forms.TextInput(attrs={'class': 'w-full px-4 py-4 bg-slate-50 border-2 border-transparent rounded-2xl text-sm font-bold focus:bg-white focus:border-indigo-600 transition-all outline-none'}),

            'zip_code': forms.TextInput(attrs={'class': 'w-full px-4 py-4 bg-slate-50 border-2 border-transparent rounded-2xl text-sm font-bold focus:bg-white focus:border-indigo-600 transition-all outline-none', 'placeholder': '00000-000'}),
            'address': forms.TextInput(attrs={'class': 'w-full px-4 py-4 bg-slate-50 border-2 border-transparent rounded-2xl text-sm font-bold focus:bg-white focus:border-indigo-600 transition-all outline-none'}),
            'city': forms.TextInput(attrs={'class': 'w-full px-4 py-4 bg-slate-50 border-2 border-transparent rounded-2xl text-sm font-bold focus:bg-white focus:border-indigo-600 transition-all outline-none'}),
            'state': forms.TextInput(attrs={'class': 'w-full px-4 py-4 bg-slate-50 border-2 border-transparent rounded-2xl text-sm font-bold focus:bg-white focus:border-indigo-600 transition-all outline-none'}),

            'payment_terms': forms.TextInput(attrs={'class': 'w-full px-4 py-4 bg-slate-50 border-2 border-transparent rounded-2xl text-sm font-bold focus:bg-white focus:border-indigo-600 transition-all outline-none'}),
            'lead_time_days': forms.NumberInput(attrs={'class': 'w-full px-4 py-4 bg-slate-50 border-2 border-transparent rounded-2xl text-sm font-bold focus:bg-white focus:border-indigo-600 transition-all outline-none'}),
            'minimum_order': forms.NumberInput(attrs={'class': 'w-full px-4 py-4 bg-slate-50 border-2 border-transparent rounded-2xl text-sm font-bold focus:bg-white focus:border-indigo-600 transition-all outline-none'}),
            'notes': forms.Textarea(attrs={'class': 'w-full px-4 py-4 bg-slate-50 border-2 border-transparent rounded-2xl text-sm font-bold focus:bg-white focus:border-indigo-600 transition-all outline-none', 'rows': 3}),

            'is_active': forms.CheckboxInput(attrs={'class': 'w-5 h-5 text-indigo-600 bg-white border-slate-300 rounded-lg focus:ring-indigo-600 transition-all'}),
        }
