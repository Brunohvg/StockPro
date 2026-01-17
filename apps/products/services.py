"""
Product Consolidation Service - Intelligent product grouping suggestions
"""
import re
from collections import defaultdict
from django.db import transaction

from .models import Product, ProductVariant, AttributeType, VariantAttributeValue, ProductType
from apps.inventory.models import StockMovement


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

        # Group products by base name
        groups = defaultdict(list)

        for product in simple_products:
            parsed = self._parse_product_name(product.name)
            if parsed:
                base_name, attr_type, attr_value = parsed
                groups[(base_name, attr_type)].append({
                    'product': product,
                    'attr_value': attr_value
                })

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
            sku=f"VAR-{parent_name[:20].replace(' ', '-').upper()}",
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

            # Create variant
            variant = ProductVariant.objects.create(
                tenant=self.tenant,
                product=parent,
                sku=product.sku,
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
