from django.contrib import admin
from .models import Product, StockMovement, Category, Brand

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug')
    prepopulated_fields = {'slug': ('name',)}

@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug')
    prepopulated_fields = {'slug': ('name',)}

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('sku', 'name', 'category', 'brand', 'current_stock', 'is_active')
    search_fields = ('sku', 'name', 'category__name', 'brand__name')
    list_filter = ('category', 'brand', 'is_active')
    readonly_fields = ('current_stock',)

@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'type', 'product', 'quantity', 'balance_after', 'user')
    list_filter = ('type', 'created_at', 'user')
    search_fields = ('product__sku', 'product__name', 'reason')

    def has_add_permission(self, request):
        return False # Force usage of custom actions/forms

    def has_change_permission(self, request, obj=None):
        return False # Immutable history

    def has_delete_permission(self, request, obj=None):
        return False # Immutable history
