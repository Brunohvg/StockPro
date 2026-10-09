"""
Product Consolidation Service - Intelligent product grouping suggestions
"""
import re
from collections import defaultdict

from django.db import transaction

from apps.inventory.models import StockMovement

from .models import AttributeType, Product, ProductType, ProductVariant, VariantAttributeValue


class ConsolidationService:
    """
    Service for detecting and consolidating SIMPLE products that should be variants.

    Detects patterns like:
    - "AMIGURUMI - COR 6006" and "AMIGURUMI - COR 8013" → Group "AMIGURUMI" with attr "Cor"
    - "DUNA - COR 2012" and "DUNA - COR 7144" → Group "DUNA" with attr "Cor"
    """

    # Common attribute patterns in Brazilian product names
    ATTR_PATTERNS = [
        (r'\s*-\s*COR\s+(.+)$', 'Cor'),
        (r'\s*COR\s+(.+)$', 'Cor'),
        (r'\s*-\s*TAM\s+(.+)$', 'Tamanho'),
        (r'\s*TAMANHO\s+(.+)$', 'Tamanho'),
        (r'\s*(.+)\s+VOLTS?$', 'Voltagem'),
        (r'\s*(\d+V)$', 'Voltagem'),
        # Suffixes with codes before technical specs (common in textiles)
        (r'\s+([A-Z0-9]+)\s+L\.\s?\d+', 'Variação'),
        (r'\s+([A-Z0-9]+)\s+MTS?', 'Variação'),
        # Trailing codes
        (r'\s*-\s*([A-Z0-9]+)$', 'Código'),
    ]

    def __init__(self, tenant):
        self.tenant = tenant

    def detect_candidates(self):
        """
        Detect SIMPLE products that could be grouped as variants.

        Returns list of candidate groups:
        [
            {
                'parent_name': 'AMIGURUMI',
                'attribute': 'Cor',
                'products': [Product, Product, ...],
                'count': 5
            },
            ...
        ]
        """
        simple_products = Product.objects.filter(
            tenant=self.tenant,
            product_type=ProductType.SIMPLE,
            is_active=True
        ).order_by('name')

        # Group products by base name (Regex first)
        groups = defaultdict(list)
        unmatched_products = []

        for product in simple_products:
            parsed = self._parse_product_name(product.name)
            if parsed:
                base_name, attr_type, attr_value = parsed
                groups[(base_name, attr_type)].append({
                    'product': product,
                    'attr_value': attr_value
                })
            else:
                unmatched_products.append(product)

        # Fallback: Group by Longest Common Prefix (Useful for any product type)
        # We look for products that share the first 70%+ of their name
        if unmatched_products:
            processed_pks = set()
            for i, p1 in enumerate(unmatched_products):
                if p1.pk in processed_pks: continue

                group_pks = {p1.pk}
                p1_name = p1.name.upper()

                for j in range(i + 1, len(unmatched_products)):
                    p2 = unmatched_products[j]
                    if p2.pk in processed_pks: continue

                    p2_name = p2.name.upper()
                    # Encontra prefixo comum
                    prefix = ""
                    for char1, char2 in zip(p1_name, p2_name):
                        if char1 == char2: prefix += char1
                        else: break

                    # Se o prefixo for longo o suficiente (ex: 10 chars ou 50% do nome)
                    if len(prefix) >= 10:
                        group_pks.add(p2.pk)

                if len(group_pks) >= 2:
                    current_group = [p for p in unmatched_products if p.pk in group_pks]
                    # Tenta descobrir o atributo via IA para este cluster específico
                    base_name = self._find_common_prefix([p.name for p in current_group])

                    groups[(base_name, 'Variação')].extend([
                        {'product': p, 'attr_value': p.name[len(base_name):].strip() or 'Padrão'}
                        for p in current_group
                    ])
                    processed_pks.update(group_pks)

        # Filter to groups with 2+ products
        candidates = []
        for (base_name, attr_type), items in groups.items():
            if len(items) >= 2:
                candidates.append({
                    'parent_name': base_name.strip(),
                    'attribute': attr_type,
                    'products': [item['product'] for item in items],
                    'attr_values': {item['product'].pk: item['attr_value'] for item in items},
                    'count': len(items),
                    'total_stock': sum(p['product'].current_stock or 0 for p in items),
                    'total_value': sum(p['product'].total_stock_value or 0 for p in items),
                })

        # Sort by count (most impactful first)
        candidates.sort(key=lambda x: x['count'], reverse=True)

        return candidates

    def _parse_product_name(self, name):
        """
        Parse a product name to extract base name and attribute.

        Returns: (base_name, attr_type, attr_value) or None
        """
        name_upper = name.upper().strip()

        for pattern, attr_type in self.ATTR_PATTERNS:
            match = re.search(pattern, name_upper, re.IGNORECASE)
            if match:
                attr_value = match.group(1).strip()
                base_name = name_upper[:match.start()].strip()
                if base_name and attr_value:
                    return (base_name, attr_type, attr_value)

        return None

    def _find_common_prefix(self, names):
        """Calcula o prefixo comum entre uma lista de nomes"""
        if not names: return ""
        s1 = min(names)
        s2 = max(names)
        for i, c in enumerate(s1):
            if c != s2[i]:
                return s1[:i].strip()
        return s1

    @transaction.atomic
    def consolidate(self, parent_name, attribute_name, product_ids):
        """
        Consolidate SIMPLE products into a VARIABLE product with variants.

        Args:
            parent_name: Name for the new parent product
            attribute_name: Name of the attribute type (e.g., "Cor")
            product_ids: List of Product IDs to consolidate

        Returns:
            The new parent Product
        """
        products = Product.objects.filter(
            tenant=self.tenant,
            pk__in=product_ids,
            product_type=ProductType.SIMPLE
        )

        if products.count() < 2:
            raise ValueError("Precisa de pelo menos 2 produtos para consolidar")

        # Get or create attribute type
        attr_type, _ = AttributeType.objects.get_or_create(
            tenant=self.tenant,
            name=attribute_name
        )

        # Create parent VARIABLE product
        first_product = products.first()
        parent = Product.objects.create(
            tenant=self.tenant,
            name=parent_name,
            product_type=ProductType.VARIABLE,
            sku=None,  # Deixa o save() gerar o VAR-CAT-ID padronizado
            category=first_product.category,
            brand=first_product.brand,
            default_supplier=first_product.default_supplier,
            uom=first_product.uom,
            is_active=True,
        )

        # Cada produto SIMPLE vira variação do pai: a variação existente é
        # reaproveitada (mesmo SKU, saldo, custo, lotes e histórico).
        for product in products:
            parsed = self._parse_product_name(product.name)
            attr_value = parsed[2] if parsed else product.name

            variant = product.variants.select_for_update().first()
            if variant is None:  # estado inesperado: cria a variação padrão
                variant = ProductVariant.objects.create(
                    tenant=self.tenant, product=product, sku=product.sku, name="Padrão")

            variant.product = parent
            variant.name = product.name
            variant.is_active = True
            if not variant.photo and product.photo:
                variant.photo = product.photo
            variant.save()

            VariantAttributeValue.objects.update_or_create(
                variant=variant,
                attribute_type=attr_type,
                defaults={'value': attr_value.title()},
            )

            # Referências ao produto antigo passam para o pai antes de removê-lo
            StockMovement.objects.filter(product=product).update(product=parent)
            from apps.partners.models import SupplierProductMap
            SupplierProductMap.objects.filter(product=product).update(product=parent)
            from apps.inventory.models import InventoryAuditItem
            InventoryAuditItem.objects.filter(product=product).update(product=parent)

            # Produto SIMPLE agora vazio (sem variações nem movimentações)
            product.delete()

        return parent


class ArchiveError(Exception):
    pass


class ProductArchiveService:
    """
    Remoção segura de produtos e variações.

    - Sem nenhuma movimentação: exclusão definitiva (não há histórico a perder).
    - Com movimentações: arquiva (is_active=False). O histórico é preservado e,
      se pedido, o saldo é zerado com um ajuste registrado ("Arquivamento").
    """

    ARCHIVE_REASON = "Arquivamento do produto"

    @staticmethod
    def variant_has_movements(variant):
        return StockMovement.objects.filter(variant=variant).exists()

    @classmethod
    def has_movements(cls, product):
        return StockMovement.objects.filter(variant__product=product).exists() or \
            StockMovement.objects.filter(product=product).exists()

    @classmethod
    def _zero_variant(cls, variant, user, reason):
        from apps.core.services import StockService
        if variant.current_stock and variant.current_stock > 0:
            StockService.create_movement(
                tenant=variant.tenant, user=user, movement_type='ADJ', quantity=0,
                variant=variant, reason=reason, source='ARCHIVE',
            )

    @classmethod
    @transaction.atomic
    def remove_product(cls, product, user, zero_stock=False):
        """Retorna 'deleted' ou 'archived'."""
        product = Product.objects.select_for_update().get(pk=product.pk)
        if not cls.has_movements(product):
            product.delete()
            return 'deleted'
        variants = list(product.variants.select_for_update())
        if zero_stock:
            for variant in variants:
                cls._zero_variant(variant, user, cls.ARCHIVE_REASON)
        ProductVariant.objects.filter(pk__in=[v.pk for v in variants]).update(is_active=False)
        Product.objects.filter(pk=product.pk).update(is_active=False)
        return 'archived'

    @classmethod
    @transaction.atomic
    def remove_variant(cls, variant, user, zero_stock=False):
        variant = ProductVariant.objects.select_for_update().get(pk=variant.pk)
        if not cls.variant_has_movements(variant):
            variant.delete()
            return 'deleted'
        if zero_stock:
            cls._zero_variant(variant, user, "Arquivamento da variação")
        ProductVariant.objects.filter(pk=variant.pk).update(is_active=False)
        return 'archived'

    @classmethod
    @transaction.atomic
    def restore_product(cls, product):
        from apps.tenants.models import Tenant
        tenant = Tenant.objects.select_for_update().get(pk=product.tenant_id)
        product = Product.objects.select_for_update().get(pk=product.pk)
        if product.is_active:
            return product
        variants = product.variants.all()
        plan = tenant.plan
        if plan and plan.max_products:
            needed = variants.count() or 1
            if tenant.products_count + needed > plan.max_products:
                raise ArchiveError(
                    f"Limite de {plan.max_products} produtos do plano '{plan.display_name}' atingido. "
                    "Arquive outro produto ou faça upgrade para reativar este.")
        variants.update(is_active=True)
        Product.objects.filter(pk=product.pk).update(is_active=True)
        product.refresh_from_db()
        return product
