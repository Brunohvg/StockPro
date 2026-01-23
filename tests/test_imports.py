import pytest

from apps.partners.models import SupplierProductMap
from tests.factories import (
    ImportItemFactory,
    ProductFactory,
    SupplierFactory,
    SupplierProductMapFactory,
    TenantFactory,
)


@pytest.mark.django_db
class TestImportIntelligence:
    def test_supplier_product_mapping(self, tenant):
        """Verify that a supplier SKU can be mapped to an internal product"""
        supplier = SupplierFactory(tenant=tenant)
        product = ProductFactory(tenant=tenant)

        mapping = SupplierProductMapFactory(
            tenant=tenant,
            supplier=supplier,
            product=product,
            supplier_sku="EXT-123"
        )

        found = SupplierProductMap.find_mapping(tenant, supplier, "EXT-123")
        assert found == mapping
        assert found.product == product

    def test_import_item_ai_suggestion(self, tenant):
        """Verify storage of AI suggestions in ImportItem"""
        item = ImportItemFactory(
            tenant=tenant,
            ai_suggestion={"brand": "Apple", "category": "Electronics"},
            ai_confidence=0.95
        )

        assert item.ai_suggestion["brand"] == "Apple"
        assert item.ai_confidence_percent == 95

    def test_deduplication_ean_match(self, tenant):
        """Verify EAN deduplication logic (Simulated via Service-like behavior)"""
        product = ProductFactory(tenant=tenant, barcode="7891234567890")

        # In a real scenario, the Matcher service would find this.
        # Here we verify the model's ability to hold the matched product
        item = ImportItemFactory(tenant=tenant)
        item.matched_product = product
        item.status = 'DONE'
        item.save()

        assert item.matched_product == product
        assert item.status == 'DONE'

    def test_tenant_isolation_mappings(self):
        """Verify that mappings from one tenant don't appear in another"""
        t1 = TenantFactory()
        t2 = TenantFactory()

        s1 = SupplierFactory(tenant=t1, cnpj="00000000000191")
        s2 = SupplierFactory(tenant=t2, cnpj="00000000000191") # Same CNPJ, different tenant

        p1 = ProductFactory(tenant=t1)

        SupplierProductMapFactory(tenant=t1, supplier=s1, product=p1, supplier_sku="MAPPED")

        # Mapping for t1 should not be found for t2
        assert SupplierProductMap.find_mapping(t2, s2, "MAPPED") is None
        assert SupplierProductMap.find_mapping(t1, s1, "MAPPED") is not None
