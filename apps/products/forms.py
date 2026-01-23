from django import forms

from apps.inventory.models import Location
from apps.partners.models import Supplier

from .models import (
    AttributeType,
    Brand,
    Category,
    Product,
    ProductType,
    ProductVariant,
    VariantAttributeValue,
)


class ProductForm(forms.ModelForm):
    """Formulário para criação/edição de Produto Base com Multi-tenancy"""
    class Meta:
        model = Product
        fields = [
            'name', 'product_type', 'sku', 'barcode', 'photo',
            'description', 'category', 'brand', 'default_supplier', 'default_location', 'uom',
            'current_stock', 'minimum_stock', 'avg_unit_cost', 'is_active'
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-900 focus:ring-4 focus:ring-indigo-500/10 focus:border-indigo-500 transition-all font-bold'}),
            'sku': forms.TextInput(attrs={'class': 'w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-900 focus:ring-4 focus:ring-indigo-500/10 focus:border-indigo-500 transition-all font-mono'}),
            'barcode': forms.TextInput(attrs={'class': 'w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-900 focus:ring-4 focus:ring-indigo-500/10 focus:border-indigo-500 transition-all'}),
            'category': forms.Select(attrs={'class': 'w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-900 focus:ring-4 focus:ring-indigo-500/10 focus:border-indigo-500 transition-all font-bold'}),
            'brand': forms.Select(attrs={'class': 'w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-900 focus:ring-4 focus:ring-indigo-500/10 focus:border-indigo-500 transition-all font-bold'}),
            'default_supplier': forms.Select(attrs={'class': 'w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-900 focus:ring-4 focus:ring-indigo-500/10 focus:border-indigo-500 transition-all font-bold'}),
            'default_location': forms.Select(attrs={'class': 'w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-900 focus:ring-4 focus:ring-indigo-500/10 focus:border-indigo-500 transition-all font-bold'}),
            'description': forms.Textarea(attrs={'class': 'w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-900 focus:ring-4 focus:ring-indigo-500/10 focus:border-indigo-500 transition-all', 'rows': 3}),
            'uom': forms.TextInput(attrs={'class': 'w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-900 focus:ring-4 focus:ring-indigo-500/10 focus:border-indigo-500 transition-all font-bold'}),
            'current_stock': forms.NumberInput(attrs={'class': 'w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-900 focus:ring-4 focus:ring-indigo-500/10 focus:border-indigo-500 transition-all font-black'}),
            'minimum_stock': forms.NumberInput(attrs={'class': 'w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-900 focus:ring-4 focus:ring-indigo-500/10 focus:border-indigo-500 transition-all font-black'}),
            'avg_unit_cost': forms.NumberInput(attrs={'class': 'w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-900 focus:ring-4 focus:ring-indigo-500/10 focus:border-indigo-500 transition-all font-black'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'w-4 h-4 text-indigo-600 bg-white border-slate-300 rounded focus:ring-indigo-500'}),
            'product_type': forms.RadioSelect(attrs={'class': 'flex gap-4'}),
        }

    def __init__(self, *args, **kwargs):
        self.tenant = kwargs.pop('tenant', None)
        super().__init__(*args, **kwargs)
        self.fields['sku'].required = False
        self.fields['barcode'].required = False

        if self.tenant:
            self.fields['category'].queryset = Category.objects.filter(tenant=self.tenant)
            self.fields['brand'].queryset = Brand.objects.filter(tenant=self.tenant)
            self.fields['default_supplier'].queryset = Supplier.objects.filter(tenant=self.tenant)
            self.fields['default_location'].queryset = Location.objects.filter(tenant=self.tenant)

        # Se for VARIABLE, esconde campos de estoque (serão das variantes)
        instance = kwargs.get('instance')
        if instance and instance.product_type == ProductType.VARIABLE:
            for field in ['current_stock', 'minimum_stock', 'barcode']:
                if field in self.fields:
                    self.fields[field].widget = forms.HiddenInput()


    def clean(self):
        cleaned_data = super().clean()
        sku = cleaned_data.get('sku')
        barcode = cleaned_data.get('barcode')

        if sku and self.tenant:
            qs = Product.objects.filter(tenant=self.tenant, sku=sku)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError(f"Já existe um produto com o SKU '{sku}'.")

        if barcode and self.tenant:
            qs = Product.objects.filter(tenant=self.tenant, barcode=barcode)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                qs_variant = ProductVariant.objects.filter(tenant=self.tenant, barcode=barcode)
                if qs.exists() or qs_variant.exists():
                    raise forms.ValidationError(f"Já existe um produto ou variação com o código de barras '{barcode}'.")

        return cleaned_data


class ProductVariantForm(forms.ModelForm):
    """Formulário para criação/edição de Variação"""
    def __init__(self, *args, **kwargs):
        self.tenant = kwargs.pop('tenant', None)
        super().__init__(*args, **kwargs)
        self.fields['sku'].required = False
        self.fields['name'].required = False

    def clean(self):
        cleaned_data = super().clean()
        sku = cleaned_data.get('sku')
        barcode = cleaned_data.get('barcode')

        if sku and self.tenant:
            qs = ProductVariant.objects.filter(tenant=self.tenant, sku=sku)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError(f"Já existe uma variação com o SKU '{sku}'.")

            # Também verifica no produto base para evitar confusão
            if Product.objects.filter(tenant=self.tenant, sku=sku).exists():
                raise forms.ValidationError(f"O SKU '{sku}' já está sendo usado por um produto base.")

        if barcode and self.tenant:
            qs = ProductVariant.objects.filter(tenant=self.tenant, barcode=barcode)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists() or Product.objects.filter(tenant=self.tenant, barcode=barcode).exists():
                raise forms.ValidationError(f"Já existe um produto ou variação com o código de barras '{barcode}'.")

        return cleaned_data

    class Meta:
        model = ProductVariant
        fields = [
            'sku', 'name', 'barcode', 'photo',
            'current_stock', 'minimum_stock', 'avg_unit_cost', 'is_active'
        ]
        widgets = {
            'sku': forms.TextInput(attrs={'class': 'w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-900 transition-all font-mono'}),
            'name': forms.TextInput(attrs={'class': 'w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-900 transition-all font-bold'}),
            'barcode': forms.TextInput(attrs={'class': 'w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-900 transition-all'}),
            'current_stock': forms.NumberInput(attrs={'class': 'w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-900 transition-all font-black'}),
            'minimum_stock': forms.NumberInput(attrs={'class': 'w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-900 transition-all font-black'}),
            'avg_unit_cost': forms.NumberInput(attrs={'class': 'w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-900 transition-all font-black'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'w-4 h-4 text-indigo-600 bg-white border-slate-300 rounded focus:ring-indigo-500'}),
        }


class VariantAttributeValueForm(forms.ModelForm):
    """Formulário para atribuir valor de atributo a uma variação"""
    class Meta:
        model = VariantAttributeValue
        fields = ['attribute_type', 'value']
        widgets = {
            'attribute_type': forms.Select(attrs={'class': 'w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-900 font-bold'}),
            'value': forms.TextInput(attrs={'class': 'w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-900 font-bold'}),
        }


class QuickVariantForm(forms.Form):
    """Formulário rápido para criar variação com atributos inline"""
    sku = forms.CharField(max_length=50, required=False, label="SKU", widget=forms.TextInput(attrs={'class': 'w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl'}))
    barcode = forms.CharField(max_length=100, required=False, label="Código de Barras", widget=forms.TextInput(attrs={'class': 'w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl'}))
    initial_stock = forms.IntegerField(min_value=0, initial=0, label="Estoque Inicial", widget=forms.NumberInput(attrs={'class': 'w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl'}))
    cost = forms.DecimalField(max_digits=12, decimal_places=2, required=False, label="Custo", widget=forms.NumberInput(attrs={'class': 'w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl'}))

    def __init__(self, *args, attribute_types=None, **kwargs):
        super().__init__(*args, **kwargs)
        if attribute_types:
            for attr in attribute_types:
                self.fields[f'attr_{attr.id}'] = forms.CharField(
                    max_length=100,
                    required=False,
                    label=attr.name,
                    widget=forms.TextInput(attrs={'class': 'w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl', 'placeholder': f'Valor para {attr.name}'})
                )


class AttributeTypeForm(forms.ModelForm):
    """Formulário para criar tipo de atributo"""
    def __init__(self, *args, **kwargs):
        self.tenant = kwargs.pop('tenant', None)
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        name = cleaned_data.get('name')
        if name and self.tenant:
            qs = AttributeType.objects.filter(tenant=self.tenant, name=name)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError(f"O atributo '{name}' já existe.")
        return cleaned_data

    class Meta:
        model = AttributeType
        fields = ['name']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-900 font-black', 'placeholder': 'Ex: Cor, Tamanho, Voltagem...'}),
        }
