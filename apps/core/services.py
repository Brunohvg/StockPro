"""
Stock Service - Business logic for inventory operations
"""
from django.db import transaction
from apps.products.models import Product
from apps.inventory.models import StockMovement


class StockService:
    @staticmethod
    @transaction.atomic
    def create_movement(tenant, user, product_sku, movement_type, quantity, reason='', source='MANUAL', unit_cost=None, source_doc=None):
        """Create a stock movement and update product stock"""
        product = Product.objects.select_for_update().get(tenant=tenant, sku=product_sku)

        # Calculate new stock
        if movement_type == 'IN':
            new_stock = product.current_stock + quantity
            if unit_cost:
                # Weighted average cost update
                total_current_value = (product.current_stock or 0) * (product.avg_unit_cost or 0)
                total_new_value = quantity * unit_cost
                if new_stock > 0:
                    product.avg_unit_cost = (total_current_value + total_new_value) / new_stock
        elif movement_type == 'OUT':
            new_stock = product.current_stock - quantity
            if new_stock < 0:
                raise ValueError(f"Estoque insuficiente para {product.sku}. Disponível: {product.current_stock}")
        elif movement_type == 'ADJ':
            new_stock = quantity  # Absolute adjustment
        else:
            raise ValueError(f"Tipo de movimento inválido: {movement_type}")

        product.current_stock = new_stock
        product.save()

        # Create immutable movement record
        movement = StockMovement.objects.create(
            tenant=tenant,
            product=product,
            user=user,
            type=movement_type,
            quantity=quantity,
            reason=reason,
            source=source,
            unit_cost=unit_cost,
            source_doc=source_doc
        )

        return movement
