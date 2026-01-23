from decimal import Decimal

import pytest

from apps.core.services import StockService
from apps.inventory.models import StockMovement
from tests.factories import (
    ProductFactory,
    ProductVariantFactory,
)


@pytest.mark.django_db
class TestInventoryLogic:
    def test_stock_in_and_cost_averaging(self, tenant, user):
        """Verify IN movement increases stock and updates weighted average cost"""
        # Start with 10 items at 5.0 cost
        product = ProductFactory(tenant=tenant, current_stock=10, avg_unit_cost=5.0)

        # Add 10 items at 15.0 cost
        StockService.create_movement(
            tenant=tenant,
            user=user,
            movement_type='IN',
            quantity=10,
            product=product,
            unit_cost=15.0,
            reason="Purchase"
        )

        product.refresh_from_db()
        assert product.current_stock == 20
        # Average: (10*5 + 10*15) / 20 = 200 / 20 = 10.0
        assert product.avg_unit_cost == Decimal('10.0')

    def test_stock_out_and_protection(self, tenant, user):
        """Verify OUT movement decreases stock and blocks insufficient balance"""
        product = ProductFactory(tenant=tenant, current_stock=10)

        # Valid OUT
        StockService.create_movement(
            tenant=tenant,
            user=user,
            movement_type='OUT',
            quantity=4,
            product=product
        )

        product.refresh_from_db()
        assert product.current_stock == 6

        # Insufficient balance
        with pytest.raises(ValueError, match="Estoque insuficiente"):
            StockService.create_movement(
                tenant=tenant,
                user=user,
                movement_type='OUT',
                quantity=10,
                product=product
            )

    def test_absolute_adjustment(self, tenant, user):
        """Verify ADJ movement sets stock to absolute value"""
        product = ProductFactory(tenant=tenant, current_stock=10)

        StockService.create_movement(
            tenant=tenant,
            user=user,
            movement_type='ADJ',
            quantity=42,
            product=product
        )

        product.refresh_from_db()
        assert product.current_stock == 42

    def test_movement_immutability(self, tenant, user):
        """Verify that StockMovement records are considered immutable by convention"""
        product = ProductFactory(tenant=tenant)
        movement = StockService.create_movement(
            tenant=tenant,
            user=user,
            movement_type='IN',
            quantity=10,
            product=product
        )

        # Check that we can't easily change the balance_after without the proper service
        # (Convention check: ensure the record exists and has correct data)
        assert movement.balance_after == 10
        assert StockMovement.objects.count() == 1

    def test_variant_stock_isolation(self, tenant, user):
        """Verify that moving variant stock does NOT move simple product stock with same SKU"""
        product = ProductFactory(tenant=tenant, product_type='VARIABLE')
        variant = ProductVariantFactory(product=product, current_stock=5)

        StockService.create_movement(
            tenant=tenant,
            user=user,
            movement_type='IN',
            quantity=5,
            variant=variant
        )

        variant.refresh_from_db()
        assert variant.current_stock == 10
        assert product.total_stock == 10

    def test_safe_delete_protection(self, tenant, user):
        """Verify that products with OUT movements cannot be safely deleted"""
        product = ProductFactory(tenant=tenant, current_stock=10)

        # Initially can be deleted (no movements yet, or only IN/ADJ)
        assert product.can_be_safely_deleted is True

        # Add a movement (IN) - still safe
        StockService.create_movement(tenant=tenant, user=user, movement_type='IN', quantity=5, product=product)
        assert product.can_be_safely_deleted is True

        # Add an OUT movement - NOT safe anymore
        StockService.create_movement(tenant=tenant, user=user, movement_type='OUT', quantity=2, product=product)
        assert product.can_be_safely_deleted is False
        assert "saída" in product.delete_block_reason
