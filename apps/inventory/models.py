"""
Inventory App - Stock Movements and Import Management (Normalized V3)
"""
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.products.models import Product, ProductVariant
from apps.tenants.models import TenantMixin

# ==========================================
# 1. Choices & Enums
# ==========================================

class LocationType(models.TextChoices):
    STORE = 'STORE', 'Loja'
    WAREHOUSE = 'WAREHOUSE', 'Depósito'
    SHELF = 'SHELF', 'Prateleira'
    DISPLAY = 'DISPLAY', 'Expositor'
    TRANSIT = 'TRANSIT', 'Em Trânsito'
    QUARANTINE = 'QUARANTINE', 'Quarentena'

class MovementType(models.TextChoices):
    IN = 'IN', 'Entrada'
    OUT = 'OUT', 'Saída'
    ADJ = 'ADJ', 'Ajuste'

class ImportStatus(models.TextChoices):
    PENDING = 'PENDING', 'Pendente'
    PROCESSING = 'PROCESSING', 'Processando'
    PENDING_REVIEW = 'PENDING_REVIEW', 'Aguardando Revisão'
    COMPLETED = 'COMPLETED', 'Concluído'
    FAILED = 'FAILED', 'Falha'

class PendingAssociationStatus(models.TextChoices):
    PENDING = 'PENDING', 'Aguardando'
    LINKED = 'LINKED', 'Vinculado a Existente'
    CREATED = 'CREATED', 'Produto Criado'
    IGNORED = 'IGNORED', 'Ignorado'

# ==========================================
# 2. Base Models
# ==========================================

class Location(TenantMixin):
    """Physical storage location (Warehouse, Store, Shelf, etc.)"""
    code = models.CharField(max_length=20, verbose_name='Código', help_text='Ex: LOJ-001')
    name = models.CharField(max_length=100, verbose_name='Nome')
    location_type = models.CharField(max_length=20, choices=LocationType.choices, default=LocationType.STORE)
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='children')
    address = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False, help_text='Local padrão para recebimento')
    allows_negative = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Localização'
        verbose_name_plural = 'Localizações'
        unique_together = ['tenant', 'code']
        ordering = ['name']

    def __str__(self):
        return f'{self.parent.name} > {self.name}' if self.parent else self.name

    def save(self, *args, **kwargs):
        if self.is_default:
            Location.objects.filter(tenant=self.tenant, is_default=True).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)

    @classmethod
    def get_default_for_tenant(cls, tenant):
        return cls.objects.filter(tenant=tenant, is_active=True, is_default=True).first()

class StockMovement(TenantMixin):
    """Immutable record of any stock change"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='movements', null=True, blank=True, verbose_name="Produto (Opcional)")
    variant = models.ForeignKey(ProductVariant, on_delete=models.PROTECT, related_name='movements', verbose_name="Variante/SKU")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name='movements', null=True, blank=True)
    type = models.CharField(max_length=3, choices=MovementType.choices)
    quantity = models.DecimalField(max_digits=12, decimal_places=4)
    balance_after = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    reason = models.CharField(max_length=255, blank=True)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    source = models.CharField(max_length=50, blank=True, default='MANUAL')
    source_doc = models.CharField(max_length=100, blank=True, null=True)
    external_order = models.ForeignKey('ExternalOrder', on_delete=models.SET_NULL, null=True, blank=True, related_name='movements')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Movimentação"
        verbose_name_plural = "Movimentações"

    def clean(self):
        if not self.variant_id:
            raise ValidationError("Toda movimentação deve estar vinculada a uma variante (SKU).")
        if self.variant_id and not self.product_id:
            self.product = self.variant.product

    def __str__(self):
        target = self.variant.sku if self.variant_id else (self.product.sku if self.product_id else "?")
        return f"{self.get_type_display()} {self.quantity}x {target}"

class StockLot(TenantMixin):
    """
    Lote de uma variação com validade (FEFO).

    Invariante: soma(quantity dos lotes) <= variant.current_stock.
    A diferença é saldo "sem lote" (estoque anterior ao controle de validade).
    Só o StockService altera quantity.
    """
    variant = models.ForeignKey(ProductVariant, on_delete=models.CASCADE, related_name='lots', verbose_name="Variação")
    lot_number = models.CharField(max_length=60, blank=True, default='', verbose_name="Lote")
    expiry_date = models.DateField(null=True, blank=True, db_index=True, verbose_name="Validade")
    manufacture_date = models.DateField(null=True, blank=True, verbose_name="Fabricação")
    quantity = models.DecimalField(max_digits=12, decimal_places=4, default=0, verbose_name="Saldo do lote")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Lote"
        verbose_name_plural = "Lotes"
        ordering = [models.F('expiry_date').asc(nulls_last=True), 'created_at']
        constraints = [
            models.CheckConstraint(check=models.Q(quantity__gte=0), name='lot_quantity_non_negative'),
            models.UniqueConstraint(
                fields=['variant', 'lot_number', 'expiry_date'], name='unique_lot_per_variant_expiry'
            ),
        ]

    def __str__(self):
        label = self.lot_number or 'sem nº'
        exp = self.expiry_date.strftime('%d/%m/%Y') if self.expiry_date else 'sem validade'
        return f"{self.variant.sku} · lote {label} · {exp}"

    @property
    def days_to_expiry(self):
        if not self.expiry_date:
            return None
        from django.utils import timezone
        return (self.expiry_date - timezone.localdate()).days

    @property
    def is_expired(self):
        d = self.days_to_expiry
        return d is not None and d < 0


class MovementLot(models.Model):
    """Quanto de cada lote uma movimentação consumiu ou criou."""
    movement = models.ForeignKey(StockMovement, on_delete=models.CASCADE, related_name='lot_allocations')
    lot = models.ForeignKey(StockLot, on_delete=models.PROTECT, related_name='allocations')
    quantity = models.DecimalField(max_digits=12, decimal_places=4)

    class Meta:
        verbose_name = "Lote da movimentação"
        verbose_name_plural = "Lotes das movimentações"


# ==========================================
# 3. Import & Intelligence Layer (V3)
# ==========================================

class ImportBatch(TenantMixin):
    """Batch import header for tracking CSV/XML files"""
    IMPORT_TYPES = [
        ('CATALOG_DIRECT', 'Criação/Update de Catálogo (Completo/CSV)'),
        ('STOCK_SYNC', 'Sincronização de Estoque (SKU Only/CSV)'),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    type = models.CharField(max_length=20, choices=IMPORT_TYPES)
    file = models.FileField(upload_to='imports/')
    status = models.CharField(max_length=20, choices=ImportStatus.choices, default=ImportStatus.PENDING)
    total_rows = models.PositiveIntegerField(default=0)
    processed_rows = models.PositiveIntegerField(default=0)
    success_count = models.PositiveIntegerField(default=0)
    error_count = models.PositiveIntegerField(default=0)
    log = models.TextField(blank=True, null=True)
    source_doc = models.CharField(max_length=100, blank=True, null=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    @property
    def progress_percent(self):
        if self.total_rows == 0:
            return 0
        return int((self.processed_rows / self.total_rows) * 100)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Lote de Importação"

    def __str__(self):
        return f"{self.get_type_display()} - {self.created_at.strftime('%d/%m/%Y')}"

class ExportBatch(TenantMixin):
    """Batch export header for tracking CSV generation jobs"""
    STATUS_CHOICES = [
        ('PENDING', 'Pendente'),
        ('PROCESSING', 'Processando'),
        ('COMPLETED', 'Concluído'),
        ('FAILED', 'Falha'),
    ]
    FORMAT_CHOICES = [
        ('CSV', 'CSV'),
        ('EXCEL', 'Excel'),
        ('JSON', 'JSON'),
    ]
    RESOURCE_CHOICES = [
        ('PRODUCTS', 'Produtos'),
        ('MOVEMENTS', 'Movimentações'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    file = models.FileField(upload_to='exports/', null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    export_type = models.CharField(max_length=10, choices=FORMAT_CHOICES, default='CSV')
    resource = models.CharField(max_length=20, choices=RESOURCE_CHOICES, default='PRODUCTS')
    params = models.TextField(blank=True, default='{}', help_text="JSON params for export filtering")
    total_rows = models.PositiveIntegerField(default=0)
    log = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Lote de Exportação"
        verbose_name_plural = "Lotes de Exportação"

    def __str__(self):
        return f"Export {self.created_at.strftime('%d/%m/%Y %H:%M')}"

class ImportLog(models.Model):
    """Detailed error logging for each row in a batch"""
    batch = models.ForeignKey(ImportBatch, on_delete=models.CASCADE, related_name='logs_legacy')
    row_number = models.PositiveIntegerField()
    status = models.CharField(max_length=20)
    message = models.TextField()
    idempotency_key = models.CharField(max_length=100, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['row_number']
        verbose_name = "Log de Importação"

class ImportItem(TenantMixin):
    """Granular record for each line in an import (The Curatorship Hub)"""
    STATUS_CHOICES = [
        ('PENDING', 'Aguardando Revisão'),
        ('PROCESSING', 'Em Processamento'),
        ('DONE', 'Processado'),
        ('REJECTED', 'Rejeitado'),
        ('ERROR', 'Erro'),
    ]
    SOURCE_CHOICES = [
        ('CSV', 'Importação CSV'),
        ('API', 'Integração API'),
        ('MANUAL', 'Manual'),
    ]
    batch = models.ForeignKey(ImportBatch, on_delete=models.CASCADE, related_name='items', null=True, blank=True)
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='CSV')
    supplier_sku = models.CharField(max_length=100, db_index=True)
    description = models.TextField()
    ean = models.CharField(max_length=20, blank=True, null=True)
    quantity = models.DecimalField(max_digits=12, decimal_places=4)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=4)
    raw_data = models.JSONField(default=dict)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    ai_suggestion = models.JSONField(null=True, blank=True)
    ai_confidence = models.DecimalField(max_digits=3, decimal_places=2, default=0)
    ai_logic_summary = models.TextField(blank=True)

    matched_product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, blank=True)
    matched_variant = models.ForeignKey(ProductVariant, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    @property
    def ai_confidence_percent(self):
        return int((self.ai_confidence or 0) * 100)

    class Meta:
        ordering = ['-ai_confidence']

class ImportKnowledge(TenantMixin):
    """Learned patterns for the Intelligence Engine"""
    pattern_type = models.CharField(max_length=30)
    pattern_value = models.CharField(max_length=255)
    supplier = models.ForeignKey('partners.Supplier', on_delete=models.SET_NULL, null=True, blank=True)
    confidence_score = models.FloatField(default=0.5)
    times_confirmed = models.PositiveIntegerField(default=0)
    last_used = models.DateTimeField(auto_now=True)

# ==========================================
# 4. Audit & Legacy
# ==========================================

class InventoryAudit(TenantMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name='audits')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    status = models.CharField(max_length=15, default='DRAFT')
    created_at = models.DateTimeField(auto_now_add=True)

class InventoryAuditItem(models.Model):
    audit = models.ForeignKey(InventoryAudit, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, null=True, blank=True)
    variant = models.ForeignKey(ProductVariant, on_delete=models.CASCADE, null=True, blank=True)
    ledger_quantity = models.DecimalField(max_digits=12, decimal_places=4)
    physical_quantity = models.DecimalField(max_digits=12, decimal_places=4)
    adjustment_quantity = models.DecimalField(max_digits=12, decimal_places=4, default=0)

# Legacy V2 models kept for migration compatibility or future structure


class ExternalOrder(TenantMixin):
    """
    Tracks orders from external platforms (Nuvemshop, Tray, etc.)
    Used for stock consumption mapping (Plan C).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    platform = models.CharField(max_length=50) # 'NUVEMSHOP', 'TRAY'
    external_order_id = models.CharField(max_length=100, db_index=True)

    total_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    status = models.CharField(max_length=50, blank=True) # 'PAID', 'SHIPPED', etc.

    customer_name = models.CharField(max_length=255, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Pedido Externo"
        verbose_name_plural = "Pedidos Externos"
        unique_together = ['tenant', 'platform', 'external_order_id']

    def __str__(self):
        return f"{self.platform} #{self.external_order_id} ({self.status})"
