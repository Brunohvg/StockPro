"""Homologation checks for lot export and label permissions."""
import csv
import io
import pytest
from django.test import Client
from apps.accounts.models import TenantMembership
from apps.products.models import Product
from tests.factories import TenantFactory, UserFactory


@pytest.mark.django_db
def test_lot_export_is_admin_only():
    tenant = TenantFactory()
    user = UserFactory()
    TenantMembership.objects.create(user=user, tenant=tenant, role='OPERATOR')
    client = Client()
    client.force_login(user)
    response = client.get('/app/export/lots/csv/')
    assert response.status_code in (302, 403)


@pytest.mark.django_db
def test_lot_csv_export_begins_with_expected_columns():
    from apps.reports.exports import ProductExporter
    tenant = TenantFactory()
    csv_text = ProductExporter(tenant).export_lots_csv()
    rows = list(csv.reader(io.StringIO(csv_text.lstrip('\ufeff')), delimiter=';'))
    assert rows[0] == ['sku', 'produto', 'lote', 'validade', 'fabricacao', 'saldo_lote']
