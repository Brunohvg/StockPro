"""
Products App - Product Catalog Management (V10 - Normalized Architecture)
"""
from django.db import models
from apps.tenants.models import Tenant, TenantMixin


class ProductType(models.TextChoices):
    SIMPLE = 'SIMPLE', 'Produto Simples'
    VARIABLE = 'VARIABLE', 'Produto Variável'


class Category(TenantMixin):
    """Product category with stock rotation classification"""
    ROTATION_TYPES = [
        ('A', 'Alta Rotação'),
        ('B', 'Média Rotação'),
        ('C', 'Baixa Rotação'),
    ]
    name = models.CharField(max_length=100)
    rotation = models.CharField(max_length=1, choices=ROTATION_TYPES, default='B')

    class Meta:
        verbose_name = "Categoria"
        verbose_name_plural = "Categorias"
        unique_together = ['tenant', 'name']

    def __str__(self):
        return self.name


class Brand(TenantMixin):
    """Product brand/manufacturer"""
    name = models.CharField(max_length=100)

    class Meta:
        verbose_name = "Marca"
        verbose_name_plural = "Marcas"
        unique_together = ['tenant', 'name']

    def __str__(self):
        return self.name


class AttributeType(TenantMixin):
    """
    Tipos de atributos para variações: Cor, Tamanho, Voltagem, etc.
    Normalizados para queries eficientes e consistência.
    """
    name = models.CharField(max_length=50, verbose_name="Nome do Atributo")

    class Meta:
        verbose_name = "Tipo de Atributo"
        verbose_name_plural = "Tipos de Atributo"
        unique_together = ['tenant', 'name']
        ordering = ['name']

    def __str__(self):
        return self.name


class Product(TenantMixin):
    """
    Produto Base - pode ser SIMPLE (único) ou VARIABLE (com variações).
    Para SIMPLE: estoque controlado diretamente aqui.
    Para VARIABLE: estoque é a soma das variantes.
    """
    sku = models.CharField(max_length=50, blank=True, null=True, verbose_name="SKU Base")
    _allow_stock_change = False  # Flag interna para permitir alteração de estoque via StockService
    name = models.CharField(max_length=255, verbose_name="Nome do Produto")
    product_type = models.CharField(
        max_length=10,
        choices=ProductType.choices,
        default=ProductType.SIMPLE,
        verbose_name="Tipo"
    )
    photo = models.ImageField(upload_to='products/', blank=True, null=True, verbose_name="Foto")
    description = models.TextField(blank=True, verbose_name="Descrição")
    category = models.ForeignKey('Category', on_delete=models.SET_NULL, null=True, blank=True, related_name='products')
    brand = models.ForeignKey('Brand', on_delete=models.SET_NULL, null=True, blank=True, related_name='products')
    uom = models.CharField(max_length=10, default='UN', verbose_name="Unidade")

    # Novas Atribuições V2
    default_supplier = models.ForeignKey(
        'partners.Supplier',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='default_products',
        verbose_name="Fornecedor Padrão"
    )
    default_location = models.ForeignKey(
        'inventory.Location',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='default_products',
        verbose_name="Local de Estoque Padrão"
    )

    # Campos para SIMPLE - ignorados se VARIABLE
    barcode = models.CharField(max_length=100, blank=True, null=True, verbose_name="Código de Barras")
    current_stock = models.DecimalField(max_digits=12, decimal_places=4, default=0, verbose_name="Estoque Atual")
    minimum_stock = models.DecimalField(max_digits=12, decimal_places=4, default=0, verbose_name="Estoque Mínimo")
    avg_unit_cost = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True, verbose_name="Custo Médio")

    # AI Hardening (V3)
    requires_review = models.BooleanField(default=False, verbose_name="Requer Revisão")
    ai_confidence = models.DecimalField(max_digits=3, decimal_places=2, default=1.0, verbose_name="Confiança IA")

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Produto"
        verbose_name_plural = "Produtos"
        unique_together = ['tenant', 'sku']
        ordering = ['name']

    def generate_sku(self):
        """Gera SKU padronizado: [TIPO]-[CAT]-[ID]"""
        prefix = "VAR" if self.is_variable else "SIM"

        # Pega as primeiras 3 letras da categoria ou 'GER'
        cat_code = "GER"
        if self.category:
            cat_code = "".join(filter(str.isalnum, self.category.name)).upper()[:3]

        return f"{prefix}-{cat_code}-{self.id:04d}"

    def save(self, *args, **kwargs):
        is_new = self._state.adding

        # LOCKDOWN: Se não for novo e o estoque mudou sem a flag, bloqueia
        if not is_new and hasattr(self, 'id'):
            old_instance = Product.objects.get(pk=self.id)
            if old_instance.current_stock != self.current_stock and not getattr(self, '_allow_stock_change', False):
                # Reverte e avisa
                self.current_stock = old_instance.current_stock
                # Em produção poderíamos dar raise ValidationError, mas para evitar quebrar o Admin por completo,
                # apenas revertemos silenciosamente ou logamos. Vamos de Reversão Silenciosa + Flag interna para o Admin saber.

        super().save(*args, **kwargs)
        if (is_new and not self.sku) or (self.sku and (self.sku.startswith('PROD-') or '-' not in self.sku)):
            # Se for novo ou tiver o padrão antigo 'PROD-...'
            self.sku = self.generate_sku()
            Product.objects.filter(pk=self.pk).update(sku=self.sku)

    @property
    def ai_confidence_percent(self):
        return int((self.ai_confidence or 0) * 100)

    def __str__(self):
        return f"{self.sku} - {self.name}" if self.sku else self.name

    @property
    def is_simple(self):
        return self.product_type == ProductType.SIMPLE

    @property
    def is_variable(self):
        return self.product_type == ProductType.VARIABLE

    @property
    def total_stock(self):
        """Retorna estoque total (próprio se SIMPLE, soma se VARIABLE)"""
        if self.is_variable:
            return sum(v.current_stock for v in self.variants.all())
        return self.current_stock

    @property
    def total_stock_value(self):
        """Valor total em estoque"""
        if self.is_variable:
            return sum(v.stock_value for v in self.variants.all())
        return (self.current_stock or 0) * (self.avg_unit_cost or 0)

    @property
    def variants_count(self):
        return self.variants.count() if self.is_variable else 0

    @property
    def is_low_stock(self):
        if self.is_variable:
            return any(v.is_low_stock for v in self.variants.all())
        return self.current_stock <= self.minimum_stock

    @property
    def can_be_safely_deleted(self):
        """
        Produto pode ser excluído com segurança se:
        - Não possui movimentações de SAÍDA (OUT)
        - Apenas entradas (IN) ou ajustes (ADJ)

        Isso permite desfazer imports errados sem corromper histórico de vendas.
        """
        from apps.inventory.models import StockMovement

        if self.is_variable:
            # Para VARIABLE, verificar todas as variantes
            for variant in self.variants.all():
                if StockMovement.objects.filter(variant=variant, type='OUT').exists():
                    return False
            return True
        else:
            # Para SIMPLE, verificar movimentações do próprio produto
            return not StockMovement.objects.filter(product=self, type='OUT').exists()

    @property
    def delete_block_reason(self):
        """Retorna o motivo pelo qual não pode ser excluído, ou None se pode."""
        if self.can_be_safely_deleted:
            return None
        return "Este produto possui movimentações de saída e não pode ser excluído."


class ProductVariant(TenantMixin):
    """
    Variação específica de um produto variável.
    Ex: "Tinta PVA Azul", "Camiseta M Preta"
    Cada variação tem SKU, estoque e código de barras próprios.
    """
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='variants',
        limit_choices_to={'product_type': ProductType.VARIABLE}
    )
    sku = models.CharField(max_length=50, null=True, blank=True, verbose_name="SKU Variação")
    _allow_stock_change = False
    name = models.CharField(max_length=255, blank=True, verbose_name="Nome da Variação")
    barcode = models.CharField(max_length=100, blank=True, null=True, verbose_name="Código de Barras")
    photo = models.ImageField(upload_to='products/variants/', blank=True, null=True)

    current_stock = models.DecimalField(max_digits=12, decimal_places=4, default=0, verbose_name="Estoque")
    minimum_stock = models.DecimalField(max_digits=12, decimal_places=4, default=0, verbose_name="Estoque Mínimo")
    avg_unit_cost = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True, verbose_name="Custo Médio")

    # AI Hardening (V3)
    requires_review = models.BooleanField(default=False, verbose_name="Requer Revisão")
    ai_confidence = models.DecimalField(max_digits=3, decimal_places=2, default=1.0, verbose_name="Confiança IA")

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Variação de Produto"
        verbose_name_plural = "Variações de Produtos"
        unique_together = ['tenant', 'sku']
        ordering = ['product', 'name']

    def generate_sku(self):
        """Gera SKU padronizado: [SKU_PAI]-[ATTR_VALS]"""
        parent_sku = self.product.sku
        attrs = self.attribute_values.all()
        if not attrs:
            return f"{parent_sku}-{self.id}"

        # Pega as primeiras 2 letras de cada valor de atributo
        attr_slugs = []
        for a in attrs:
            val = "".join(filter(str.isalnum, a.value)).upper()
            attr_slugs.append(val[:2] if len(val) > 2 else val)

        return f"{parent_sku}-{''.join(attr_slugs)}"

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        # Inherit tenant from parent product
        if self.product_id and not self.tenant_id:
            self.tenant = self.product.tenant

        # LOCKDOWN
        if not is_new and hasattr(self, 'id'):
            old_instance = ProductVariant.objects.get(pk=self.id)
            if old_instance.current_stock != self.current_stock and not getattr(self, '_allow_stock_change', False):
                self.current_stock = old_instance.current_stock

        super().save(*args, **kwargs)
        if (is_new and not self.sku) or (self.sku and self.sku.startswith('VAR-') and '-' not in self.sku[4:]):
            self.sku = self.generate_sku()
            ProductVariant.objects.filter(pk=self.pk).update(sku=self.sku)

    def __str__(self):
        attrs = ", ".join([f"{a.attribute_type.name}: {a.value}" for a in self.attribute_values.all()])
        if attrs:
            return f"{self.product.name} ({attrs})"
        return self.name or f"{self.product.name} - {self.sku}"

    @property
    def ai_confidence_percent(self):
        return int((self.ai_confidence or 0) * 100)

    @property
    def stock_value(self):
        return (self.current_stock or 0) * (self.avg_unit_cost or 0)

    @property
    def is_low_stock(self):
        return self.current_stock <= self.minimum_stock

    @property
    def display_name(self):
        """Nome legível com atributos"""
        attrs = self.attribute_values.select_related('attribute_type').all()
        if attrs:
            attr_str = " / ".join([f"{a.value}" for a in attrs])
            return f"{self.product.name} - {attr_str}"
        return self.name or self.sku

    @property
    def can_be_safely_deleted(self):
        """Variante pode ser excluída se não possui saídas (OUT)."""
        from apps.inventory.models import StockMovement
        return not StockMovement.objects.filter(variant=self, type='OUT').exists()


class VariantAttributeValue(models.Model):
    """
    Valor de atributo para uma variação específica.
    Ex: variant="Tinta Azul", attribute_type="Cor", value="Azul"
    """
    variant = models.ForeignKey(
        ProductVariant,
        on_delete=models.CASCADE,
        related_name='attribute_values'
    )
    attribute_type = models.ForeignKey(
        AttributeType,
        on_delete=models.PROTECT,
        verbose_name="Tipo de Atributo"
    )
    value = models.CharField(max_length=100, verbose_name="Valor")

    class Meta:
        verbose_name = "Valor de Atributo"
        verbose_name_plural = "Valores de Atributos"
        unique_together = ['variant', 'attribute_type']
        ordering = ['attribute_type__name']

    def __str__(self):
        return f"{self.attribute_type.name}: {self.value}"
