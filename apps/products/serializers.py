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

class ProductVariantSerializer(TenantSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = ProductVariant
        fields = [
            'id', 'sku', 'name', 'barcode', 'current_stock',
            'minimum_stock', 'avg_unit_cost', 'external_id',
            'external_platform', 'is_active'
        ]
        read_only_fields = ['current_stock']

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
        read_only_fields = ['current_stock']
