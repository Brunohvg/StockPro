from decimal import Decimal

import pytest

from apps.core.services import StockService
from apps.reports.services import BIService
from tests.factories import ProductFactory


@pytest.mark.django_db
class TestBILogic:
    def test_abc_classification(self, tenant):
        """Verify that products are correctly classified into A, B, and C tiers"""
        # A Tier (High value) - 80% of total value
        p1 = ProductFactory(tenant=tenant, current_stock=10, avg_unit_cost=80.0) # 800

        # B Tier (Medium value) - 15% (cumulative 95%)
        p2 = ProductFactory(tenant=tenant, current_stock=10, avg_unit_cost=15.0) # 150

        # C Tier (Low value) - 5%
        p3 = ProductFactory(tenant=tenant, current_stock=10, avg_unit_cost=5.0)  # 50

        # Total = 1000

        abc = BIService.calculate_abc_analysis(tenant)

        assert abc[f"P-{p1.id}"] == "A"
        assert abc[f"P-{p2.id}"] == "B"
        assert abc[f"P-{p3.id}"] == "C"

    def test_stock_health_dead_stock(self, tenant, user):
        """Verify that items with no OUT movements are flagged as dead stock"""
        # Product with recent OUT movement (Not dead)
        # Use 0 and then IN to ensure correct state if factory has side effects
        p_active = ProductFactory(tenant=tenant, current_stock=0, avg_unit_cost=100.0)
        StockService.create_movement(
            tenant=tenant, user=user, movement_type='IN',
            quantity=10, product=p_active, reason="Initial"
        )
        StockService.create_movement(
            tenant=tenant, user=user, movement_type='OUT',
            quantity=1, product=p_active, reason="Sale"
        )

        # Product with ONLY IN movement (Is dead stock)
        p_dead = ProductFactory(tenant=tenant, current_stock=0, avg_unit_cost=100.0)
        StockService.create_movement(
            tenant=tenant, user=user, movement_type='IN',
            quantity=10, product=p_dead, reason="Purchase"
        )

        health = BIService.get_inventory_health(tenant)

        # Check if p_dead is in dead stock list
        dead_ids = [item['item'].id for item in health['dead_stock'] if item['type'] == 'product']
        assert p_dead.id in dead_ids
        assert p_active.id not in dead_ids

        # p_dead: 10 units * 100 cost = 1000.0
        assert health['dead_stock_value'] == Decimal('1000.0')

    def test_empty_inventory_bi(self, tenant):
        """Verify BI service handles empty inventory gracefully"""
        abc = BIService.calculate_abc_analysis(tenant)
        assert abc == {}

        health = BIService.get_inventory_health(tenant)
        assert health['item_count'] == 0
        assert health['dead_stock_value'] == 0
