from django import forms
from .models import Product


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ['sku', 'name', 'description', 'category', 'brand', 'uom', 'minimum_stock', 'avg_unit_cost', 'is_active']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
        }
