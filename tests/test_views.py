import pytest
from django.urls import reverse

from tests.factories import ProductFactory


@pytest.mark.django_db
class TestUISmoke:
    def test_dashboard_view(self, client, tenant, user, member):
        tenant.is_active = True
        tenant.save()
        client.force_login(user)
        url = reverse('reports:dashboard')
        response = client.get(url)
        assert response.status_code == 200
        assert b"Dashboard" in response.content

    def test_inventory_reports_view(self, client, tenant, user, member):
        tenant.is_active = True
        tenant.save()
        client.force_login(user)
        # Create some data for BI
        ProductFactory(tenant=tenant, current_stock=10, avg_unit_cost=10.0)
        url = reverse('reports:inventory_reports')
        response = client.get(url)
        assert response.status_code == 200
        assert b"ABC" in response.content

    def test_product_list_view(self, client, tenant, user, member):
        tenant.is_active = True
        tenant.save()
        client.force_login(user)
        url = reverse('products:product_list')
        response = client.get(url)
        assert response.status_code == 200
        assert b"Produtos" in response.content

    def test_movement_list_view(self, client, tenant, user, member):
        tenant.is_active = True
        tenant.save()
        client.force_login(user)
        url = reverse('inventory:movement_list')
        response = client.get(url)
        assert response.status_code == 200
        assert b"Moviment" in response.content

    def test_location_list_view(self, client, tenant, user, member):
        tenant.is_active = True
        tenant.save()
        client.force_login(user)
        url = reverse('inventory:location_list')
        response = client.get(url)
        assert response.status_code == 200
        assert b"Local" in response.content
