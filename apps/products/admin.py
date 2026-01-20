from django.contrib import admin

from .models import Product, ProductVariant, Category, Brand, AttributeType

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ['sku', 'name', 'product_type', 'current_stock', 'requires_review', 'ai_confidence', 'is_active']
    readonly_fields = ['current_stock']
    search_fields = ['sku', 'name']
    list_filter = ['product_type', 'category', 'requires_review', 'is_active']

@admin.register(ProductVariant)
class ProductVariantAdmin(admin.ModelAdmin):
    list_display = ['sku', 'product', 'current_stock', 'requires_review', 'ai_confidence', 'is_active']
    readonly_fields = ['current_stock']
    search_fields = ['sku', 'name']
    list_filter = ['requires_review', 'is_active']

admin.site.register(Category)
admin.site.register(Brand)
admin.site.register(AttributeType)
