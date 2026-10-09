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


# ==========================================
# 5. NF-e de entrada (Beta)
# ==========================================

class NfeSettings(TenantMixin):
    """Padrão de cada empresa para importar notas fiscais de compra."""
    NEW_PRODUCT_POLICY = [
        ('REVIEW', 'Decidir item a item na prévia (padrão)'),
        ('AUTO_CREATE', 'Sugerir "criar produto novo" para itens não encontrados'),
    ]
    SKU_POLICY = [
        ('AUTO', 'Gerar SKU automaticamente'),
        ('SUPPLIER_CODE', 'Usar o código do fornecedor (cProd)'),
        ('EAN', 'Usar o EAN, quando houver'),
    ]

    # Custo de entrada (rateio por item, campos da própria NF-e)
    cost_include_ipi = models.BooleanField(default=True, verbose_name="Somar IPI ao custo")
    cost_include_st = models.BooleanField(default=True, verbose_name="Somar ICMS-ST (e FCP-ST) ao custo")
    cost_include_freight = models.BooleanField(default=True, verbose_name="Somar frete ao custo")
    cost_include_insurance = models.BooleanField(default=True, verbose_name="Somar seguro ao custo")
    cost_include_other = models.BooleanField(default=True, verbose_name="Somar outras despesas ao custo")
    cost_subtract_discount = models.BooleanField(default=True, verbose_name="Descontar o desconto do custo")

    # Como encontrar o produto (nesta ordem)
    match_supplier_code = models.BooleanField(default=True, verbose_name="Pelo código do fornecedor já aprendido")
    match_ean = models.BooleanField(default=True, verbose_name="Pelo código de barras (EAN)")
    match_sku = models.BooleanField(default=False, verbose_name="Pelo SKU igual ao código do fornecedor")

    # Produtos novos
    new_product_policy = models.CharField(max_length=20, choices=NEW_PRODUCT_POLICY, default='REVIEW',
                                          verbose_name="Itens não encontrados")
    sku_policy = models.CharField(max_length=20, choices=SKU_POLICY, default='AUTO',
                                  verbose_name="SKU dos produtos criados pela nota")
    default_category = models.ForeignKey('products.Category', on_delete=models.SET_NULL, null=True, blank=True,
                                         verbose_name="Categoria padrão dos produtos novos")
    title_case_names = models.BooleanField(default=True, verbose_name="Ajustar nomes em MAIÚSCULAS (Caneta Azul)")
    auto_tracks_expiry = models.BooleanField(default=True,
                                             verbose_name="Ligar 'controla validade' quando a nota trouxer lote")

    # Entrada
    default_location = models.ForeignKey('Location', on_delete=models.SET_NULL, null=True, blank=True,
                                         verbose_name="Local de entrada padrão")
    require_recipient_cnpj = models.BooleanField(
        default=True, verbose_name="Exigir confirmação quando o destinatário não for o CNPJ da empresa")

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Configuração de NF-e"
        constraints = [models.UniqueConstraint(fields=['tenant'], name='unique_nfe_settings_per_tenant')]

    @classmethod
    def for_tenant(cls, tenant):
        obj, _ = cls.objects.get_or_create(tenant=tenant)
        return obj


class NfeDocument(TenantMixin):
    STATUS = [
        ('PREVIEW', 'Em revisão'),
        ('IMPORTED', 'Importada'),
        ('REVERTED', 'Desfeita'),
        ('DISCARDED', 'Descartada'),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    access_key = models.CharField(max_length=44, verbose_name="Chave de acesso")
    number = models.CharField(max_length=20, blank=True)
    series = models.CharField(max_length=5, blank=True)
    issued_at = models.DateTimeField(null=True, blank=True)
    supplier_cnpj = models.CharField(max_length=14, blank=True)
    supplier_name = models.CharField(max_length=200, blank=True)
    supplier_trade_name = models.CharField(max_length=200, blank=True)
    supplier_ie = models.CharField(max_length=20, blank=True)
    supplier_city = models.CharField(max_length=100, blank=True)
    supplier_state = models.CharField(max_length=2, blank=True)
    supplier = models.ForeignKey('partners.Supplier', on_delete=models.SET_NULL, null=True, blank=True)
    recipient_cnpj = models.CharField(max_length=14, blank=True)
    total_products = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_invoice = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    authorized = models.BooleanField(default=False, verbose_name="Tem protocolo de autorização")
    warnings = models.JSONField(default=list, blank=True)
    xml_file = models.FileField(upload_to='nfe/%Y/%m/')
    status = models.CharField(max_length=20, choices=STATUS, default='PREVIEW')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                   related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    imported_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                    blank=True, related_name='+')
    imported_at = models.DateTimeField(null=True, blank=True)
    reverted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "NF-e de entrada"
        verbose_name_plural = "NF-e de entrada"
        constraints = [
            # A mesma nota não pode estar em revisão/importada duas vezes na mesma empresa
            models.UniqueConstraint(fields=['tenant', 'access_key'],
                                    condition=models.Q(status__in=['PREVIEW', 'IMPORTED']),
                                    name='unique_active_nfe_per_tenant'),
        ]

    def __str__(self):
        return f"NF-e {self.number} - {self.supplier_name}"

    @property
    def blocking_warnings(self):
        return [w for w in self.warnings if w.get('blocking')]


class NfeItem(models.Model):
    DECISIONS = [
        ('LINK', 'Vincular a produto existente'),
        ('CREATE', 'Criar produto novo'),
        ('IGNORE', 'Ignorar (não dar entrada)'),
        ('PENDING', 'Decidir'),
    ]
    document = models.ForeignKey(NfeDocument, on_delete=models.CASCADE, related_name='items')
    item_number = models.PositiveIntegerField()
    supplier_code = models.CharField(max_length=60, blank=True)
    ean = models.CharField(max_length=14, blank=True)
    description = models.CharField(max_length=255)
    ncm = models.CharField(max_length=10, blank=True)
    cfop = models.CharField(max_length=4, blank=True)
    unit = models.CharField(max_length=10, blank=True)
    quantity = models.DecimalField(max_digits=15, decimal_places=4)
    unit_price = models.DecimalField(max_digits=21, decimal_places=10, default=0)
    total = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    freight = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    insurance = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    discount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    other = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    ipi = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    icms_st = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    lots = models.JSONField(default=list, blank=True)  # [{"lot", "quantity", "manufacture", "expiry"}]

    decision = models.CharField(max_length=10, choices=DECISIONS, default='PENDING')
    variant = models.ForeignKey('products.ProductVariant', on_delete=models.SET_NULL, null=True, blank=True)
    match_source = models.CharField(max_length=20, blank=True)  # SUPPLIER_MAP | EAN | SKU | MANUAL
    conversion_factor = models.DecimalField(max_digits=12, decimal_places=4, default=1)
    factor_suggested = models.BooleanField(default=False)
    new_product_name = models.CharField(max_length=255, blank=True)
    new_product_category = models.ForeignKey('products.Category', on_delete=models.SET_NULL, null=True, blank=True)
    movement_ids = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ['item_number']

    def cost_total(self, cfg):
        """Valor do item que vira custo, conforme a configuração da empresa."""
        from decimal import Decimal
        total = Decimal(self.total)
        if cfg.cost_include_ipi:
            total += self.ipi
        if cfg.cost_include_st:
            total += self.icms_st
        if cfg.cost_include_freight:
            total += self.freight
        if cfg.cost_include_insurance:
            total += self.insurance
        if cfg.cost_include_other:
            total += self.other
        if cfg.cost_subtract_discount:
            total -= self.discount
        return max(total, Decimal('0'))

    @property
    def stock_quantity(self):
        return self.quantity * self.conversion_factor

    def unit_cost(self, cfg):
        from decimal import ROUND_HALF_UP, Decimal
        qty = self.stock_quantity
        if not qty:
            return Decimal('0')
        return (self.cost_total(cfg) / qty).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)
