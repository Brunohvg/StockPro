from django import forms
from .models import Product, ProductVariant, AttributeType, VariantAttributeValue, ProductType


class ProductForm(forms.ModelForm):
    """Formulário para criação/edição de Produto Base"""
    class Meta:
        model = Product
        fields = [
            'name', 'product_type', 'sku', 'barcode', 'photo',
            'description', 'category', 'brand', 'uom',
            'current_stock', 'minimum_stock', 'avg_unit_cost', 'is_active'
        ]
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
            'product_type': forms.RadioSelect(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['sku'].required = False
        self.fields['barcode'].required = False

        # Se for VARIABLE, esconde campos de estoque (serão das variantes)
        instance = kwargs.get('instance')
        if instance and instance.product_type == ProductType.VARIABLE:
            for field in ['current_stock', 'minimum_stock', 'barcode']:
                self.fields[field].widget = forms.HiddenInput()


class ProductVariantForm(forms.ModelForm):
    """Formulário para criação/edição de Variação"""
    class Meta:
        model = ProductVariant
        fields = [
            'sku', 'name', 'barcode', 'photo',
            'current_stock', 'minimum_stock', 'avg_unit_cost', 'is_active'
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['sku'].required = False
        self.fields['name'].required = False


class VariantAttributeValueForm(forms.ModelForm):
    """Formulário para atribuir valor de atributo a uma variação"""
    class Meta:
        model = VariantAttributeValue
        fields = ['attribute_type', 'value']


class QuickVariantForm(forms.Form):
    """Formulário rápido para criar variação com atributos inline"""
    sku = forms.CharField(max_length=50, required=False, label="SKU")
    barcode = forms.CharField(max_length=100, required=False, label="Código de Barras")
    initial_stock = forms.IntegerField(min_value=0, initial=0, label="Estoque Inicial")
    cost = forms.DecimalField(max_digits=12, decimal_places=2, required=False, label="Custo")

    # Campos dinâmicos de atributos serão adicionados via __init__
    def __init__(self, *args, attribute_types=None, **kwargs):
        super().__init__(*args, **kwargs)
        if attribute_types:
            for attr in attribute_types:
                self.fields[f'attr_{attr.id}'] = forms.CharField(
                    max_length=100,
                    required=False,
                    label=attr.name
                )


class AttributeTypeForm(forms.ModelForm):
    """Formulário para criar tipo de atributo"""
    class Meta:
        model = AttributeType
        fields = ['name']
