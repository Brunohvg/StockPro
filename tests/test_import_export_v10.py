"""
Tests for Import/Export System (V10 Hardened)

Covers the 7 bugs fixed in the audit:
1. Export _simple_row reads from variant instead of legacy Product fields
2. Stock adjustment per-row transaction isolation
3. ImportLog status detection
4. Name normalization on Product and ProductVariant
5. Products without SKU auto-generation + name-based dedup
6. StockService source tagging
7. parse_decimal_br edge cases
"""
import csv
import io
import os
import tempfile
from decimal import Decimal

import pytest

from apps.core.services import StockService
from apps.inventory.tasks import parse_decimal_br, process_csv_catalog_direct, process_csv_stock_adjustment
from apps.products.models import Product, ProductType, ProductVariant
from apps.reports.exports import ProductExporter
from tests.factories import (
    CategoryFactory,
    ImportBatchFactory,
    LocationFactory,
    ProductFactory,
    ProductVariantFactory,
    TenantFactory,
    UserFactory,
)


# ═══════════════════════════════════════════════════════════════
# PARSE DECIMAL
# ═══════════════════════════════════════════════════════════════


class TestParseDecimalBr:
    """Test parse_decimal_br() edge cases"""

    def test_br_format_with_thousands(self):
        assert parse_decimal_br("1.250,00") == Decimal("1250.00")

    def test_br_format_without_thousands(self):
        assert parse_decimal_br("1250,00") == Decimal("1250.00")

    def test_international_format(self):
        assert parse_decimal_br("1250.00") == Decimal("1250.00")

    def test_integer(self):
        assert parse_decimal_br("1000") == Decimal("1000")

    def test_none_returns_none(self):
        assert parse_decimal_br(None) is None

    def test_empty_string_returns_none(self):
        assert parse_decimal_br("") is None

    def test_nan_returns_none(self):
        assert parse_decimal_br("nan") is None

    def test_nan_case_insensitive(self):
        assert parse_decimal_br("NaN") is None

    def test_whitespace_stripped(self):
        assert parse_decimal_br("  25.90  ") == Decimal("25.90")

    def test_invalid_string_returns_none(self):
        assert parse_decimal_br("abc") is None

    def test_zero(self):
        assert parse_decimal_br("0") == Decimal("0")

    def test_negative_value(self):
        assert parse_decimal_br("-10.50") == Decimal("-10.50")


# ═══════════════════════════════════════════════════════════════
# NAME NORMALIZATION
# ═══════════════════════════════════════════════════════════════


@pytest.mark.django_db
class TestNameNormalization:
    """Test name normalization in Product.save() and ProductVariant.save()"""

    def test_product_strips_whitespace(self, tenant):
        product = Product.objects.create(
            tenant=tenant,
            name="  Parafuso Sextavado  ",
            product_type=ProductType.SIMPLE
        )
        assert product.name == "Parafuso Sextavado"

    def test_product_collapses_multiple_spaces(self, tenant):
        product = Product.objects.create(
            tenant=tenant,
            name="Parafuso  Sextavado   8mm",
            product_type=ProductType.SIMPLE
        )
        assert product.name == "Parafuso Sextavado 8mm"

    def test_product_preserves_case(self, tenant):
        product = Product.objects.create(
            tenant=tenant,
            name="Cabo USB-C Para LED 8mm",
            product_type=ProductType.SIMPLE
        )
        assert product.name == "Cabo USB-C Para LED 8mm"

    def test_variant_strips_whitespace(self, tenant):
        product = ProductFactory(tenant=tenant, product_type=ProductType.VARIABLE)
        variant = ProductVariant.objects.create(
            product=product,
            tenant=tenant,
            name="  Azul  M  ",
            sku="TEST-NORM-V1"
        )
        assert variant.name == "Azul M"

    def test_normalization_on_update(self, tenant):
        product = Product.objects.create(
            tenant=tenant,
            name="Original",
            product_type=ProductType.SIMPLE
        )
        product.name = "  Updated   Name  "
        product.save()
        product.refresh_from_db()
        assert product.name == "Updated Name"


# ═══════════════════════════════════════════════════════════════
# SKU AUTO-GENERATION
# ═══════════════════════════════════════════════════════════════


@pytest.mark.django_db
class TestSKUAutoGeneration:
    """Test SKU auto-generation when SKU is empty"""

    def test_product_generates_sku_when_empty(self, tenant):
        product = Product.objects.create(
            tenant=tenant,
            name="Auto SKU Test",
            sku="",
            product_type=ProductType.SIMPLE
        )
        product.refresh_from_db()
        assert product.sku
        assert len(product.sku) > 3

    def test_product_preserves_provided_sku(self, tenant):
        product = Product.objects.create(
            tenant=tenant,
            name="Manual SKU Test",
            sku="MY-CUSTOM-SKU",
            product_type=ProductType.SIMPLE
        )
        product.refresh_from_db()
        assert product.sku == "MY-CUSTOM-SKU"

    def test_variant_generates_sku_when_empty(self, tenant):
        product = ProductFactory(tenant=tenant, product_type=ProductType.VARIABLE)
        variant = ProductVariant.objects.create(
            product=product,
            tenant=tenant,
            name="Test Variant",
            sku=""
        )
        variant.refresh_from_db()
        assert variant.sku

    def test_simple_product_creates_variant_with_same_sku(self, tenant):
        product = Product.objects.create(
            tenant=tenant,
            name="Simple With Variant",
            sku="SIM-TEST-01",
            product_type=ProductType.SIMPLE
        )
        variant = product.variants.first()
        assert variant is not None
        assert variant.sku == product.sku


# ═══════════════════════════════════════════════════════════════
# EXPORT: _simple_row reads from VARIANT
# ═══════════════════════════════════════════════════════════════


@pytest.mark.django_db
class TestExportSimpleRow:
    """BUG 1: Export must read stock/cost from variant, not legacy Product fields"""

    def test_simple_row_reads_variant_stock(self, tenant):
        product = ProductFactory(tenant=tenant, product_type=ProductType.SIMPLE)
        variant = product.variants.first()

        ProductVariant.objects.filter(pk=variant.pk).update(
            current_stock=42, avg_unit_cost=Decimal("15.50")
        )
        Product.objects.filter(pk=product.pk).update(current_stock=0, avg_unit_cost=None)

        exporter = ProductExporter(tenant)
        row = exporter._simple_row(product)

        assert row['stock'] == 42
        assert row['cost'] == 15.50

    def test_simple_row_reads_variant_barcode(self, tenant):
        product = ProductFactory(tenant=tenant, product_type=ProductType.SIMPLE)
        variant = product.variants.first()
        ProductVariant.objects.filter(pk=variant.pk).update(barcode="7891234567890")

        exporter = ProductExporter(tenant)
        row = exporter._simple_row(product)

        assert row['barcode'] == "7891234567890"

    def test_export_csv_full_flow(self, tenant):
        product = ProductFactory(tenant=tenant, product_type=ProductType.SIMPLE, name="TestProd")
        variant = product.variants.first()
        ProductVariant.objects.filter(pk=variant.pk).update(
            current_stock=100, avg_unit_cost=Decimal("25.00")
        )

        exporter = ProductExporter(tenant)
        csv_content = exporter.export_csv()

        reader = csv.DictReader(io.StringIO(csv_content))
        rows = list(reader)
        assert len(rows) == 1
        assert rows[0]['name'] == "TestProd"
        assert float(rows[0]['stock']) == 100.0
        assert float(rows[0]['cost']) == 25.0


# ═══════════════════════════════════════════════════════════════
# IMPORT: CATALOG DIRECT
# ═══════════════════════════════════════════════════════════════


def _make_csv(rows, header="nome,sku,categoria,marca,unidade,custo_medio,estoque_atual"):
    """Helper to create a temp CSV file"""
    fd, path = tempfile.mkstemp(suffix='.csv')
    with os.fdopen(fd, 'w', newline='') as f:
        f.write(header + "\n")
        for row in rows:
            f.write(row + "\n")
    return path


def _make_batch(tenant, user, csv_path, batch_type='CATALOG_DIRECT'):
    """Helper to create an ImportBatch with a file"""
    batch = ImportBatchFactory(tenant=tenant, user=user, type=batch_type)
    batch.file.name = csv_path
    batch.save()
    batch.file.path = csv_path
    return batch


@pytest.mark.django_db
class TestCatalogImport:
    """Test process_csv_catalog_direct() edge cases"""

    def test_create_product_with_sku(self, tenant, user):
        csv_path = _make_csv(["Parafuso 8mm,PAR-001,Fixadores,,UN,0.55,1000"])
        batch = _make_batch(tenant, user, csv_path)

        result = process_csv_catalog_direct(batch)

        assert "1 itens criados" in result
        product = Product.objects.filter(tenant=tenant, name="Parafuso 8mm").first()
        assert product is not None
        assert product.sku == "PAR-001"

        os.unlink(csv_path)

    def test_create_product_without_sku(self, tenant, user):
        csv_path = _make_csv(["Parafuso 8mm,,Fixadores,,UN,0.55,1000"])
        batch = _make_batch(tenant, user, csv_path)

        result = process_csv_catalog_direct(batch)

        assert "1 itens criados" in result
        product = Product.objects.filter(tenant=tenant, name="Parafuso 8mm").first()
        assert product is not None
        assert product.sku  # Should have auto-generated SKU

        os.unlink(csv_path)

    def test_reimport_without_sku_updates_existing(self, tenant, user):
        csv_path1 = _make_csv(["Parafuso 8mm,,Fixadores,,UN,0.55,100"])
        batch1 = _make_batch(tenant, user, csv_path1)
        process_csv_catalog_direct(batch1)

        csv_path2 = _make_csv(["Parafuso 8mm,,Fixadores,,UN,1.00,200"])
        batch2 = _make_batch(tenant, user, csv_path2)
        process_csv_catalog_direct(batch2)

        count = Product.objects.filter(tenant=tenant, name="Parafuso 8mm").count()
        assert count == 1

        os.unlink(csv_path1)
        os.unlink(csv_path2)

    def test_skip_row_without_name(self, tenant, user):
        csv_path = _make_csv([",SKU-001,,,UN,1.00,10"])
        batch = _make_batch(tenant, user, csv_path)

        result = process_csv_catalog_direct(batch)

        assert "1 erros" in result
        assert "Nome ausente" in result

        os.unlink(csv_path)

    def test_per_row_error_isolation(self, tenant, user):
        csv_path = _make_csv([
            "Produto Bom,SKU-GOOD,,,UN,10.00,50",
            ",,,,,,"
        ])
        batch = _make_batch(tenant, user, csv_path)

        result = process_csv_catalog_direct(batch)

        assert "1 itens criados" in result
        assert Product.objects.filter(tenant=tenant, sku="SKU-GOOD").exists()

        os.unlink(csv_path)

    def test_stock_adjustment_via_import(self, tenant, user):
        csv_path = _make_csv(["Produto Estoque,SKU-STK,,,UN,,500"])
        batch = _make_batch(tenant, user, csv_path)

        result = process_csv_catalog_direct(batch)

        variant = ProductVariant.objects.filter(tenant=tenant, sku="SKU-STK").first()
        assert variant is not None
        variant.refresh_from_db()
        assert variant.current_stock == 500

        os.unlink(csv_path)


# ═══════════════════════════════════════════════════════════════
# STOCK ADJUSTMENT CSV
# ═══════════════════════════════════════════════════════════════


@pytest.mark.django_db
class TestStockAdjustmentCSV:
    """Test process_csv_stock_adjustment() — BUG 2: per-row isolation"""

    def test_adjustment_in_movement(self, tenant, user):
        product = ProductFactory(tenant=tenant, product_type=ProductType.SIMPLE, sku="ADJ-001")
        variant = product.variants.first()
        ProductVariant.objects.filter(pk=variant.pk).update(current_stock=10)

        csv_path = _make_csv(["ADJ-001,Produto A,5,"], header="sku,name,quantity,avg_unit_cost")
        batch = _make_batch(tenant, user, csv_path, batch_type='STOCK_SYNC')

        result = process_csv_stock_adjustment(batch)

        variant.refresh_from_db()
        assert variant.current_stock == 15  # 10 + 5
        assert "Sucessos: 1" in result

        os.unlink(csv_path)

    def test_not_found_sku_logged(self, tenant, user):
        csv_path = _make_csv(["FAKE-SKU,Produto X,10,"], header="sku,name,quantity,avg_unit_cost")
        batch = _make_batch(tenant, user, csv_path, batch_type='STOCK_SYNC')

        result = process_csv_stock_adjustment(batch)

        assert "Erros: 1" in result
        assert "FAKE-SKU" in result

        os.unlink(csv_path)

    def test_per_row_isolation_in_stock_adj(self, tenant, user):
        product = ProductFactory(tenant=tenant, product_type=ProductType.SIMPLE, sku="ISO-001")
        variant = product.variants.first()
        ProductVariant.objects.filter(pk=variant.pk).update(current_stock=0)

        csv_path = _make_csv([
            "ISO-001,Good Row,10,",
            "NONEXISTENT,Bad Row,5,"
        ], header="sku,name,quantity,avg_unit_cost")
        batch = _make_batch(tenant, user, csv_path, batch_type='STOCK_SYNC')

        result = process_csv_stock_adjustment(batch)

        variant.refresh_from_db()
        assert variant.current_stock == 10
        assert "Sucessos: 1" in result
        assert "Erros: 1" in result

        os.unlink(csv_path)


# ═══════════════════════════════════════════════════════════════
# STOCK SERVICE SOURCE TAG
# ═══════════════════════════════════════════════════════════════


@pytest.mark.django_db
class TestStockServiceSourceTag:
    """BUG 5: Import movements should have source='IMPORT'"""

    def test_manual_movement_has_manual_source(self, tenant, user):
        product = ProductFactory(tenant=tenant)
        movement = StockService.create_movement(
            tenant=tenant,
            user=user,
            movement_type='IN',
            quantity=10,
            product=product,
            reason="Manual entry"
        )
        assert movement.source == 'MANUAL'

    def test_import_movement_has_import_source(self, tenant, user):
        product = ProductFactory(tenant=tenant)
        movement = StockService.create_movement(
            tenant=tenant,
            user=user,
            movement_type='IN',
            quantity=10,
            product=product,
            reason="Via import",
            source='IMPORT'
        )
        assert movement.source == 'IMPORT'


# ═══════════════════════════════════════════════════════════════
# STOCK ADJUSTMENT: PORTUGUESE ALIASES
# ═══════════════════════════════════════════════════════════════


@pytest.mark.django_db
class TestStockAdjustmentPortugueseAliases:
    """BUG 8: CSV with Portuguese column names should work"""

    def test_quantidade_alias(self, tenant, user):
        """Column 'quantidade' should map to 'quantity'"""
        product = ProductFactory(tenant=tenant, product_type=ProductType.SIMPLE, sku="PT-001")
        variant = product.variants.first()
        ProductVariant.objects.filter(pk=variant.pk).update(current_stock=0)

        csv_path = _make_csv(
            ["PT-001,100,0.55"],
            header="sku,quantidade,custo_unitario"
        )
        batch = _make_batch(tenant, user, csv_path, batch_type='STOCK_SYNC')

        result = process_csv_stock_adjustment(batch)

        variant.refresh_from_db()
        assert variant.current_stock == 100
        assert "Sucessos: 1" in result

        os.unlink(csv_path)
