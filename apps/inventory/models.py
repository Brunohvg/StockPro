"""
Inventory App - Stock Movements and Import Management
"""
import uuid
from django.db import models
from django.conf import settings
from apps.tenants.models import TenantMixin
from apps.products.models import Product


class StockMovement(TenantMixin):
    """Immutable record of stock changes"""
    MOVEMENT_TYPES = [
        ('IN', 'Entrada'),
        ('OUT', 'Saída'),
        ('ADJ', 'Ajuste'),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='movements')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    type = models.CharField(max_length=3, choices=MOVEMENT_TYPES)
    quantity = models.PositiveIntegerField()
    reason = models.CharField(max_length=255, blank=True)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    source = models.CharField(max_length=50, blank=True, default='MANUAL')
    source_doc = models.CharField(max_length=100, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Movimentação"
        verbose_name_plural = "Movimentações"

    def __str__(self):
        return f"{self.get_type_display()} {self.quantity}x {self.product.sku}"


class ImportBatch(TenantMixin):
    """Batch import record for CSV/XML files"""
    IMPORT_TYPES = [
        ('CSV_PRODUCTS', 'CSV de Produtos'),
        ('XML_NFE', 'XML de NF-e'),
    ]
    STATUS_CHOICES = [
        ('PENDING', 'Pendente'),
        ('PROCESSING', 'Processando'),
        ('COMPLETED', 'Concluído'),
        ('ERROR', 'Erro'),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    type = models.CharField(max_length=20, choices=IMPORT_TYPES)
    file = models.FileField(upload_to='imports/%Y/%m/%d/')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    log = models.TextField(blank=True, null=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Lote de Importação"
        verbose_name_plural = "Lotes de Importação"

    def __str__(self):
        return f"{self.get_type_display()} - {self.created_at.strftime('%d/%m/%Y %H:%M')}"
