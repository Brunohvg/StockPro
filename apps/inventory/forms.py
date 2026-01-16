from django import forms
from .models import ImportBatch


class ImportBatchForm(forms.ModelForm):
    class Meta:
        model = ImportBatch
        fields = ['type', 'file']
