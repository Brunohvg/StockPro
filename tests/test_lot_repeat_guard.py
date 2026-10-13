"""Prevent duplicate catalog lot imports."""
import pytest
from django.core.files.base import ContentFile
from decimal import Decimal
from apps.inventory.tasks import process_csv_catalog_direct
from apps.products.models import Product
from tests.factories import ImportBatchFactory, TenantFactory, UserFactory


@pytest.mark.django_db
def test_same_lot_spreadsheet_twice_is_blocked():
    tenant, user = TenantFactory(), UserFactory()
    payload = b'nome,sku,estoque,lote,validade\nProduto Teste,LT-001,6,A,07/02/2027\nProduto Teste,LT-001,4,B,24/11/2026\n'
    def run():
        batch = ImportBatchFactory(tenant=tenant, user=user, type='CATALOG_DIRECT')
        batch.file.save('lotes.csv', ContentFile(payload))
        return process_csv_catalog_direct(batch)
    run()
    variant = Product.objects.get(tenant=tenant, sku='LT-001').variants.first()
    assert variant.current_stock == Decimal('10')
    result = run()
    assert 'evitar duplicidade' in result
    variant.refresh_from_db()
    assert variant.current_stock == Decimal('10')
