from django import forms

from .models import ImportBatch, Location


class ImportBatchForm(forms.ModelForm):
    ALLOWED_EXTENSIONS = ('.xlsx', '.xlsm', '.csv', '.txt')
    MAX_SIZE_MB = 10

    def clean_file(self):
        f = self.cleaned_data.get('file')
        if not f:
            return f
        import os
        ext = os.path.splitext(f.name)[1].lower()
        if ext not in self.ALLOWED_EXTENSIONS:
            raise forms.ValidationError("Envie uma planilha .xlsx ou .csv.")
        if f.size > self.MAX_SIZE_MB * 1024 * 1024:
            raise forms.ValidationError(f"Arquivo maior que {self.MAX_SIZE_MB} MB.")
        return f

    class Meta:
        model = ImportBatch
        fields = ['type', 'file']
        widgets = {
            'type': forms.Select(attrs={'class': 'w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-900 outline-none focus:ring-4 focus:ring-indigo-500/10 focus:border-indigo-500 transition-all font-bold'}),
            'file': forms.FileInput(attrs={'class': 'w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-900 outline-none focus:ring-4 focus:ring-indigo-500/10 focus:border-indigo-500 transition-all'}),
        }

class LocationForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        self.tenant = kwargs.pop('tenant', None)
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        code = cleaned_data.get('code')

        if code and self.tenant:
            qs = Location.objects.filter(tenant=self.tenant, code=code)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)

            if qs.exists():
                raise forms.ValidationError(f"O local com código '{code}' já existe para sua empresa.")

        return cleaned_data

    class Meta:
        model = Location
        fields = ['name', 'code', 'location_type', 'address', 'is_default', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-900 outline-none focus:ring-4 focus:ring-indigo-500/10 focus:border-indigo-500 transition-all font-black'}),
            'code': forms.TextInput(attrs={'class': 'w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-900 outline-none focus:ring-4 focus:ring-indigo-500/10 focus:border-indigo-500 transition-all font-mono font-bold'}),
            'location_type': forms.Select(attrs={'class': 'w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-900 outline-none focus:ring-4 focus:ring-indigo-500/10 focus:border-indigo-500 transition-all font-bold'}),
            'address': forms.Textarea(attrs={'class': 'w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-900 outline-none focus:ring-4 focus:ring-indigo-500/10 focus:border-indigo-500 transition-all font-medium', 'rows': 3}),
            'is_default': forms.CheckboxInput(attrs={'class': 'w-4 h-4 text-indigo-600 bg-white border-slate-300 rounded focus:ring-indigo-500'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'w-4 h-4 text-indigo-600 bg-white border-slate-300 rounded focus:ring-indigo-500'}),
        }
