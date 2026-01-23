from decimal import Decimal

from django.utils import timezone

from apps.inventory.models import StockMovement
from apps.products.models import Product, ProductType, ProductVariant


class BIService:
    @staticmethod
    def calculate_abc_analysis(tenant):
        """
        ABC Classification based on immobilized value (Avg Cost * Current Stock).
        Returns a dictionary with product IDs as keys and 'A', 'B', or 'C' as values.
        """
        # Get all products/variants with stock and value
        items = []

        # Simple products
        simple_products = Product.objects.filter(
            tenant=tenant,
            product_type=ProductType.SIMPLE,
            is_active=True
        ).exclude(current_stock=0)
        for p in simple_products:
            val = Decimal(p.current_stock or 0) * Decimal(p.avg_unit_cost or 0)
            if val > 0:
                items.append({'id': f"P-{p.id}", 'value': val, 'obj': p})

        # Variants
        variants = ProductVariant.objects.filter(
            tenant=tenant,
            is_active=True
        ).exclude(current_stock=0)
        for v in variants:
            val = Decimal(v.current_stock or 0) * Decimal(v.avg_unit_cost or 0)
            if val > 0:
                items.append({'id': f"V-{v.id}", 'value': val, 'obj': v})

        if not items:
            return {}

        # Sort by value descending
        items.sort(key=lambda x: x['value'], reverse=True)
        total_value = sum(item['value'] for item in items)

        cumulative_value = Decimal('0')
        classification = {}

        for item in items:
            cumulative_value += item['value']
            percent = (cumulative_value / total_value) * 100

            if percent <= 80:
                grade = 'A'
            elif percent <= 95:
                grade = 'B'
            else:
                grade = 'C'

            classification[item['id']] = grade

        return classification

    @staticmethod
    def get_inventory_health(tenant):
        """
        Identifies 'Dead Stock' (items with no OUT movements in last 60 days).
        Returns a list of items and health summary.
        """
        sixty_days_ago = timezone.now() - timezone.timedelta(days=60)

        # Find product units that had OUT movements
        moved_skus = StockMovement.objects.filter(
            tenant=tenant,
            type='OUT',
            created_at__gte=sixty_days_ago
        ).values_list('product_id', 'variant_id')

        moved_product_ids = {p[0] for p in moved_skus if p[0]}
        moved_variant_ids = {p[1] for p in moved_skus if p[1]}

        dead_stock = []

        # Check simple products
        candidates_p = Product.objects.filter(
            tenant=tenant,
            product_type=ProductType.SIMPLE,
            is_active=True,
            current_stock__gt=0
        ).exclude(id__in=moved_product_ids)

        for p in candidates_p:
            dead_stock.append({'type': 'product', 'item': p, 'value': p.total_stock_value})

        # Check variants
        candidates_v = ProductVariant.objects.filter(
            tenant=tenant,
            is_active=True,
            current_stock__gt=0
        ).exclude(id__in=moved_variant_ids)

        for v in candidates_v:
            dead_stock.append({'type': 'variant', 'item': v, 'value': v.total_stock_value})

        return {
            'dead_stock': dead_stock,
            'dead_stock_value': sum(item['value'] for item in dead_stock),
            'item_count': len(dead_stock)
        }
