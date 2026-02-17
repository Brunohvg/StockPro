import pytest

from apps.products.models import Product, ProductType, ProductVariant
from tests.factories import CategoryFactory, ProductFactory, ProductVariantFactory, TenantFactory


@pytest.mark.django_db
class TestProductLogic:
    def test_sku_generation_simple(self):
        """Verify SKU generation for simple products: SIM-CAT-ID"""
        cat = CategoryFactory(name="Eletrônicos")
        product = ProductFactory(
            category=cat,
            product_type=ProductType.SIMPLE,
            tenant=cat.tenant
        )
        # Expected: SIM-ELE-XXXX
        assert product.sku.startswith("SIM-ELE-")
        assert len(product.sku) > 8

    def test_sku_generation_variable(self):
        """Verify SKU generation for variable products: VAR-CAT-ID"""
        cat = CategoryFactory(name="Roupas")
        product = ProductFactory(
            category=cat,
            product_type=ProductType.VARIABLE,
            tenant=cat.tenant
        )
        assert product.sku.startswith("VAR-ROU-")

    def test_variable_product_total_stock(self, tenant):
        """Verify total_stock sums variants for variable products"""
        product = ProductFactory(
            product_type=ProductType.VARIABLE,
            tenant=tenant
        )
        v1 = ProductVariantFactory(product=product)
        v2 = ProductVariantFactory(product=product)

        # Update stock via filter to bypass signals if necessary, but here we can just set it
        ProductVariant.objects.filter(pk=v1.pk).update(current_stock=10)
        ProductVariant.objects.filter(pk=v2.pk).update(current_stock=5)

        assert product.total_stock == 15

    def test_tenant_isolation_basic(self):
        """Verify products belong to different tenants"""
        t1 = TenantFactory()
        t2 = TenantFactory()

        p1 = ProductFactory(tenant=t1, name="Product T1")
        p2 = ProductFactory(tenant=t2, name="Product T2")

        assert p1.tenant != p2.tenant
        assert Product.objects.filter(tenant=t1).count() == 1
        assert Product.objects.filter(tenant=t2).count() == 1

    def test_variant_stock_lockdown(self, tenant):
        """Verify variant stock cannot be changed without internal flag"""
        variant = ProductVariantFactory(tenant=tenant)
        ProductVariant.objects.filter(pk=variant.pk).update(current_stock=10)
        variant.refresh_from_db()

        # Attempt to change stock directly
        variant.current_stock = 20
        variant.save()

        # Should revert to 10
        variant.refresh_from_db()
        assert variant.current_stock == 10

        # With flag
        variant.current_stock = 20
        variant._allow_stock_change = True
        variant.save()

        variant.refresh_from_db()
        assert variant.current_stock == 20
