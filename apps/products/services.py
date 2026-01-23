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

        # Convert each SIMPLE product to a variant
        for product in products:
            parsed = self._parse_product_name(product.name)
            attr_value = parsed[2] if parsed else product.name

            # Determina se mantém SKU antigo ou gera novo
            # Se o SKU antigo for o padrão PROD-..., forçamos a geração do novo padrão [PAI]-[ATTR]
            old_sku = product.sku
            new_sku = old_sku
            if old_sku.startswith('PROD-') or '-' not in old_sku:
                new_sku = None # Força o save() do ProductVariant a gerar o padrão baseado no PAI

            # Create variant
            variant = ProductVariant.objects.create(
                tenant=self.tenant,
                product=parent,
                sku=new_sku,
                name=product.name,
                barcode=product.barcode,
                current_stock=product.current_stock,
                minimum_stock=product.minimum_stock,
                avg_unit_cost=product.avg_unit_cost,
                photo=product.photo,
                is_active=True,
            )

            # Create attribute value
            VariantAttributeValue.objects.create(
                variant=variant,
                attribute_type=attr_type,
                value=attr_value.title()
            )

            # Migrate stock movements from product to variant
            StockMovement.objects.filter(product=product).update(
                product=None,
                variant=variant
            )

            # Delete the original SIMPLE product
            product.delete()

        return parent
