"""
Inventory App - Admin Configuration (V2)
"""
from django.contrib import admin
from django.utils.html import format_html

from .models import ImportBatch, ImportLog, StockMovement


# Tenta importar modelos V2 (podem não existir ainda se migrations não rodaram)
try:
    from .models_v2 import Location, AdjustmentReason, PendingAssociation
    V2_AVAILABLE = True
except ImportError:
    V2_AVAILABLE = False


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = [
        'created_at', 'type', 'target_display', 'quantity', 
        'balance_after', 'user', 'source'
    ]
    list_filter = ['type', 'source', 'created_at', 'tenant']
    search_fields = ['product__name', 'product__sku', 'variant__sku', 'reason']
    date_hierarchy = 'created_at'
    readonly_fields = [
        'id', 'created_at', 'balance_after', 'product', 'variant',
        'user', 'tenant'
    ]
    raw_id_fields = ['product', 'variant']
    ordering = ['-created_at']
    
    def target_display(self, obj):
        if obj.variant:
            return f'{obj.variant.sku}'
        return obj.product.sku if obj.product else '-'
    target_display.short_description = 'Produto/SKU'


@admin.register(ImportBatch)
class ImportBatchAdmin(admin.ModelAdmin):
    list_display = [
        'created_at', 'type', 'status', 'progress_display', 
        'success_count', 'error_count', 'user'
    ]
    list_filter = ['type', 'status', 'created_at', 'tenant']
    search_fields = ['log']
    date_hierarchy = 'created_at'
    readonly_fields = ['id', 'created_at', 'completed_at', 'total_rows', 'processed_rows']
    
    def progress_display(self, obj):
        pct = obj.progress_percent
        color = 'green' if pct == 100 else 'orange' if pct > 50 else 'red'
        return format_html(
            '<span style="color: {};">{}/{} ({}%)</span>',
            color, obj.processed_rows, obj.total_rows, pct
        )
    progress_display.short_description = 'Progresso'


@admin.register(ImportLog)
class ImportLogAdmin(admin.ModelAdmin):
    list_display = ['created_at', 'batch', 'row_number', 'status', 'message_preview']
    list_filter = ['status', 'created_at']
    search_fields = ['idempotency_key', 'message']
    raw_id_fields = ['batch']
    
    def message_preview(self, obj):
        if obj.message:
            return obj.message[:100] + '...' if len(obj.message) > 100 else obj.message
        return '-'
    message_preview.short_description = 'Mensagem'


# Registra modelos V2 se disponíveis
if V2_AVAILABLE:
    @admin.register(Location)
    class LocationAdmin(admin.ModelAdmin):
        list_display = ['code', 'name', 'location_type', 'parent', 'is_default', 'is_active']
        list_filter = ['location_type', 'is_active', 'is_default', 'tenant']
        search_fields = ['code', 'name']
        ordering = ['name']
        list_editable = ['is_active', 'is_default']
        
        fieldsets = (
            ('Identificação', {
                'fields': ('tenant', 'code', 'name', 'location_type')
            }),
            ('Hierarquia', {
                'fields': ('parent',),
                'classes': ('collapse',)
            }),
            ('Configurações', {
                'fields': ('is_active', 'is_default', 'allows_negative')
            }),
            ('Endereço', {
                'fields': ('address',),
                'classes': ('collapse',)
            }),
        )

    @admin.register(AdjustmentReason)
    class AdjustmentReasonAdmin(admin.ModelAdmin):
        list_display = ['code', 'name', 'impact_type', 'requires_note', 'is_active']
        list_filter = ['impact_type', 'is_active', 'tenant']
        search_fields = ['code', 'name']
        ordering = ['name']
        list_editable = ['is_active']

    @admin.register(PendingAssociation)
    class PendingAssociationAdmin(admin.ModelAdmin):
        list_display = [
            'supplier_sku', 'supplier_name', 'supplier', 
            'quantity', 'unit_cost', 'status', 'created_at'
        ]
        list_filter = ['status', 'supplier', 'created_at', 'tenant']
        search_fields = ['supplier_sku', 'supplier_ean', 'supplier_name']
        date_hierarchy = 'created_at'
        raw_id_fields = ['import_batch', 'supplier', 'resolved_product', 'resolved_variant']
        readonly_fields = ['id', 'created_at', 'resolved_at']
        
        def has_add_permission(self, request):
            return False  # Não permite adicionar manualmente
