from rest_framework import serializers

from apps.core.api.views import TenantSerializerMixin

from .models import Brand, Category, Product, ProductVariant


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ['id', 'name', 'slug']

class BrandSerializer(serializers.ModelSerializer):
    class Meta:
        model = Brand
        fields = ['id', 'name']

def _request_tenant(serializer):
    request = serializer.context.get('request')
    return getattr(request, 'tenant', None) if request else None


class ProductVariantSerializer(TenantSerializerMixin, serializers.ModelSerializer):
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.none(), required=False)

    class Meta:
        model = ProductVariant
        fields = [
            'id', 'product', 'sku', 'name', 'barcode', 'current_stock',
            'minimum_stock', 'avg_unit_cost', 'external_id',
            'external_platform', 'is_active'
        ]
        read_only_fields = ['current_stock', 'avg_unit_cost']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'product' in self.fields:
            self.fields['product'].queryset = Product.objects.filter(tenant=_request_tenant(self))

    def validate(self, attrs):
        if self.instance is None and not attrs.get('product'):
            raise serializers.ValidationError({'product': 'Informe o produto pai (id).'})
        product = attrs.get('product')
        if self.instance is not None and product and product != self.instance.product:
            raise serializers.ValidationError({'product': 'Não é possível mover a variação para outro produto.'})
        if self.instance is None and product and product.is_simple:
            raise serializers.ValidationError({'product': 'Produto simples já tem sua variação; use um produto VARIABLE.'})
        return attrs

    def validate_sku(self, value):
        if not value:
            return value
        qs = ProductVariant.objects.filter(tenant=_request_tenant(self), sku__iexact=value)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        product_qs = Product.objects.filter(tenant=_request_tenant(self), sku__iexact=value)
        if self.instance is not None and self.instance.product.is_simple:
            product_qs = product_qs.exclude(pk=self.instance.product_id)
        if qs.exists() or product_qs.exists():
            raise serializers.ValidationError('Já existe um produto ou variação com este SKU.')
        return value

class ProductSerializer(TenantSerializerMixin, serializers.ModelSerializer):
    variants = ProductVariantSerializer(many=True, read_only=True)
    category_name = serializers.ReadOnlyField(source='category.name')
    brand_name = serializers.ReadOnlyField(source='brand.name')

    class Meta:
        model = Product
        fields = [
            'id', 'sku', 'name', 'product_type', 'description',
            'category', 'category_name', 'brand', 'brand_name',
            'barcode', 'current_stock', 'minimum_stock',
            'avg_unit_cost', 'external_id', 'external_platform',
            'is_active', 'variants'
        ]
        read_only_fields = ['current_stock', 'avg_unit_cost']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        tenant = _request_tenant(self)
        # Impede vincular categoria/marca de outra empresa
        self.fields['category'].queryset = Category.objects.filter(tenant=tenant)
        self.fields['brand'].queryset = Brand.objects.filter(tenant=tenant)

    def validate_sku(self, value):
        if not value:
            return value
        tenant = _request_tenant(self)
        qs = Product.objects.filter(tenant=tenant, sku__iexact=value)
        vqs = ProductVariant.objects.filter(tenant=tenant, sku__iexact=value)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
            vqs = vqs.exclude(product=self.instance)
        if qs.exists() or vqs.exists():
            raise serializers.ValidationError('Já existe um produto ou variação com este SKU.')
        return value


class StagingItemSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    source = serializers.CharField(read_only=True)
    supplier_sku = serializers.CharField(read_only=True)
    description = serializers.CharField(read_only=True)
    ean = serializers.CharField(read_only=True, allow_null=True)
    quantity = serializers.DecimalField(max_digits=12, decimal_places=4, read_only=True)
    unit_cost = serializers.DecimalField(max_digits=12, decimal_places=4, read_only=True)
    status = serializers.CharField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    matched_product = serializers.PrimaryKeyRelatedField(read_only=True)


class StagingSubmissionSerializer(serializers.Serializer):
    sku = serializers.CharField(max_length=100, required=False, default='N/A')
    name = serializers.CharField(max_length=255)
    barcode = serializers.CharField(max_length=20, required=False, allow_blank=True, allow_null=True)
    description = serializers.CharField(required=False, allow_blank=True, default='')
    avg_unit_cost = serializers.DecimalField(max_digits=12, decimal_places=4, min_value=0, required=False, default=0)
