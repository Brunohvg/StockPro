"""Regressão do patch 2: API (variações, SKU, curadoria, throttling) e telas mobile."""
import pytest
from django.test import Client, override_settings
from rest_framework.test import APIClient

from apps.accounts.models import TenantMembership
from apps.core.services import StockService
from apps.inventory.models import ImportItem, StockMovement
from apps.products.models import Product, ProductVariant
from tests.factories import TenantFactory, UserFactory

PWD = 'Senha!Forte123'


def _member(role='OWNER', tenant=None):
    tenant = tenant or TenantFactory()
    u = UserFactory(password=PWD)
    TenantMembership.objects.create(user=u, tenant=tenant, role=role)
    return u, tenant


def _api(user):
    api = APIClient()
    tok = api.post('/api/v1/auth/token/', {'username': user.username, 'password': PWD},
                   format='json').data['access']
    api.credentials(HTTP_AUTHORIZATION=f'Bearer {tok}')
    return api


@pytest.mark.django_db
class TestVariantesAPI:
    def test_cria_variacao_em_produto_variavel(self):
        u, tenant = _member()
        pai = Product.objects.create(tenant=tenant, name='Camiseta', product_type='VARIABLE', sku='CAM')
        r = _api(u).post('/api/v1/variants/', {'product': pai.pk, 'sku': 'CAM-P', 'name': 'P'}, format='json')
        assert r.status_code == 201, r.data
        v = ProductVariant.objects.get(sku='CAM-P')
        assert v.tenant == tenant and v.product == pai

    def test_variacao_exige_produto(self):
        u, _ = _member()
        r = _api(u).post('/api/v1/variants/', {'sku': 'X'}, format='json')
        assert r.status_code == 400

    def test_variacao_nao_usa_produto_de_outra_empresa(self):
        u, _ = _member()
        alheio = Product.objects.create(tenant=TenantFactory(), name='X', product_type='VARIABLE', sku='X')
        r = _api(u).post('/api/v1/variants/', {'product': alheio.pk, 'sku': 'X-1'}, format='json')
        assert r.status_code == 400

    def test_sku_duplicado_retorna_400(self):
        u, tenant = _member()
        Product.objects.create(tenant=tenant, name='Caneta', sku='CAN-1')
        r = _api(u).post('/api/v1/products/', {'name': 'Outra', 'sku': 'can-1'}, format='json')
        assert r.status_code == 400


@pytest.mark.django_db
class TestCuradoria:
    def _staged(self, api):
        r = api.post('/api/v1/products/?staged=true', {'sku': 'API-1', 'name': 'Novo via API'}, format='json')
        assert r.status_code == 202
        return r.data['staging_id']

    def test_lista_e_aprova_via_api(self):
        u, tenant = _member()
        api = _api(u)
        sid = self._staged(api)
        assert api.get('/api/v1/staging/').data['count'] == 1
        r = api.post(f'/api/v1/staging/{sid}/approve/')
        assert r.status_code == 200
        assert Product.objects.filter(tenant=tenant, sku='API-1', name='Novo via API').exists()
        assert api.post(f'/api/v1/staging/{sid}/approve/').status_code == 409

    def test_rejeita_via_api(self):
        u, _ = _member()
        api = _api(u)
        sid = self._staged(api)
        assert api.post(f'/api/v1/staging/{sid}/reject/').status_code == 200
        assert ImportItem.objects.get(pk=sid).status == 'REJECTED'

    def test_operador_nao_aprova(self):
        dono, tenant = _member()
        op, _ = _member('OPERATOR', tenant)
        sid = self._staged(_api(dono))
        assert _api(op).post(f'/api/v1/staging/{sid}/approve/').status_code == 403

    def test_aprovacao_pela_tela_com_quantidade(self):
        u, tenant = _member()
        item = ImportItem.objects.create(tenant=tenant, source='API', supplier_sku='WEB-1',
                                         description='Pela tela', quantity=4, unit_cost=2.5)
        c = Client()
        c.force_login(u)
        assert c.get('/inventory/pending/').status_code == 200
        r = c.post(f'/inventory/pending/{item.pk}/approve/', {'product_action': 'create_simple'})
        assert r.status_code == 302
        p = Product.objects.get(tenant=tenant, sku='WEB-1')
        assert p.variants.first().current_stock == 4
        assert StockMovement.objects.filter(product=p, type='IN').count() == 1


@pytest.mark.django_db
@override_settings(REST_FRAMEWORK={
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': ('rest_framework.permissions.IsAuthenticated',),
    'DEFAULT_THROTTLE_CLASSES': ('rest_framework.throttling.ScopedRateThrottle',),
    'DEFAULT_THROTTLE_RATES': {'auth': '3/minute', 'user': None, 'anon': None},
})
def test_login_api_tem_limite():
    from rest_framework.settings import api_settings
    from rest_framework.throttling import SimpleRateThrottle
    old_rates = SimpleRateThrottle.THROTTLE_RATES
    api_settings.reload()
    SimpleRateThrottle.THROTTLE_RATES = api_settings.DEFAULT_THROTTLE_RATES
    try:
        api = APIClient()
        codes = [api.post('/api/v1/auth/token/', {'username': 'x', 'password': 'y'}, format='json').status_code
                 for _ in range(4)]
        assert codes[-1] == 429
    finally:
        SimpleRateThrottle.THROTTLE_RATES = old_rates
        api_settings.reload()


@pytest.mark.django_db
class TestMobile:
    def test_busca_por_sessao_com_varias_empresas_usa_empresa_ativa(self):
        u, t1 = _member()
        t2 = TenantFactory()
        TenantMembership.objects.create(user=u, tenant=t2, role='OWNER')
        Product.objects.create(tenant=t1, name='Caneta', sku='CAN-1')
        c = Client()
        c.force_login(u)
        s = c.session
        s['active_tenant_id'] = t1.pk
        s.save()
        r = c.get('/inventory/api/products/search/?q=Caneta')
        assert r.status_code == 200 and r.json()['count'] == 1

    def test_historico_mostra_tipo_e_sinal(self):
        u, tenant = _member('OPERATOR')
        p = Product.objects.create(tenant=tenant, name='Caneta', sku='CAN-1')
        StockService.create_movement(tenant, u, 'IN', 3, product=p)
        c = Client()
        c.force_login(u)
        html = c.get('/mobile/history/').content.decode()
        assert '+3' in html and 'text-emerald-400' in html

    def test_saida_com_decimal(self):
        u, tenant = _member('OPERATOR')
        p = Product.objects.create(tenant=tenant, name='Fio', sku='FIO-1')
        StockService.create_movement(tenant, u, 'IN', 5, product=p)
        c = Client()
        c.force_login(u)
        c.post('/mobile/move/', {'type': 'OUT', 'sku': 'FIO-1', 'quantity': '1,5'})
        assert float(p.variants.first().current_stock) == 3.5

    def test_painel_mobile_do_gestor_aceita_decimal(self):
        u, tenant = _member('ADMIN')
        p = Product.objects.create(tenant=tenant, name='Fio', sku='FIO-1')
        c = Client()
        c.force_login(u)
        c.post('/inventory/movements/mobile/', {'type': 'IN', 'sku': 'FIO-1', 'quantity': '2.25'})
        assert float(p.variants.first().current_stock) == 2.25

    def test_logout_mobile_e_post(self):
        u, _ = _member('OPERATOR')
        c = Client()
        c.force_login(u)
        html = c.get('/mobile/move/').content.decode()
        assert 'href="/accounts/logout/"' not in html and 'method="post"' in html
