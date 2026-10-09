"""Correções encontradas na revisão do segundo patch."""
import pytest
from django.test import Client
from rest_framework.test import APIClient
from apps.accounts.models import TenantMembership
from apps.products.models import Product
from apps.inventory.models import ImportItem
from apps.inventory.services.staging import approve_item, StagingError
from tests.factories import TenantFactory, UserFactory

@pytest.mark.django_db
def test_session_header_overrides_selected_tenant():
    u=UserFactory(); t1=TenantFactory(); t2=TenantFactory()
    for t in [t1,t2]: TenantMembership.objects.create(user=u,tenant=t,role='OWNER')
    Product.objects.create(tenant=t1,name='Caneta',sku='T1')
    Product.objects.create(tenant=t2,name='Caneta',sku='T2')
    c=Client();c.force_login(u);s=c.session;s['active_tenant_id']=t1.pk;s.save()
    r=c.get('/inventory/api/products/search/?q=Caneta',HTTP_X_TENANT_ID=str(t2.pk))
    assert r.status_code==200 and r.json()['results'][0]['sku']=='T2'
    t1.subscription_status='SUSPENDED';t1.save()
    assert c.get('/inventory/api/products/search/?q=Caneta',HTTP_X_TENANT_ID=str(t2.pk)).status_code==200
    assert c.get('/inventory/api/products/search/?q=Caneta').status_code==403
    assert c.get('/inventory/api/products/search/?q=Caneta',HTTP_X_TENANT_ID='invalid').status_code==400

@pytest.mark.django_db
def test_jwt_cookie_does_not_select_tenant():
    u=UserFactory(password='Senha!Forte123');t1=TenantFactory();t2=TenantFactory()
    for t in [t1,t2]: TenantMembership.objects.create(user=u,tenant=t,role='OWNER')
    c=APIClient();c.force_login(u);s=c.session;s['active_tenant_id']=t1.pk;s.save()
    token=c.post('/api/v1/auth/token/',{'username':u.username,'password':'Senha!Forte123'},format='json').data['access']
    c.credentials(HTTP_AUTHORIZATION='Bearer '+token)
    assert c.get('/api/v1/products/search/?q=Caneta').status_code==400

@pytest.mark.django_db
def test_variant_cannot_collide_with_parent_sku():
    t=TenantFactory();u=UserFactory();TenantMembership.objects.create(user=u,tenant=t,role='OWNER')
    parent=Product.objects.create(tenant=t,name='Camisa',product_type='VARIABLE',sku='PARENT')
    api=APIClient();api.force_authenticate(u)
    assert api.post('/api/v1/variants/',{'product':parent.pk,'sku':'parent','name':'P'},format='json').status_code==400

@pytest.mark.django_db
def test_negative_staging_quantity_remains_pending():
    t=TenantFactory();u=UserFactory()
    item=ImportItem.objects.create(tenant=t,source='API',supplier_sku='NEG',description='Produto',quantity=-2,unit_cost=1)
    with pytest.raises(StagingError): approve_item(item,u)
    item.refresh_from_db()
    assert item.status=='PENDING' and not t.product_set.exists()

@pytest.mark.django_db
def test_staging_bad_cost_returns_validation_error():
    t=TenantFactory();u=UserFactory();TenantMembership.objects.create(user=u,tenant=t,role='OWNER')
    api=APIClient();api.force_authenticate(u)
    for cost in ['invalid', '-1', 'NaN', 'Infinity']:
        assert api.post('/api/v1/products/?staged=true',{'name':'Test','avg_unit_cost':cost},format='json').status_code==400
    assert not ImportItem.objects.filter(tenant=t).exists()

@pytest.mark.django_db
def test_staging_case_insensitive_sku_reuses_existing():
    t=TenantFactory();u=UserFactory()
    p=Product.objects.create(tenant=t,name='Produto',sku='CASE')
    item=ImportItem.objects.create(tenant=t,source='API',supplier_sku='case',description='Produto',quantity=2,unit_cost=1)
    assert approve_item(item,u).pk==p.pk
    assert p.variants.first().current_stock==2

@pytest.mark.django_db
def test_failed_stock_entry_rolls_back_new_product(monkeypatch):
    from apps.core.services import StockService
    t=TenantFactory();u=UserFactory()
    item=ImportItem.objects.create(tenant=t,source='API',supplier_sku='FAIL',description='Produto',quantity=2,unit_cost=1)
    def fail(*args,**kwargs): raise ValueError('Failure')
    monkeypatch.setattr(StockService,'create_movement',fail)
    with pytest.raises(StagingError): approve_item(item,u)
    item.refresh_from_db()
    assert item.status=='PENDING' and not t.product_set.exists()
