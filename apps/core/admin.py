"""
Core App - Admin Configuration
"""
from django.contrib import admin
from django.utils.html import format_html

from .models import AIDecisionLog, SystemSetting, VisualAuditLog


@admin.register(SystemSetting)
class SystemSettingAdmin(admin.ModelAdmin):
    list_display = ('tenant', 'company_name', 'ai_import_mode', 'ai_auto_approve_threshold', 'low_stock_alert_threshold')
    list_filter = ('ai_import_mode', 'tenant')
    search_fields = ('tenant__name', 'company_name')
    fieldsets = (
        ('Empresa', {
            'fields': ('tenant', 'company_name', 'logo_url', 'alert_email')
        }),
        ('Estoque', {
            'fields': ('low_stock_alert_threshold', 'enable_auto_cost_update')
        }),
        ('Inteligência Artificial', {
            'fields': ('ai_import_mode', 'ai_auto_approve_threshold')
        }),
    )


@admin.register(VisualAuditLog)
class VisualAuditLogAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'tenant', 'user', 'entity_type', 'action', 'source', 'external_ref')
    list_filter = ('entity_type', 'action', 'source', 'tenant', 'created_at')
    search_fields = ('user__username', 'entity_id', 'external_ref')
    date_hierarchy = 'created_at'
    readonly_fields = ('created_at', 'tenant', 'user', 'entity_type', 'entity_id',
                       'action', 'source', 'before_state', 'after_state', 'diff', 'external_ref')
    ordering = ('-created_at',)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False  # Log imutável


@admin.register(AIDecisionLog)
class AIDecisionLogAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'tenant', 'feature', 'provider', 'model_name', 'confidence_score')
    list_filter = ('feature', 'provider', 'tenant', 'created_at')
    search_fields = ('feature', 'provider', 'prompt_text')
    date_hierarchy = 'created_at'
    readonly_fields = ('created_at', 'tenant', 'feature', 'provider', 'model_name',
                       'prompt_text', 'response_json', 'confidence_score')
    ordering = ('-created_at',)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
