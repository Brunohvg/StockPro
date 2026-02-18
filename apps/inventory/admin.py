"""
Inventory App - Admin Configuration
"""
from django.contrib import admin
from django.utils.html import format_html

from .models import (
    ExportBatch, ExternalOrder, ImportBatch, ImportItem,
    ImportKnowledge, ImportLog, InventoryAudit, InventoryAuditItem,
    Location, StockMovement,
)


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'tenant', 'type', 'variant', 'quantity', 'balance_after', 'user', 'source')
    list_filter = ('type', 'source', 'created_at', 'tenant')
    search_fields = ('variant__sku', 'product__name', 'reason')
    date_hierarchy = 'created_at'
    readonly_fields = ('id', 'created_at', 'balance_after', 'product', 'variant', 'user', 'tenant')
    raw_id_fields = ('product', 'variant', 'location', 'external_order')
    ordering = ('-created_at',)

    def has_add_permission(self, request):
        return False


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'location_type', 'tenant', 'is_default', 'is_active')
    list_filter = ('location_type', 'is_active', 'is_default', 'tenant')
    search_fields = ('code', 'name')
    list_editable = ('is_active', 'is_default')
    ordering = ('name',)


@admin.register(ImportBatch)
class ImportBatchAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'tenant', 'type', 'status', 'progress_display', 'success_count', 'error_count', 'user')
    list_filter = ('type', 'status', 'created_at', 'tenant')
    date_hierarchy = 'created_at'
    readonly_fields = ('id', 'created_at', 'completed_at', 'total_rows', 'processed_rows')

    def progress_display(self, obj):
        pct = obj.progress_percent
        color = 'green' if pct == 100 else 'orange' if pct > 50 else 'red'
        return format_html('<span style="color:{};">{}/{} ({}%)</span>', color, obj.processed_rows, obj.total_rows, pct)
    progress_display.short_description = 'Progresso'


@admin.register(ImportItem)
class ImportItemAdmin(admin.ModelAdmin):
    list_display = ('batch', 'status', 'supplier_sku', 'description', 'quantity', 'unit_cost', 'ai_confidence', 'created_at')
    list_filter = ('status', 'source', 'created_at')
    search_fields = ('supplier_sku', 'description', 'ean')
    raw_id_fields = ('batch', 'matched_product', 'matched_variant')
    readonly_fields = ('id', 'created_at', 'ai_suggestion', 'ai_confidence')

    def has_add_permission(self, request):
        return False


@admin.register(ImportLog)
class ImportLogAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'batch', 'row_number', 'status', 'message_short')
    list_filter = ('status', 'created_at')
    search_fields = ('idempotency_key', 'message')
    raw_id_fields = ('batch',)

    def message_short(self, obj):
        if obj.message:
            return obj.message[:80] + '...' if len(obj.message) > 80 else obj.message
        return '-'
    message_short.short_description = 'Mensagem'


@admin.register(ImportKnowledge)
class ImportKnowledgeAdmin(admin.ModelAdmin):
    list_display = ('tenant', 'pattern_type', 'pattern_value', 'supplier', 'confidence_score', 'times_confirmed', 'last_used')
    list_filter = ('tenant', 'pattern_type', 'supplier')
    search_fields = ('pattern_value',)
    readonly_fields = ('last_used',)
    ordering = ('-confidence_score',)


@admin.register(ExternalOrder)
class ExternalOrderAdmin(admin.ModelAdmin):
    list_display = ('external_order_id', 'platform', 'tenant', 'status', 'customer_name', 'total_amount', 'created_at')
    list_filter = ('platform', 'status', 'tenant', 'created_at')
    search_fields = ('external_order_id', 'customer_name')
    date_hierarchy = 'created_at'
    readonly_fields = ('id', 'created_at', 'updated_at')


@admin.register(ExportBatch)
class ExportBatchAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'tenant', 'export_type', 'resource', 'status', 'total_rows', 'user')
    list_filter = ('export_type', 'resource', 'status', 'tenant', 'created_at')
    date_hierarchy = 'created_at'
    readonly_fields = ('id', 'created_at', 'completed_at')


class InventoryAuditItemInline(admin.TabularInline):
    model = InventoryAuditItem
    extra = 0
    readonly_fields = ('variant', 'product', 'ledger_quantity', 'physical_quantity', 'adjustment_quantity')
    can_delete = False


@admin.register(InventoryAudit)
class InventoryAuditAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'tenant', 'location', 'status', 'user')
    list_filter = ('status', 'tenant', 'created_at')
    date_hierarchy = 'created_at'
    readonly_fields = ('id', 'created_at')
    inlines = [InventoryAuditItemInline]
