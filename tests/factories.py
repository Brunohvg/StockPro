import factory
from django.contrib.auth import get_user_model

from apps.accounts.models import TenantMembership
from apps.inventory.models import (
    ImportBatch,
    ImportItem,
    InventoryAudit,
    InventoryAuditItem,
    Location,
    StockMovement,
)
from apps.partners.models import Supplier, SupplierProductMap
from apps.products.models import Category, Product, ProductType, ProductVariant
from apps.tenants.models import Plan, Tenant

User = get_user_model()

class PlanFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Plan

    name = factory.Sequence(lambda n: f'plan_{n}')
    display_name = "Plan Basic"
    max_products = 50
    max_users = 3

class TenantFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Tenant

    name = factory.Faker('company')
    is_active = True
    plan = factory.SubFactory(PlanFactory)
    subscription_status = 'ACTIVE'

class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User

    username = factory.Sequence(lambda n: f'user_{n}')
    email = factory.LazyAttribute(lambda o: f'{o.username}@example.com')

    @factory.post_generation
    def password(self, create, extracted, **kwargs):
        password = extracted or "password123"
        self.set_password(password)

class TenantMembershipFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = TenantMembership

    user = factory.SubFactory(UserFactory)
    tenant = factory.SubFactory(TenantFactory)
    role = 'OWNER'

class CategoryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Category

    tenant = factory.SubFactory(TenantFactory)
    name = factory.Sequence(lambda n: f'Category {n}')

class ProductFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Product

    tenant = factory.SubFactory(TenantFactory)
    name = factory.Faker('word')
    sku = None  # Will be generated on save
    product_type = ProductType.SIMPLE
    category = factory.SubFactory(CategoryFactory, tenant=factory.SelfAttribute('..tenant'))

class ProductVariantFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ProductVariant

    product = factory.SubFactory(ProductFactory, product_type=ProductType.VARIABLE)
    tenant = factory.SelfAttribute('product.tenant')
    name = factory.LazyAttribute(lambda o: f"{o.product.name} Variant")
    sku = None  # Will be generated on save

class SupplierFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Supplier

    tenant = factory.SubFactory(TenantFactory)
    cnpj = "00000000000191"
    company_name = factory.Faker('company')
    trade_name = factory.Faker('company')
    is_active = True

class SupplierProductMapFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = SupplierProductMap

    tenant = factory.SubFactory(TenantFactory)
    supplier = factory.SubFactory(SupplierFactory, tenant=factory.SelfAttribute('..tenant'))
    product = factory.SubFactory(ProductFactory, tenant=factory.SelfAttribute('..tenant'))
    supplier_sku = factory.Sequence(lambda n: f'SUP-{n}')
    supplier_name = factory.Faker('word')

class ImportBatchFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ImportBatch

    tenant = factory.SubFactory(TenantFactory)
    type = 'XML_NFE'
    status = 'PENDING'
    user = factory.SubFactory(UserFactory)

class ImportItemFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ImportItem

    batch = factory.SubFactory(ImportBatchFactory)
    tenant = factory.SelfAttribute('batch.tenant')
    supplier_sku = factory.Sequence(lambda n: f'SUP-ITEM-{n}')
    description = factory.Faker('word')
    quantity = 10
    unit_cost = 5.5
    status = 'PENDING'

class LocationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Location

    tenant = factory.SubFactory(TenantFactory)
    code = factory.Sequence(lambda n: f'LOC-{n}')
    name = factory.Faker('street_name')
    location_type = 'STORE'
    is_active = True

class StockMovementFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = StockMovement

    tenant = factory.SubFactory(TenantFactory)
    user = factory.SubFactory(UserFactory)
    location = factory.SubFactory(LocationFactory, tenant=factory.SelfAttribute('..tenant'))
    type = 'IN'
    quantity = 10
    balance_after = 10
    source = 'MANUAL'

class InventoryAuditFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = InventoryAudit

    tenant = factory.SubFactory(TenantFactory)
    location = factory.SubFactory(LocationFactory, tenant=factory.SelfAttribute('..tenant'))
    user = factory.SubFactory(UserFactory)
    status = 'DRAFT'

class InventoryAuditItemFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = InventoryAuditItem

    audit = factory.SubFactory(InventoryAuditFactory)
    product = factory.SubFactory(ProductFactory, tenant=factory.SelfAttribute('..audit.tenant'))
    ledger_quantity = 10
    physical_quantity = 10
