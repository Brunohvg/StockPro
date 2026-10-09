"""Regressão do cadastro de produto com lote e validade inicial."""
import pytest
from django.test import Client

from apps.accounts.models import TenantMembership
from apps.inventory.models import StockLot, StockMovement
from apps.products.models import Product
from tests.factories import TenantFactory, UserFactory


@pytest.mark.django_db
def test_cadastro_catalogo_cria_lote_e_movimentacao():
    tenant = TenantFactory()
    tenant.plan.max_products = 1000
    tenant.plan.save()
    user = UserFactory()
    TenantMembership.objects.create(user=user, tenant=tenant, role='OWNER')
    c = Client()
    c.force_login(user)
    response = c.post('/products/add/', {
        'name': 'Produto com validade', 'product_type': 'SIMPLE',
        'sku': 'CAD-LOTE-001', 'uom': 'UN', 'is_active': 'on',
        'tracks_expiry': 'on', 'current_stock': '5',
        'minimum_stock': '1', 'avg_unit_cost': '3.50',
        'initial_lot_number': 'LOTE-A',
        'initial_manufacture_date': '2026-09-01',
        'initial_expiry_date': '2027-04-01',
    })
    assert response.status_code == 302
    product = Product.objects.get(tenant=tenant, sku='CAD-LOTE-001')
    variant = product.variants.get()
    assert variant.current_stock == 5
    assert StockLot.objects.get(tenant=tenant, variant=variant).lot_number == 'LOTE-A'
    assert StockMovement.objects.filter(tenant=tenant, variant=variant, type='IN').count() == 1


@pytest.mark.django_db
def test_catalogo_exige_validade_ao_criar_estoque_controlado():
    tenant = TenantFactory()
    user = UserFactory()
    TenantMembership.objects.create(user=user, tenant=tenant, role='OWNER')
    c = Client()
    c.force_login(user)
    response = c.post('/products/add/', {
        'name': 'Sem vencimento', 'product_type': 'SIMPLE',
        'sku': 'SEM-VALIDADE-001', 'uom': 'UN', 'is_active': 'on',
        'tracks_expiry': 'on', 'current_stock': '5', 'minimum_stock': '0',
    })
    assert response.status_code == 200
    assert not Product.objects.filter(tenant=tenant, sku='SEM-VALIDADE-001').exists()
