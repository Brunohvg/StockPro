"""
Stock Service - Business logic for inventory operations (V10)
Suporta Product (SIMPLE) e ProductVariant (para VARIABLE)
"""
from django.db import transaction
from apps.products.models import Product, ProductVariant, ProductType
from apps.inventory.models import StockMovement


class StockService:
    @staticmethod
    @transaction.atomic
    def create_movement(
        tenant,
        user,
        movement_type,
        quantity,
        product=None,
        variant=None,
        product_sku=None,
        reason='',
        source='MANUAL',
        unit_cost=None,
        source_doc=None
    ):
        """
        Create a stock movement and update stock.

        Args:
            product: Product instance (for SIMPLE products)
            variant: ProductVariant instance (for VARIABLE products)
            product_sku: SKU string (auto-resolves to product or variant)
        """
        # Resolve by SKU if no direct reference
        if product_sku and not product and not variant:
            # Try variant first (more specific)
            variant = ProductVariant.objects.filter(tenant=tenant, sku=product_sku).first()
            if not variant:
                product = Product.objects.filter(tenant=tenant, sku=product_sku).first()

            if not product and not variant:
                raise ValueError(f"Produto/variação com SKU '{product_sku}' não encontrado.")

        # Determine target
        if variant:
            target = variant
            target_type = 'variant'
        elif product:
            if product.is_variable:
                raise ValueError(f"Produto '{product.sku}' é variável. Especifique uma variação.")
            target = product
            target_type = 'product'
        else:
            raise ValueError("Deve especificar product, variant ou product_sku.")

        # Lock for update
        if target_type == 'variant':
            target = ProductVariant.objects.select_for_update().get(pk=target.pk)
        else:
            target = Product.objects.select_for_update().get(pk=target.pk)

        # Calculate new stock
        if movement_type == 'IN':
            new_stock = target.current_stock + quantity
            if unit_cost:
                # Weighted average cost update
                total_current_value = (target.current_stock or 0) * (target.avg_unit_cost or 0)
                total_new_value = quantity * unit_cost
                if new_stock > 0:
                    target.avg_unit_cost = (total_current_value + total_new_value) / new_stock
        elif movement_type == 'OUT':
            new_stock = target.current_stock - quantity
            if new_stock < 0:
                raise ValueError(f"Estoque insuficiente para {target.sku}. Disponível: {target.current_stock}")
        elif movement_type == 'ADJ':
            new_stock = quantity  # Absolute adjustment
        else:
            raise ValueError(f"Tipo de movimento inválido: {movement_type}")

        target.current_stock = new_stock
        target.save()

        # Create immutable movement record
        movement_data = {
            'tenant': tenant,
            'user': user,
            'type': movement_type,
            'quantity': quantity,
            'balance_after': new_stock,
            'reason': reason,
            'source': source,
            'unit_cost': unit_cost,
            'source_doc': source_doc,
        }

        if target_type == 'variant':
            movement_data['variant'] = target
        else:
            movement_data['product'] = target

        movement = StockMovement.objects.create(**movement_data)
        return movement

    @staticmethod
    def get_stock_for_product(product):
        """Retorna estoque total para um produto (agregado se variável)"""
        if product.is_simple:
            return product.current_stock
        return sum(v.current_stock for v in product.variants.filter(is_active=True))

    @staticmethod
    def get_low_stock_items(tenant, threshold=None):
        """Retorna itens com estoque baixo"""
        low_stock = []

        # Simple products
        for p in Product.objects.filter(tenant=tenant, product_type=ProductType.SIMPLE, is_active=True):
            if p.current_stock <= p.minimum_stock:
                low_stock.append({'type': 'product', 'item': p})

        # Variants
        for v in ProductVariant.objects.filter(tenant=tenant, is_active=True):
            if v.current_stock <= v.minimum_stock:
                low_stock.append({'type': 'variant', 'item': v})

        return low_stock
