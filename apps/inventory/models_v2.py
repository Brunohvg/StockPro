"""
Inventory App - V2 Models (New models only)

Este módulo define APENAS os novos modelos para V2:
- Location: Locais físicos de armazenamento
- AdjustmentReason: Motivos de ajuste para auditoria
- PendingAssociation: Itens pendentes de associação em importação

Os campos adicionais de StockMovement e ImportBatch são adicionados
via migrations no modelo existente em models.py
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Optional, TYPE_CHECKING

from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.tenants.models import TenantMixin

if TYPE_CHECKING:
    from apps.products.models import Product, ProductVariant


class LocationType(models.TextChoices):
    """Tipos de localização física."""
    STORE = 'STORE', 'Loja'
    WAREHOUSE = 'WAREHOUSE', 'Depósito'
    SHELF = 'SHELF', 'Prateleira'
    DISPLAY = 'DISPLAY', 'Expositor'
    TRANSIT = 'TRANSIT', 'Em Trânsito'
    QUARANTINE = 'QUARANTINE', 'Quarentena'


class Location(TenantMixin):
    """
    Representa um local físico de armazenamento.
    
    Permite organização hierárquica (ex: Depósito > Corredor A > Prateleira 1)
    e segregação de estoque por local.
    
    Attributes:
        code: Código único do local (ex: "LOJ-001")
        name: Nome legível (ex: "Loja Centro")
        location_type: Tipo do local (STORE, WAREHOUSE, etc.)
        parent: Local pai para hierarquia
        address: Endereço físico (opcional)
        is_active: Se o local está ativo
        is_default: Se é o local padrão para recebimento
        allows_negative: Se permite estoque negativo (ex: consignação)
    """
    
    code = models.CharField(
        max_length=20,
        verbose_name='Código',
        help_text='Código único do local (ex: LOJ-001)'
    )
    name = models.CharField(
        max_length=100,
        verbose_name='Nome'
    )
    location_type = models.CharField(
        max_length=20,
        choices=LocationType.choices,
        default=LocationType.STORE,
        verbose_name='Tipo'
    )
    parent = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='children',
        verbose_name='Local Pai',
        help_text='Para organização hierárquica'
    )
    
    address = models.TextField(
        blank=True,
        verbose_name='Endereço'
    )
    
    is_active = models.BooleanField(
        default=True,
        verbose_name='Ativo'
    )
    is_default = models.BooleanField(
        default=False,
        verbose_name='Local Padrão',
        help_text='Local padrão para recebimento de mercadorias'
    )
    allows_negative = models.BooleanField(
        default=False,
        verbose_name='Permite Negativo',
        help_text='Permite estoque negativo (ex: consignação)'
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = 'Localização'
        verbose_name_plural = 'Localizações'
        unique_together = ['tenant', 'code']
        ordering = ['name']
        indexes = [
            models.Index(fields=['tenant', 'code']),
            models.Index(fields=['tenant', 'is_active', 'is_default']),
        ]
    
    def __str__(self) -> str:
        if self.parent:
            return f'{self.parent.name} > {self.name}'
        return self.name
    
    def clean(self) -> None:
        """Valida dados antes de salvar."""
        super().clean()
        
        # Impede auto-referência
        if self.parent_id and self.parent_id == self.pk:
            raise ValidationError({
                'parent': 'Um local não pode ser pai de si mesmo.'
            })
        
        # Impede referência circular
        if self.parent:
            ancestor = self.parent
            while ancestor:
                if ancestor.pk == self.pk:
                    raise ValidationError({
                        'parent': 'Referência circular detectada na hierarquia.'
                    })
                ancestor = ancestor.parent
    
    def save(self, *args, **kwargs) -> None:
        # Garante que só um local seja default por tenant
        if self.is_default:
            Location.objects.filter(
                tenant=self.tenant,
                is_default=True
            ).exclude(pk=self.pk).update(is_default=False)
        
        super().save(*args, **kwargs)
    
    @property
    def full_path(self) -> str:
        """Retorna caminho completo na hierarquia."""
        parts = [self.name]
        ancestor = self.parent
        while ancestor:
            parts.insert(0, ancestor.name)
            ancestor = ancestor.parent
        return ' > '.join(parts)
    
    @classmethod
    def get_default_for_tenant(cls, tenant) -> Optional['Location']:
        """Retorna local padrão do tenant."""
        return cls.objects.filter(
            tenant=tenant,
            is_active=True,
            is_default=True
        ).first()
    
    @classmethod
    def ensure_default_exists(cls, tenant) -> 'Location':
        """
        Garante que existe um local padrão para o tenant.
        Cria automaticamente se não existir.
        """
        location = cls.get_default_for_tenant(tenant)
        if not location:
            location = cls.objects.create(
                tenant=tenant,
                code='PRINCIPAL',
                name='Localização Principal',
                location_type=LocationType.STORE,
                is_default=True
            )
        return location


class ImpactType(models.TextChoices):
    """Tipo de impacto do ajuste no estoque."""
    LOSS = 'LOSS', 'Perda'
    GAIN = 'GAIN', 'Ganho'
    NEUTRAL = 'NEUTRAL', 'Neutro'


class AdjustmentReason(TenantMixin):
    """
    Motivos de ajuste de estoque para auditoria.
    
    Permite tipificar e categorizar os ajustes de estoque
    para análise de perdas e controle interno.
    
    Attributes:
        code: Código único (ex: "FURTO")
        name: Nome legível (ex: "Furto/Roubo")
        description: Descrição detalhada
        impact_type: Tipo de impacto (LOSS, GAIN, NEUTRAL)
        requires_note: Se obriga preenchimento de observação
        is_active: Se o motivo está ativo
    """
    
    code = models.CharField(
        max_length=20,
        verbose_name='Código'
    )
    name = models.CharField(
        max_length=100,
        verbose_name='Nome'
    )
    description = models.TextField(
        blank=True,
        verbose_name='Descrição'
    )
    impact_type = models.CharField(
        max_length=10,
        choices=ImpactType.choices,
        default=ImpactType.NEUTRAL,
        verbose_name='Tipo de Impacto'
    )
    requires_note = models.BooleanField(
        default=False,
        verbose_name='Exige Observação',
        help_text='Obriga preenchimento de observação no ajuste'
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name='Ativo'
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = 'Motivo de Ajuste'
        verbose_name_plural = 'Motivos de Ajuste'
        unique_together = ['tenant', 'code']
        ordering = ['name']
    
    def __str__(self) -> str:
        return f'{self.name} ({self.get_impact_type_display()})'
    
    @classmethod
    def seed_defaults(cls, tenant) -> list['AdjustmentReason']:
        """
        Cria motivos padrão para um tenant.
        
        Returns:
            Lista de motivos criados
        """
        defaults = [
            ('FURTO', 'Furto/Roubo', ImpactType.LOSS, True, 'Perda por furto ou roubo'),
            ('AVARIA', 'Avaria/Quebra', ImpactType.LOSS, True, 'Produto danificado ou quebrado'),
            ('VALIDADE', 'Produto Vencido', ImpactType.LOSS, False, 'Produto com validade expirada'),
            ('CONSUMO', 'Consumo Interno', ImpactType.LOSS, False, 'Consumo interno da empresa'),
            ('ACHADO', 'Produto Encontrado', ImpactType.GAIN, False, 'Produto encontrado no estoque'),
            ('DOACAO', 'Doação Recebida', ImpactType.GAIN, True, 'Produto recebido em doação'),
            ('CORRECAO', 'Correção de Sistema', ImpactType.NEUTRAL, True, 'Correção de erro no sistema'),
            ('CONTAGEM', 'Ajuste de Inventário', ImpactType.NEUTRAL, False, 'Ajuste após contagem física'),
        ]
        
        created = []
        for code, name, impact, requires_note, desc in defaults:
            obj, was_created = cls.objects.get_or_create(
                tenant=tenant,
                code=code,
                defaults={
                    'name': name,
                    'impact_type': impact,
                    'requires_note': requires_note,
                    'description': desc,
                }
            )
            if was_created:
                created.append(obj)
        
        return created


class PendingAssociationStatus(models.TextChoices):
    """Status de associação pendente."""
    PENDING = 'PENDING', 'Aguardando'
    LINKED = 'LINKED', 'Vinculado a Existente'
    CREATED = 'CREATED', 'Produto Criado'
    IGNORED = 'IGNORED', 'Ignorado'


class PendingAssociation(TenantMixin):
    """
    Item de NF-e aguardando associação manual.
    
    Quando o sistema não consegue fazer match automático de um
    item da nota fiscal, ele cria um registro aqui para o usuário
    decidir: criar novo produto ou vincular a existente.
    
    Attributes:
        import_batch: Lote de importação relacionado
        supplier: Fornecedor da NF-e
        nfe_key: Chave de acesso da NF-e
        item_number: nItem do XML
        supplier_sku: cProd do XML
        supplier_ean: cEAN do XML
        supplier_name: xProd do XML
        quantity: Quantidade a dar entrada
        unit_cost: Custo unitário
        status: Status da resolução
        resolved_product: Produto associado (após resolução)
        match_suggestions: Sugestões de produtos similares
    """
    
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )
    
    import_batch = models.ForeignKey(
        'inventory.ImportBatch',
        on_delete=models.CASCADE,
        related_name='pending_associations'
    )
    supplier = models.ForeignKey(
        'partners.Supplier',
        on_delete=models.PROTECT,
        related_name='pending_associations'
    )
    
    # Dados do XML
    nfe_key = models.CharField(max_length=44)
    nfe_number = models.CharField(max_length=20)
    item_number = models.PositiveIntegerField(verbose_name='nItem')
    
    supplier_sku = models.CharField(
        max_length=60,
        verbose_name='Código Fornecedor (cProd)'
    )
    supplier_ean = models.CharField(
        max_length=14,
        blank=True,
        verbose_name='EAN (cEAN)'
    )
    supplier_name = models.CharField(
        max_length=120,
        verbose_name='Descrição (xProd)'
    )
    ncm = models.CharField(max_length=8, blank=True)
    cfop = models.CharField(max_length=4, blank=True)
    unit = models.CharField(max_length=10, verbose_name='Unidade (uCom)')
    
    quantity = models.DecimalField(
        max_digits=15,
        decimal_places=4,
        verbose_name='Quantidade'
    )
    unit_cost = models.DecimalField(
        max_digits=15,
        decimal_places=4,
        verbose_name='Custo Unitário'
    )
    total_cost = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        verbose_name='Custo Total'
    )
    
    # Status e Resolução
    status = models.CharField(
        max_length=20,
        choices=PendingAssociationStatus.choices,
        default=PendingAssociationStatus.PENDING
    )
    resolved_product = models.ForeignKey(
        'products.Product',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='resolved_associations'
    )
    resolved_variant = models.ForeignKey(
        'products.ProductVariant',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='resolved_associations'
    )
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='resolved_associations'
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    
    # Sugestões de match
    match_suggestions = models.JSONField(
        default=list,
        blank=True,
        help_text='Lista de produtos similares encontrados'
    )
    match_score = models.FloatField(
        default=0,
        help_text='Score do melhor match encontrado (0-1)'
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = 'Associação Pendente'
        verbose_name_plural = 'Associações Pendentes'
        ordering = ['-created_at']
        unique_together = ['import_batch', 'item_number']
    
    def __str__(self) -> str:
        return f'{self.supplier_name} ({self.supplier_sku}) - {self.get_status_display()}'
    
    @property
    def is_resolved(self) -> bool:
        """Verifica se já foi resolvido."""
        return self.status != PendingAssociationStatus.PENDING
    
    def resolve_with_existing(
        self,
        product: 'Product',
        variant: Optional['ProductVariant'],
        user,
        create_mapping: bool = True
    ) -> None:
        """
        Resolve associando a um produto existente.
        
        Args:
            product: Produto a vincular
            variant: Variante a vincular (opcional)
            user: Usuário que está resolvendo
            create_mapping: Se deve criar SupplierProductMap
        """
        from apps.partners.models import SupplierProductMap
        
        self.resolved_product = product
        self.resolved_variant = variant
        self.resolved_by = user
        self.resolved_at = timezone.now()
        self.status = PendingAssociationStatus.LINKED
        self.save()
        
        if create_mapping:
            SupplierProductMap.objects.get_or_create(
                tenant=self.tenant,
                supplier=self.supplier,
                supplier_sku=self.supplier_sku,
                defaults={
                    'product': product,
                    'variant': variant,
                    'supplier_ean': self.supplier_ean,
                    'supplier_name': self.supplier_name,
                    'last_cost': self.unit_cost,
                    'last_purchase': timezone.now().date(),
                }
            )
    
    def resolve_with_new_product(
        self,
        product: 'Product',
        user
    ) -> None:
        """
        Resolve criando um novo produto.
        
        Args:
            product: Produto recém-criado
            user: Usuário que está resolvendo
        """
        self.resolved_product = product
        self.resolved_by = user
        self.resolved_at = timezone.now()
        self.status = PendingAssociationStatus.CREATED
        self.save()
    
    def ignore(self, user) -> None:
        """Ignora este item."""
        self.resolved_by = user
        self.resolved_at = timezone.now()
        self.status = PendingAssociationStatus.IGNORED
        self.save()
