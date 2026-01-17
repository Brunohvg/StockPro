from django.contrib import admin
from .models import Plan, Tenant

@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ('display_name', 'name', 'price', 'max_products', 'max_users', 'has_ai_matching')
    search_fields = ('name', 'display_name')
    list_filter = ('has_ai_matching', 'has_ai_reconciliation')

@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ('name', 'plan', 'subscription_status', 'is_active', 'trial_ends_at', 'created_at')
    list_filter = ('subscription_status', 'is_active', 'plan')
    search_fields = ('name', 'cnpj', 'slug')
    list_editable = ('is_active', 'subscription_status', 'plan')
    prepopulated_fields = {'slug': ('name',)}
