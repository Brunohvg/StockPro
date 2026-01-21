"""
Inventory App - Stock Movements and Import Management (Normalized V3)
"""
import uuid
from decimal import Decimal
from typing import Optional
from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone
from apps.tenants.models import TenantMixin
from apps.products.models import Product, ProductVariant

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
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='movements', null=True, blank=True)
    variant = models.ForeignKey(ProductVariant, on_delete=models.PROTECT, related_name='movements', null=True, blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name='movements', null=True, blank=True)
    type = models.CharField(max_length=3, choices=MovementType.choices)
    quantity = models.DecimalField(max_digits=12, decimal_places=4)
    balance_after = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    reason = models.CharField(max_length=255, blank=True)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    source = models.CharField(max_length=50, blank=True, default='MANUAL')
    source_doc = models.CharField(max_length=100, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Movimentação"
        verbose_name_plural = "Movimentações"

    def clean(self):
        if not self.product and not self.variant:
            raise ValidationError("Deve especificar produto ou variante.")

    def __str__(self):
        target = self.variant.sku if self.variant else (self.product.sku if self.product else "?")
        return f"{self.get_type_display()} {self.quantity}x {target}"

# ==========================================
# 3. Import & Intelligence Layer (V3)
# ==========================================

class ImportBatch(TenantMixin):
    """Batch import header for tracking CSV/XML files"""
    IMPORT_TYPES = [
        ('CSV_PRODUCTS', 'CSV de Produtos'),
        ('CSV_VARIANTS', 'CSV de Variações'),
        ('CSV_INVENTORY', 'CSV de Inventário'),
        ('XML_NFE', 'XML de NF-e'),
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
    batch = models.ForeignKey(ImportBatch, on_delete=models.CASCADE, related_name='items')
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

# Legacy V2 models kept for migration compatibility
class AdjustmentReason(TenantMixin):
    code = models.CharField(max_length=20)
    name = models.CharField(max_length=100)
    impact_type = models.CharField(max_length=10, default='NEUTRAL')
    requires_note = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.code} - {self.name}"

    @classmethod
    def seed_defaults(cls, tenant):
        reasons = [
            {'code': 'COMPRA', 'name': 'Compra de Mercadoria', 'impact_type': 'GAIN'},
            {'code': 'AJUSTE_POS', 'name': 'Ajuste Positivo', 'impact_type': 'GAIN'},
            {'code': 'AJUSTE_NEG', 'name': 'Ajuste Negativo', 'impact_type': 'LOSS'},
            {'code': 'AVARIA', 'name': 'Avaria/Quebra', 'impact_type': 'LOSS', 'requires_note': True},
            {'code': 'FURTO', 'name': 'Furto/Roubo', 'impact_type': 'LOSS', 'requires_note': True},
            {'code': 'VENCIMENTO', 'name': 'Data de Validade Expirada', 'impact_type': 'LOSS'},
            {'code': 'DEVOLUCAO', 'name': 'Devolução de Cliente', 'impact_type': 'GAIN'},
        ]
        created = []
        for r in reasons:
            obj, _ = cls.objects.get_or_create(tenant=tenant, code=r['code'], defaults=r)
            created.append(obj)
        return created

class PendingAssociation(TenantMixin):
    import_batch = models.ForeignKey(ImportBatch, on_delete=models.CASCADE)
    supplier = models.ForeignKey('partners.Supplier', on_delete=models.CASCADE, null=True, blank=True)

    nfe_key = models.CharField(max_length=44, blank=True)
    nfe_number = models.CharField(max_length=20, blank=True)
    item_number = models.IntegerField(default=0)

    supplier_sku = models.CharField(max_length=60)
    supplier_ean = models.CharField(max_length=20, blank=True)
    supplier_name = models.CharField(max_length=120)

    ncm = models.CharField(max_length=10, blank=True)
    cfop = models.CharField(max_length=4, blank=True)
    unit = models.CharField(max_length=10, blank=True)

    quantity = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    total_cost = models.DecimalField(max_digits=12, decimal_places=4, default=0)

    status = models.CharField(max_length=20, choices=PendingAssociationStatus.choices, default=PendingAssociationStatus.PENDING)
    match_suggestions = models.JSONField(default=list, blank=True)
    match_score = models.FloatField(default=0)

    resolved_product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, blank=True)
    resolved_variant = models.ForeignKey(ProductVariant, on_delete=models.SET_NULL, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.supplier_sku} - {self.supplier_name}"
