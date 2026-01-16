"""
Inventory App - Stock Movements and Import Management (V10)
"""
import uuid
from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from apps.tenants.models import TenantMixin
from apps.products.models import Product, ProductVariant


class StockMovement(TenantMixin):
    """
    Immutable record of stock changes.
    Suporta tanto Product (SIMPLE) quanto ProductVariant (para VARIABLE).
    """
    MOVEMENT_TYPES = [
        ('IN', 'Entrada'),
        ('OUT', 'Saída'),
        ('ADJ', 'Ajuste'),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Suporta ambos - um deve ser preenchido
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name='movements',
        null=True,
        blank=True,
        help_text="Para produtos simples"
    )
    variant = models.ForeignKey(
        ProductVariant,
        on_delete=models.PROTECT,
        related_name='movements',
        null=True,
        blank=True,
        help_text="Para variações de produtos"
    )

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    type = models.CharField(max_length=3, choices=MOVEMENT_TYPES)
    quantity = models.PositiveIntegerField()
    balance_after = models.IntegerField(default=0, verbose_name="Saldo Após")
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
        if self.product and self.variant:
            raise ValidationError("Especifique apenas produto OU variante, não ambos.")

    def __str__(self):
        target = self.variant.sku if self.variant else (self.product.sku if self.product else "?")
        return f"{self.get_type_display()} {self.quantity}x {target}"

    @property
    def target_name(self):
        """Retorna nome legível do produto/variante"""
        if self.variant:
            return self.variant.display_name
        return self.product.name if self.product else "Desconhecido"

    @property
    def target_sku(self):
        if self.variant:
            return self.variant.sku
        return self.product.sku if self.product else ""


class ImportBatch(TenantMixin):
    """Batch import record for CSV/XML files"""
    IMPORT_TYPES = [
        ('CSV_PRODUCTS', 'CSV de Produtos'),
        ('CSV_VARIANTS', 'CSV de Variações'),
        ('XML_NFE', 'XML de NF-e'),
    ]
    STATUS_CHOICES = [
        ('PENDING', 'Pendente'),
        ('PROCESSING', 'Processando'),
        ('COMPLETED', 'Concluído'),
        ('PARTIAL', 'Parcial'),
        ('ERROR', 'Erro'),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    type = models.CharField(max_length=20, choices=IMPORT_TYPES)
    file = models.FileField(upload_to='imports/%Y/%m/%d/')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    total_rows = models.PositiveIntegerField(default=0)
    processed_rows = models.PositiveIntegerField(default=0)
    success_count = models.PositiveIntegerField(default=0)
    error_count = models.PositiveIntegerField(default=0)
    log = models.TextField(blank=True, null=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Lote de Importação"
        verbose_name_plural = "Lotes de Importação"

    def __str__(self):
        return f"{self.get_type_display()} - {self.created_at.strftime('%d/%m/%Y %H:%M')}"

    @property
    def progress_percent(self):
        if self.total_rows == 0:
            return 0
        return int((self.processed_rows / self.total_rows) * 100)


class ImportLog(TenantMixin):
    """Log de idempotência para evitar duplicações"""
    batch = models.ForeignKey(ImportBatch, on_delete=models.CASCADE, related_name='logs')
    idempotency_key = models.CharField(max_length=255, db_index=True)
    row_number = models.PositiveIntegerField(null=True)
    status = models.CharField(max_length=20, choices=[('SUCCESS', 'Sucesso'), ('ERROR', 'Erro')])
    message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Log de Importação"
        verbose_name_plural = "Logs de Importação"
        unique_together = ['batch', 'idempotency_key']
