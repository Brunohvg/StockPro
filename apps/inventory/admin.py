"""
Inventory App - Admin Configuration
"""
from django.contrib import admin
from django.utils.html import format_html

from .models import (
    ExportBatch, ExternalOrder, ImportBatch, ImportItem,
    ImportKnowledge, ImportLog, InventoryAudit, InventoryAuditItem,
    Location, PendingAssociation, StockMovement,
)

try:
    from .models import AdjustmentReason
    HAS_ADJUSTMENT_REASON = True
except ImportError:
    HAS_ADJUSTMENT_REASON = False


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
        return False  # Movimentos criados apenas pela aplicação


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
    search_fields = ('error_log',)
    date_hierarchy = 'created_at'
    readonly_fields = ('id', 'created_at', 'completed_at', 'total_rows', 'processed_rows')

    def progress_display(self, obj):
        pct = obj.progress_percent
        color = 'green' if pct == 100 else 'orange' if pct > 50 else 'red'
        return format_html('<span style="color:{};">{}/{} ({}%)</span>', color, obj.processed_rows, obj.total_rows, pct)
    progress_display.short_description = 'Progresso'


@admin.register(ImportItem)
class ImportItemAdmin(admin.ModelAdmin):
    list_display = ('batch', 'status', 'supplier_sku', 'supplier_name', 'quantity', 'unit_cost', 'created_at')
    list_filter = ('status', 'batch__tenant', 'created_at')
    search_fields = ('supplier_sku', 'supplier_name', 'supplier_ean')
    raw_id_fields = ('batch', 'resolved_product', 'resolved_variant')
    readonly_fields = ('id', 'created_at')

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
    list_display = ('tenant', 'supplier_sku', 'supplier_name', 'product', 'variant', 'confidence', 'updated_at')
    list_filter = ('tenant', 'updated_at')
    search_fields = ('supplier_sku', 'supplier_name', 'supplier_ean')
    raw_id_fields = ('tenant', 'product', 'variant')
    readonly_fields = ('created_at', 'updated_at')
    ordering = ('-updated_at',)


@admin.register(PendingAssociation)
class PendingAssociationAdmin(admin.ModelAdmin):
    list_display = ('supplier_sku', 'supplier_name', 'tenant', 'quantity', 'unit_cost', 'status', 'created_at')
    list_filter = ('status', 'tenant', 'created_at')
    search_fields = ('supplier_sku', 'supplier_ean', 'supplier_name')
    date_hierarchy = 'created_at'
    raw_id_fields = ('import_batch', 'import_item', 'resolved_product', 'resolved_variant')
    readonly_fields = ('id', 'created_at', 'resolved_at')

    def has_add_permission(self, request):
        return False


@admin.register(ExternalOrder)
class ExternalOrderAdmin(admin.ModelAdmin):
    list_display = ('external_order_id', 'platform', 'tenant', 'status', 'created_at')
    list_filter = ('platform', 'status', 'tenant', 'created_at')
    search_fields = ('external_order_id',)
    date_hierarchy = 'created_at'
    readonly_fields = ('created_at', 'updated_at')


@admin.register(ExportBatch)
class ExportBatchAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'tenant', 'export_type', 'status', 'user')
    list_filter = ('export_type', 'status', 'tenant', 'created_at')
    date_hierarchy = 'created_at'
    readonly_fields = ('id', 'created_at', 'completed_at')


class InventoryAuditItemInline(admin.TabularInline):
    model = InventoryAuditItem
    extra = 0
    readonly_fields = ('variant', 'system_qty', 'counted_qty', 'difference')
    can_delete = False


@admin.register(InventoryAudit)
class InventoryAuditAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'tenant', 'location', 'status', 'user', 'completed_at')
    list_filter = ('status', 'tenant', 'created_at')
    date_hierarchy = 'created_at'
    readonly_fields = ('created_at', 'completed_at')
    inlines = [InventoryAuditItemInline]


if HAS_ADJUSTMENT_REASON:
    @admin.register(AdjustmentReason)
    class AdjustmentReasonAdmin(admin.ModelAdmin):
        list_display = ('code', 'name', 'impact_type', 'requires_note', 'is_active')
        list_filter = ('impact_type', 'is_active', 'tenant')
        search_fields = ('code', 'name')
        list_editable = ('is_active',)
