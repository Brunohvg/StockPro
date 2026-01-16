from django.db import transaction
from django.core.exceptions import ValidationError
from decimal import Decimal
from .models import Product, StockMovement
import uuid

class StockService:
    @staticmethod
    @transaction.atomic
    def create_movement(tenant, user, product_sku, movement_type, quantity, reason="",
                       source="MANUAL", unit_cost=None, source_doc=None,
                       batch_info=None, external_reference=None, idempotency_key=None):
        """
        Creates a stock movement atomically with full audit trail, within a Tenant.
        """
        try:
            product = Product.objects.select_for_update().get(tenant=tenant, sku=product_sku)
        except Product.DoesNotExist:
            raise ValidationError(f"Produto {product_sku} não encontrado para esta unidade.")

        if not product.is_active:
             raise ValidationError(f"Produto {product_sku} está inativo e não pode ser movimentado.")

        if movement_type not in dict(StockMovement.MOVEMENT_TYPES):
            raise ValidationError("Tipo de movimentação inválido.")

        if quantity <= 0:
            raise ValidationError("A quantidade deve ser positiva.")

        if idempotency_key and StockMovement.objects.filter(idempotency_key=idempotency_key).exists():
            raise ValidationError(f"Movimentação duplicada detectada (Idempotency Key: {idempotency_key})")

        balance_before = product.current_stock
        balance_after = balance_before

        if movement_type == 'IN':
            balance_after += quantity
            # Update Average Cost if cost provided
            if unit_cost:
                unit_cost = Decimal(str(unit_cost))
                qty_dec = Decimal(str(quantity))
                balance_before_dec = Decimal(str(balance_before))

                total_value_before = (product.avg_unit_cost or Decimal('0')) * balance_before_dec
                total_value_added = unit_cost * qty_dec
                new_total_qty = balance_before_dec + qty_dec

                if new_total_qty > 0:
                     product.avg_unit_cost = (total_value_before + total_value_added) / new_total_qty

        elif movement_type == 'OUT':
            balance_after -= quantity
            from .models import SystemSetting
            settings = SystemSetting.get_settings(tenant)
            if balance_after < 0 and settings.prevent_negative_stock:
                raise ValidationError(f"Estoque insuficiente. Disponível: {balance_before}")

        elif movement_type == 'ADJUSTMENT':
             # Treat Adjustment as 'Add' for POSITIVE quantity in this simple logic.
             # User must use OUT for negative adjustment in the UI logic or we need a sign.
             # V2 Decision: ADJUSTMENT is purely additive logic here. 'OUT' type uses 'Adjustment' reason for losses.
             balance_after += quantity

        product.current_stock = balance_after
        product.save()

        movement = StockMovement.objects.create(
            user=user,
            product=product,
            type=movement_type,
            quantity=quantity,
            balance_before=balance_before,
            balance_after=balance_after,
            reason=reason,
            source=source,
            source_doc=source_doc,
            unit_cost=unit_cost,
            batch_info=batch_info,
            external_reference=external_reference,
            idempotency_key=idempotency_key or uuid.uuid4()
        )

        return movement
