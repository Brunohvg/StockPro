"""
Partners App - Supplier and Product Mapping Models

Este módulo define os modelos de fornecedores e mapeamento de produtos
para suportar importação inteligente de NF-e com deduplicação.

Models:
    - Supplier: Cadastro de fornecedores
    - SupplierProductMap: Vínculo entre código do fornecedor e produto interno
"""
from __future__ import annotations

import re
from decimal import Decimal
from typing import Optional, TYPE_CHECKING

from django.db import models
from django.core.validators import RegexValidator
from django.core.exceptions import ValidationError

from apps.tenants.models import TenantMixin

if TYPE_CHECKING:
    from apps.products.models import Product, ProductVariant


def validate_cnpj(value: str) -> None:
    """
    Valida CNPJ brasileiro.
    
    Args:
        value: CNPJ com ou sem formatação
        
    Raises:
        ValidationError: Se CNPJ for inválido
    """
    # Remove formatação
    cnpj = re.sub(r'[^0-9]', '', value)
    
    if len(cnpj) != 14:
        raise ValidationError('CNPJ deve ter 14 dígitos')
    
    # Verifica se todos os dígitos são iguais
    if cnpj == cnpj[0] * 14:
        raise ValidationError('CNPJ inválido')
    
    # Calcula primeiro dígito verificador
    soma = 0
    peso = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    for i, digito in enumerate(cnpj[:12]):
        soma += int(digito) * peso[i]
    resto = soma % 11
    digito1 = 0 if resto < 2 else 11 - resto
    
    # Calcula segundo dígito verificador
    soma = 0
    peso = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    for i, digito in enumerate(cnpj[:13]):
        soma += int(digito) * peso[i]
    resto = soma % 11
    digito2 = 0 if resto < 2 else 11 - resto
    
    # Verifica dígitos
    if cnpj[-2:] != f'{digito1}{digito2}':
        raise ValidationError('CNPJ inválido')


def format_cnpj(cnpj: str) -> str:
    """
    Formata CNPJ para exibição (XX.XXX.XXX/XXXX-XX).
    
    Args:
        cnpj: CNPJ apenas com números
        
    Returns:
        CNPJ formatado
    """
    cnpj = re.sub(r'[^0-9]', '', cnpj)
    if len(cnpj) == 14:
        return f'{cnpj[:2]}.{cnpj[2:5]}.{cnpj[5:8]}/{cnpj[8:12]}-{cnpj[12:]}'
    return cnpj


class Supplier(TenantMixin):
    """
    Cadastro de fornecedores.
    
    O CNPJ é usado para match automático em importação de NF-e.
    Cada tenant pode ter seu próprio cadastro do mesmo fornecedor,
    permitindo condições comerciais diferentes por empresa.
    
    Attributes:
        cnpj: CNPJ do fornecedor (único por tenant)
        company_name: Razão social
        trade_name: Nome fantasia
        state_registration: Inscrição estadual
        email: E-mail de contato
        phone: Telefone
        contact_name: Nome do contato principal
        payment_terms: Condições de pagamento
        lead_time_days: Prazo médio de entrega em dias
        minimum_order: Valor mínimo de pedido
        address: Endereço completo
        city: Cidade
        state: Estado (UF)
        zip_code: CEP
        notes: Observações gerais
        is_active: Se o fornecedor está ativo
        
    Example:
        >>> supplier = Supplier.objects.create(
        ...     tenant=tenant,
        ...     cnpj='12345678000199',
        ...     company_name='Fornecedor LTDA',
        ...     trade_name='Fornecedor',
        ... )
    """
    
    cnpj = models.CharField(
        max_length=18,
        validators=[validate_cnpj],
        verbose_name='CNPJ',
        help_text='CNPJ do fornecedor (com ou sem formatação)'
    )
    company_name = models.CharField(
        max_length=200,
        verbose_name='Razão Social'
    )
    trade_name = models.CharField(
        max_length=200,
        blank=True,
        verbose_name='Nome Fantasia'
    )
    state_registration = models.CharField(
        max_length=20,
        blank=True,
        verbose_name='Inscrição Estadual'
    )
    
    # Contato
    email = models.EmailField(blank=True, verbose_name='E-mail')
    phone = models.CharField(max_length=20, blank=True, verbose_name='Telefone')
    contact_name = models.CharField(
        max_length=100,
        blank=True,
        verbose_name='Nome do Contato'
    )
    
    # Condições Comerciais
    payment_terms = models.CharField(
        max_length=100,
        blank=True,
        verbose_name='Condições de Pagamento',
        help_text='Ex: 30/60/90 DDL, À vista, etc.'
    )
    lead_time_days = models.PositiveIntegerField(
        default=7,
        verbose_name='Prazo de Entrega (dias)',
        help_text='Prazo médio em dias úteis'
    )
    minimum_order = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name='Pedido Mínimo (R$)'
    )
    
    # Endereço
    address = models.TextField(blank=True, verbose_name='Endereço')
    city = models.CharField(max_length=100, blank=True, verbose_name='Cidade')
    state = models.CharField(
        max_length=2,
        blank=True,
        verbose_name='UF',
        validators=[RegexValidator(r'^[A-Z]{2}$', 'UF deve ter 2 letras maiúsculas')]
    )
    zip_code = models.CharField(
        max_length=9,
        blank=True,
        verbose_name='CEP'
    )
    
    # Metadata
    notes = models.TextField(blank=True, verbose_name='Observações')
    is_active = models.BooleanField(default=True, verbose_name='Ativo')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = 'Fornecedor'
        verbose_name_plural = 'Fornecedores'
        unique_together = ['tenant', 'cnpj']
        ordering = ['trade_name', 'company_name']
        indexes = [
            models.Index(fields=['tenant', 'cnpj']),
            models.Index(fields=['tenant', 'is_active']),
        ]
    
    def __str__(self) -> str:
        name = self.trade_name or self.company_name
        return f'{name} ({self.formatted_cnpj})'
    
    def clean(self) -> None:
        """Valida e normaliza dados antes de salvar."""
        super().clean()
        # Normaliza CNPJ (remove formatação para armazenar)
        if self.cnpj:
            self.cnpj = re.sub(r'[^0-9]', '', self.cnpj)
    
    def save(self, *args, **kwargs) -> None:
        self.full_clean()
        super().save(*args, **kwargs)
    
    @property
    def formatted_cnpj(self) -> str:
        """Retorna CNPJ formatado para exibição."""
        return format_cnpj(self.cnpj)
    
    @property
    def display_name(self) -> str:
        """Retorna nome para exibição (fantasia ou razão social)."""
        return self.trade_name or self.company_name
    
    @classmethod
    def get_or_create_from_nfe(
        cls,
        tenant,
        cnpj: str,
        company_name: str,
        state_registration: str = '',
        **extra_fields
    ) -> tuple['Supplier', bool]:
        """
        Obtém ou cria fornecedor a partir de dados da NF-e.
        
        Args:
            tenant: Tenant atual
            cnpj: CNPJ do emitente
            company_name: Razão social do emitente
            state_registration: IE do emitente
            **extra_fields: Campos adicionais (trade_name, address, etc.)
            
        Returns:
            Tuple (supplier, created)
        """
        cnpj_clean = re.sub(r'[^0-9]', '', cnpj)
        
        supplier, created = cls.objects.get_or_create(
            tenant=tenant,
            cnpj=cnpj_clean,
            defaults={
                'company_name': company_name[:200],
                'state_registration': state_registration[:20] if state_registration else '',
                **extra_fields
            }
        )
        
        return supplier, created


class SupplierProductMap(TenantMixin):
    """
    Mapeamento entre código do produto no fornecedor e produto interno.
    
    Este modelo é essencial para a deduplicação de produtos durante
    importação de NF-e. Quando um produto é importado de um fornecedor,
    o sistema registra a associação entre o código do fornecedor (cProd)
    e o produto/variante interno.
    
    Na próxima importação do mesmo fornecedor, o sistema usa este
    mapeamento para identificar automaticamente o produto.
    
    Attributes:
        supplier: Fornecedor relacionado
        product: Produto interno vinculado
        variant: Variante do produto (se aplicável)
        supplier_sku: Código do produto no fornecedor (cProd da NF-e)
        supplier_ean: EAN informado pelo fornecedor (pode diferir do nosso)
        supplier_name: Descrição original na NF-e (xProd)
        last_cost: Último custo de compra
        last_purchase: Data da última compra
        
    Example:
        >>> mapping = SupplierProductMap.objects.create(
        ...     tenant=tenant,
        ...     supplier=supplier,
        ...     product=product,
        ...     supplier_sku='ABC123',
        ...     supplier_name='PRODUTO X',
        ...     last_cost=Decimal('15.50'),
        ... )
    """
    
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.CASCADE,
        related_name='product_mappings',
        verbose_name='Fornecedor'
    )
    product = models.ForeignKey(
        'products.Product',
        on_delete=models.CASCADE,
        related_name='supplier_mappings',
        verbose_name='Produto'
    )
    variant = models.ForeignKey(
        'products.ProductVariant',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='supplier_mappings',
        verbose_name='Variação'
    )
    
    # Dados do fornecedor
    supplier_sku = models.CharField(
        max_length=60,
        verbose_name='Código do Fornecedor',
        help_text='cProd da NF-e'
    )
    supplier_ean = models.CharField(
        max_length=14,
        blank=True,
        verbose_name='EAN do Fornecedor',
        help_text='cEAN da NF-e (pode diferir do código interno)'
    )
    supplier_name = models.CharField(
        max_length=120,
        blank=True,
        verbose_name='Descrição do Fornecedor',
        help_text='xProd da NF-e'
    )
    
    # Histórico de compras
    last_cost = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        null=True,
        blank=True,
        verbose_name='Último Custo'
    )
    last_purchase = models.DateField(
        null=True,
        blank=True,
        verbose_name='Última Compra'
    )
    total_purchased = models.PositiveIntegerField(
        default=0,
        verbose_name='Total Comprado',
        help_text='Quantidade total já comprada deste fornecedor'
    )
    
    # Metadata
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = 'Mapeamento de Produto'
        verbose_name_plural = 'Mapeamentos de Produtos'
        unique_together = ['tenant', 'supplier', 'supplier_sku']
        ordering = ['-last_purchase', 'supplier_name']
        indexes = [
            models.Index(fields=['tenant', 'supplier', 'supplier_sku']),
            models.Index(fields=['tenant', 'supplier_ean']),
        ]
    
    def __str__(self) -> str:
        target = self.variant.display_name if self.variant else self.product.name
        return f'{self.supplier_sku} ({self.supplier.display_name}) → {target}'
    
    def clean(self) -> None:
        """Valida consistência do mapeamento."""
        super().clean()
        
        # Se variant está definido, deve pertencer ao product
        if self.variant and self.product:
            if self.variant.product_id != self.product_id:
                raise ValidationError({
                    'variant': 'A variação deve pertencer ao produto selecionado.'
                })
    
    def save(self, *args, **kwargs) -> None:
        self.full_clean()
        super().save(*args, **kwargs)
    
    def update_purchase_info(
        self,
        cost: Decimal,
        quantity: int,
        purchase_date=None
    ) -> None:
        """
        Atualiza informações de compra após importação.
        
        Args:
            cost: Custo unitário da compra
            quantity: Quantidade comprada
            purchase_date: Data da compra (default: hoje)
        """
        from django.utils import timezone
        
        self.last_cost = cost
        self.last_purchase = purchase_date or timezone.now().date()
        self.total_purchased += quantity
        self.save(update_fields=['last_cost', 'last_purchase', 'total_purchased', 'updated_at'])
    
    @classmethod
    def find_mapping(
        cls,
        tenant,
        supplier: Supplier,
        supplier_sku: str
    ) -> Optional['SupplierProductMap']:
        """
        Busca mapeamento existente.
        
        Args:
            tenant: Tenant atual
            supplier: Fornecedor
            supplier_sku: Código do produto no fornecedor
            
        Returns:
            Mapeamento encontrado ou None
        """
        return cls.objects.filter(
            tenant=tenant,
            supplier=supplier,
            supplier_sku=supplier_sku,
            is_active=True
        ).select_related('product', 'variant').first()
