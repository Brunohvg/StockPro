import pytest
from django.core.exceptions import ValidationError
from apps.products.models import Product, ProductType, ProductVariant
from apps.inventory.models import StockMovement
from tests.factories import ProductFactory, ProductVariantFactory, TenantFactory, LocationFactory

@pytest.fixture
def location(tenant):
    return LocationFactory(tenant=tenant)

@pytest.mark.django_db
class TestProductNormalization:
    def test_simple_product_auto_variant_creation(self, tenant):
        """Verify that creating a SIMPLE product automatically creates a variant"""
        product = Product.objects.create(
            name="Simple Product",
            sku="SIM-AUTO-01",
            product_type=ProductType.SIMPLE,
            tenant=tenant,
            current_stock=50,
            barcode="12345678"
        )

        # Check if exactly one variant was created
        assert product.variants.count() == 1
        variant = product.variants.first()

        # Check if data was copied correctly
        assert variant.sku == product.sku
        assert variant.current_stock == 50
        assert variant.barcode == "12345678"
        assert variant.tenant == product.tenant

    def test_variable_product_no_auto_variant(self, tenant):
        """Verify that VARIABLE products do not auto-create a variant (should be done manually)"""
        product = Product.objects.create(
            name="Variable Product",
            sku="VAR-MAN-01",
            product_type=ProductType.VARIABLE,
            tenant=tenant
        )
        assert product.variants.count() == 0

    def test_total_stock_delegation(self, tenant):
        """Verify total_stock only looks at variants"""
        product = ProductFactory(product_type=ProductType.SIMPLE, tenant=tenant)
        variant = product.variants.first()

        # Update variant stock directly using filter to bypass lockdown
        ProductVariant.objects.filter(pk=variant.pk).update(current_stock=100)

        # Even if product field has different value (deprecated), property should prioritize variant
        Product.objects.filter(pk=product.pk).update(current_stock=0)
        product.refresh_from_db()

        assert product.total_stock == 100

    def test_stock_movement_requires_variant(self, tenant, location):
        """Verify StockMovement cannot be created without a variant"""
        product = ProductFactory(tenant=tenant)

        # Attempting create without variant should fail validation
        movement = StockMovement(
            product=product,
            quantity=10,
            type='IN',
            location=location,
            tenant=tenant
        )

        with pytest.raises(ValidationError):
            movement.full_clean()

    def test_delete_simple_product_deletes_variant(self, tenant):
        """Verify cascading delete works"""
        product = ProductFactory(product_type=ProductType.SIMPLE, tenant=tenant)
        variant_id = product.variants.first().id

        product.delete()
        assert not ProductVariant.objects.filter(id=variant_id).exists()
