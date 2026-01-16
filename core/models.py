from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from django.utils.text import slugify
import uuid

class Plan(models.Model):
    PLAN_TYPES = [
        ('FREE', 'Free'),
        ('STARTER', 'Starter'),
        ('PRO', 'Pro'),
        ('ENTERPRISE', 'Enterprise'),
    ]
    name = models.CharField(max_length=50, choices=PLAN_TYPES, unique=True)
    display_name = models.CharField(max_length=100, default="Plano")
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    max_products = models.PositiveIntegerField(default=50, help_text="Limite de produtos cadastrados")
    max_users = models.PositiveIntegerField(default=3, help_text="Limite de usuários na empresa")
    features = models.TextField(blank=True, help_text="Lista de features separadas por vírgula")

    class Meta:
        verbose_name = "Plano"
        verbose_name_plural = "Planos"

    def __str__(self):
        return self.display_name

class Tenant(models.Model):
    SUBSCRIPTION_STATUS = [
        ('TRIAL', 'Em Teste'),
        ('ACTIVE', 'Ativo'),
        ('SUSPENDED', 'Suspenso'),
        ('CANCELLED', 'Cancelado'),
    ]

    name = models.CharField(max_length=100, verbose_name="Nome da Empresa/Unidade")
    cnpj = models.CharField(max_length=18, unique=True, blank=True, null=True, verbose_name="CNPJ", help_text="XX.XXX.XXX/XXXX-XX")
    slug = models.SlugField(max_length=100, unique=True, blank=True)
    subdomain = models.CharField(max_length=50, unique=True, blank=True, null=True)
    plan = models.ForeignKey(Plan, on_delete=models.SET_NULL, null=True, blank=True, related_name='tenants')
    subscription_status = models.CharField(max_length=20, choices=SUBSCRIPTION_STATUS, default='TRIAL', verbose_name="Status da Assinatura")
    trial_ends_at = models.DateTimeField(null=True, blank=True, verbose_name="Fim do Período de Teste")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Tenant (Empresa)"
        verbose_name_plural = "Tenants (Empresas)"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        # Set trial end date on first save
        if not self.pk and not self.trial_ends_at:
            from django.utils import timezone
            self.trial_ends_at = timezone.now() + timezone.timedelta(days=14)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    @property
    def is_trial_expired(self):
        from django.utils import timezone
        if self.subscription_status == 'TRIAL' and self.trial_ends_at:
            return timezone.now() > self.trial_ends_at
        return False

    @property
    def products_count(self):
        return self.product_set.count()

    @property
    def users_count(self):
        return self.userprofile_set.count()

    @property
    def products_limit_reached(self):
        if self.plan and self.plan.max_products:
            return self.products_count >= self.plan.max_products
        return False

    @property
    def users_limit_reached(self):
        if self.plan and self.plan.max_users:
            return self.users_count >= self.plan.max_users
        return False

class TenantMixin(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, verbose_name="Tenant", null=True, blank=True)

    class Meta:
        abstract = True

class Category(TenantMixin):
    name = models.CharField(max_length=100, verbose_name="Nome da Categoria")
    slug = models.SlugField(max_length=100, blank=True)
    description = models.TextField(blank=True, verbose_name="Descrição")

    class Meta:
        verbose_name = "Categoria"
        verbose_name_plural = "Categorias"
        unique_together = ('tenant', 'name')
        unique_together = ('tenant', 'slug')

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"[{self.tenant.name}] {self.name}"

class Brand(TenantMixin):
    name = models.CharField(max_length=100, verbose_name="Nome da Marca")
    slug = models.SlugField(max_length=100, blank=True)

    class Meta:
        verbose_name = "Marca"
        verbose_name_plural = "Marcas"
        unique_together = ('tenant', 'name')

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"[{self.tenant.name}] {self.name}"

class Product(TenantMixin):
    sku = models.CharField(max_length=50, help_text="Stock Keeping Unit - Código único do produto")
    name = models.CharField(max_length=255, verbose_name="Nome do Produto")
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True, related_name='products', verbose_name="Categoria")
    brand = models.ForeignKey(Brand, on_delete=models.SET_NULL, null=True, blank=True, related_name='products', verbose_name="Marca")
    uom = models.CharField(max_length=20, verbose_name="Unidade de Medida", help_text="Ex: UN, KG, LT")
    minimum_stock = models.PositiveIntegerField(default=0, verbose_name="Estoque Mínimo")

    # Core Data
    current_stock = models.IntegerField(default=0, verbose_name="Estoque Atual", editable=False)

    # Financial & Status (New V2)
    avg_unit_cost = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name="Custo Médio Unitário")
    is_active = models.BooleanField(default=True, verbose_name="Ativo")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Produto"
        verbose_name_plural = "Produtos"
        unique_together = ('tenant', 'sku')
        indexes = [
            models.Index(fields=['name']),
            models.Index(fields=['category']),
            models.Index(fields=['brand']),
            models.Index(fields=['is_active']),
        ]

    def __str__(self):
        return f"[{self.tenant.name}] [{self.sku}] {self.name}"


class StockMovement(TenantMixin):
    MOVEMENT_TYPES = [
        ('IN', 'Entrada'),
        ('OUT', 'Saída'),
        ('ADJUSTMENT', 'Ajuste de Inventário'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='movements', verbose_name="Produto")
    type = models.CharField(max_length=20, choices=MOVEMENT_TYPES, verbose_name="Tipo de Movimentação")
    quantity = models.PositiveIntegerField(verbose_name="Quantidade")

    # Balance Snapshot
    balance_before = models.IntegerField(editable=False, verbose_name="Saldo Anterior")
    balance_after = models.IntegerField(editable=False, verbose_name="Saldo Posterior")

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, verbose_name="Usuário Responsável")
    reason = models.TextField(verbose_name="Motivo/Justificativa", blank=True)

    # Detailed Audit (New V2)
    source = models.CharField(max_length=100, blank=True, null=True, help_text="Origem: MANUAL, API, XML, CSV")
    source_doc = models.CharField(max_length=100, blank=True, null=True, verbose_name="Documento de Origem", help_text="Ex: NF-e 1234, Pedido Importação #99")
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name="Custo Unitário (Entrada)")
    batch_info = models.CharField(max_length=100, blank=True, null=True, verbose_name="Lote / Validade")
    external_reference = models.CharField(max_length=100, blank=True, null=True, verbose_name="Ref. Externa")

    # Technical fields
    idempotency_key = models.UUIDField(unique=True, null=True, blank=True, help_text="Chave para prevenir duplicação de requisições")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Data da Movimentação")

    class Meta:
        verbose_name = "Movimentação de Estoque"
        verbose_name_plural = "Movimentações de Estoque"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['created_at']),
            models.Index(fields=['type']),
            models.Index(fields=['source']),
        ]

    def clean(self):
        if self.type == 'ADJUSTMENT' and not self.reason:
            raise ValidationError({'reason': _('Justificativa é obrigatória para Ajustes de Inventário.')})

    def save(self, *args, **kwargs):
        if self.pk and StockMovement.objects.filter(pk=self.pk).exists():
            raise ValidationError(_("Movimentações de estoque são imutáveis."))
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.type} {self.quantity} x {self.product.sku} em {self.created_at}"


class ImportBatch(TenantMixin):
    STATUS_CHOICES = [
        ('PENDING', 'Pendente'),
        ('PROCESSING', 'Processando'),
        ('COMPLETED', 'Concluído'),
        ('ERROR', 'Erro'),
    ]

    TYPE_CHOICES = [
        ('CSV_PRODUCTS', 'Importar Produtos (CSV)'),
        ('XML_NFE', 'Nota Fiscal Eletrônica (XML)'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    file = models.FileField(upload_to='imports/%Y/%m/%d/', verbose_name="Arquivo")
    type = models.CharField(max_length=20, choices=TYPE_CHOICES, verbose_name="Tipo de Importação")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    log = models.TextField(blank=True, verbose_name="Log de Processamento")

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Lote de Importação"
        verbose_name_plural = "Lotes de Importação"
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.get_status_display()}] {self.type} - {self.created_at}"
class SystemSetting(TenantMixin):
    company_name = models.CharField(max_length=100, default="StockPro Enterprise", verbose_name="Nome da Empresa")
    company_logo_url = models.URLField(blank=True, null=True, verbose_name="URL do Logotipo")
    prevent_negative_stock = models.BooleanField(default=True, verbose_name="Impedir Estoque Negativo", help_text="Bloqueia saídas se não houver saldo suficiente.")
    low_stock_threshold_global = models.PositiveIntegerField(default=5, verbose_name="Alerta Global de Estoque Baixo")
    enable_notifications = models.BooleanField(default=True, verbose_name="Habilitar Notificações")

    class Meta:
        verbose_name = "Configuração do Sistema"
        verbose_name_plural = "Configurações do Sistema"
        unique_together = ('tenant',)

    def __str__(self):
        return "Configurações Globais"

    @classmethod
    def get_settings(cls, tenant):
        obj, created = cls.objects.get_or_create(tenant=tenant)
        return obj

class UserProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='profile')
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='users')

    def __str__(self):
        return f"{self.user.username} ({self.tenant.name})"
