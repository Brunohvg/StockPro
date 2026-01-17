"""
Partners App - Admin Configuration
"""
from django.contrib import admin
from .models import Supplier, SupplierProductMap


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ['display_name', 'formatted_cnpj', 'city', 'state', 'is_active', 'created_at']
    list_filter = ['is_active', 'state', 'tenant']
    search_fields = ['company_name', 'trade_name', 'cnpj']
    ordering = ['trade_name', 'company_name']
    
    fieldsets = (
        ('Identificação', {
            'fields': ('cnpj', 'company_name', 'trade_name', 'state_registration')
        }),
        ('Contato', {
            'fields': ('email', 'phone', 'contact_name')
        }),
        ('Condições Comerciais', {
            'fields': ('payment_terms', 'lead_time_days', 'minimum_order')
        }),
        ('Endereço', {
            'fields': ('address', 'city', 'state', 'zip_code'),
            'classes': ('collapse',)
        }),
        ('Outros', {
            'fields': ('notes', 'is_active', 'tenant'),
            'classes': ('collapse',)
        }),
    )


@admin.register(SupplierProductMap)
class SupplierProductMapAdmin(admin.ModelAdmin):
    list_display = ['supplier_sku', 'supplier', 'product', 'variant', 'last_cost', 'last_purchase']
    list_filter = ['supplier', 'is_active', 'tenant']
    search_fields = ['supplier_sku', 'supplier_ean', 'supplier_name', 'product__name']
    raw_id_fields = ['supplier', 'product', 'variant']
    ordering = ['-last_purchase']
