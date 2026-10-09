"""Regressão das falhas de segurança e funcionamento encontradas na análise de 09/10/2026."""
from decimal import Decimal

import pytest
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.test import Client
from rest_framework.test import APIClient

from apps.accounts.models import TenantMembership
from apps.core.services import StockService
from apps.products.models import Category, Product
from apps.tenants.models import Plan
from tests.factories import TenantFactory, UserFactory

PWD = 'Senha!Forte123'


def _member(role, tenant=None):
    tenant = tenant or TenantFactory()
    u = UserFactory(password=PWD)
    TenantMembership.objects.create(user=u, tenant=tenant, role=role)
    return u, tenant


def _client(user):
    c = Client()
    c.force_login(user)
    return c


@pytest.mark.django_db
class TestLogin:
    def test_identificador_duplicado_nao_dispensa_senha(self):
        vitima = UserFactory(username='dono', email='dono@empresa.com', password='SenhaSecreta!9')
        User.objects.create_user(username='x', email='DONO@empresa.com', password='qualquer')
        assert authenticate(None, username='dono@empresa.com', password='SENHA-ERRADA') is None
        assert authenticate(None, username='dono@empresa.com', password='SenhaSecreta!9') == vitima

    def test_signup_recusa_email_existente_com_outra_caixa(self):
        UserFactory(username='dono', email='dono@empresa.com')
        r = Client().post('/signup/', {'company_name': 'X', 'email': 'DONO@empresa.com',
                                       'password': 'Outra!Senha99', 'first_name': 'a'})
        assert r.status_code == 200
        assert User.objects.filter(email__iexact='dono@empresa.com').count() == 1

    def test_funcionario_nao_pode_usar_email_alheio_como_username(self):
        UserFactory(username='dono', email='dono@empresa.com')
        u, _ = _member('OWNER')
        _client(u).post('/settings/employees/add/', {
            'username': 'dono@empresa.com', 'email': 'outro@x.com',
            'first_name': 'a', 'last_name': 'b', 'password': PWD})
        assert not User.objects.filter(username='dono@empresa.com').exists()


@pytest.mark.django_db
class TestBilling:
    def test_membro_nao_muda_plano(self):
        u, tenant = _member('OWNER')
        caro, _ = Plan.objects.get_or_create(name='EMPRESARIAL', defaults={'display_name': 'Empresarial', 'price': 697})
        plano_original = tenant.plan_id
        _client(u).post(f'/billing/upgrade/{caro.pk}/')
        tenant.refresh_from_db()
        assert tenant.plan_id == plano_original

    def test_suspensa_nao_se_reativa(self):
        u, tenant = _member('OWNER')
        tenant.subscription_status = 'SUSPENDED'
        tenant.save()
        plano = Plan.objects.create(name='P', display_name='P', price=97)
        _client(u).post(f'/billing/upgrade/{plano.pk}/')
        tenant.refresh_from_db()
        assert tenant.subscription_status == 'SUSPENDED'


@pytest.mark.django_db
class TestPermissoes:
    def test_operador_nao_cria_funcionario(self):
        u, _ = _member('OPERATOR')
        _client(u).post('/settings/employees/add/', {
            'username': 'novoadm', 'email': 'n@x.com', 'first_name': 'n',
            'last_name': 'a', 'password': PWD, 'is_staff': 'on'})
        assert not User.objects.filter(username='novoadm').exists()

    def test_admin_nao_cria_outro_admin(self):
        u, _ = _member('ADMIN')
        _client(u).post('/settings/employees/add/', {
            'username': 'novo', 'email': 'n@x.com', 'first_name': 'n',
            'last_name': 'a', 'password': PWD, 'is_staff': 'on'})
        assert TenantMembership.objects.get(user__username='novo').role == 'OPERATOR'

    def test_operador_nao_apaga_produto(self):
        u, tenant = _member('OPERATOR')
        p = Product.objects.create(tenant=tenant, name='Caneta')
        _client(u).post(f'/products/{p.pk}/delete/')
        assert Product.objects.filter(pk=p.pk).exists()

    def test_operador_nao_altera_configuracoes(self):
        u, _ = _member('OPERATOR')
        r = _client(u).get('/settings/')
        assert r.status_code == 302

    def test_funcionario_de_outra_empresa_404(self):
        u, _ = _member('OWNER')
        outro, _ = _member('OWNER')
        assert _client(u).get(f'/app/employees/{outro.pk}/').status_code == 404


@pytest.mark.django_db
class TestMobile:
    def test_operador_registra_entrada_no_mobile(self):
        u, tenant = _member('OPERATOR')
        p = Product.objects.create(tenant=tenant, name='Caneta', sku='CAN-1')
        _client(u).post('/mobile/move/', {'type': 'IN', 'sku': 'CAN-1', 'quantity': '5'})
        assert p.variants.first().current_stock == 5

    def test_mobile_nao_aceita_ajuste_absoluto(self):
        u, tenant = _member('OPERATOR')
        p = Product.objects.create(tenant=tenant, name='Caneta', sku='CAN-1')
        StockService.create_movement(tenant, u, 'IN', 10, product=p)
        _client(u).post('/mobile/move/', {'type': 'ADJ', 'sku': 'CAN-1', 'quantity': '1'})
        # Tipo inválido não pode alterar o estoque.
        assert p.variants.first().current_stock == 10


@pytest.mark.django_db
class TestAPI:
    def _api(self, user):
        api = APIClient()
        tok = api.post('/api/v1/auth/token/', {'username': user.username, 'password': PWD},
                       format='json').data['access']
        api.credentials(HTTP_AUTHORIZATION=f'Bearer {tok}')
        return api

    def test_empresa_suspensa_bloqueada(self):
        u, tenant = _member('OWNER')
        Product.objects.create(tenant=tenant, name='Caneta', sku='CAN-1')
        api = self._api(u)
        tenant.subscription_status = 'SUSPENDED'
        tenant.save()
        r = api.post('/api/v1/inventory/entry/', {'items': [{'sku': 'CAN-1', 'quantity': 3}]}, format='json')
        assert r.status_code == 403

    def test_empresa_ativa_funciona(self):
        u, tenant = _member('OWNER')
        p = Product.objects.create(tenant=tenant, name='Caneta', sku='CAN-1')
        r = self._api(u).post('/api/v1/inventory/entry/', {'items': [{'sku': 'CAN-1', 'quantity': 3}]},
                              format='json')
        assert r.status_code == 200
        assert p.variants.first().current_stock == 3

    def test_varias_empresas_exige_header(self):
        u, t1 = _member('OWNER')
        t2 = TenantFactory()
        TenantMembership.objects.create(user=u, tenant=t2, role='OWNER')
        Product.objects.create(tenant=t2, name='Caneta', sku='CAN-2')
        api = self._api(u)
        r = api.get('/api/v1/products/search/?q=Caneta')
        assert r.status_code == 400
        r = api.get('/api/v1/products/search/?q=Caneta', HTTP_X_TENANT_ID=str(t2.pk))
        assert r.status_code == 200 and r.data['count'] == 1

    def test_nao_vincula_categoria_de_outra_empresa(self):
        u, _ = _member('OWNER')
        alheia = Category.objects.create(tenant=TenantFactory(), name='Segredo')
        r = self._api(u).post('/api/v1/products/', {'name': 'X', 'category': alheia.pk}, format='json')
        assert r.status_code == 400


@pytest.mark.django_db
class TestMovimentacao:
    def test_quantidade_negativa_recusada(self):
        u, tenant = _member('OWNER')
        p = Product.objects.create(tenant=tenant, name='Caneta', sku='CAN-1')
        StockService.create_movement(tenant, u, 'IN', 10, product=p)
        with pytest.raises(ValueError):
            StockService.create_movement(tenant, u, 'OUT', -5, product=p)
        assert p.variants.first().current_stock == 10

    def test_quantidade_decimal_na_tela(self):
        u, tenant = _member('OWNER')
        p = Product.objects.create(tenant=tenant, name='Fio', sku='FIO-1')
        _client(u).post('/inventory/movements/add/', {
            'product_identifier': 'FIO-1', 'type': 'IN', 'quantity': '2,5'})
        assert p.variants.first().current_stock == Decimal('2.5')

    def test_quantidade_invalida_nao_da_500(self):
        u, tenant = _member('OWNER')
        Product.objects.create(tenant=tenant, name='Fio', sku='FIO-1')
        r = _client(u).post('/inventory/movements/add/', {
            'product_identifier': 'FIO-1', 'type': 'IN', 'quantity': 'abc'})
        assert r.status_code == 200

    def test_local_de_outra_empresa_recusado(self):
        from apps.inventory.models import Location
        u, tenant = _member('OWNER')
        p = Product.objects.create(tenant=tenant, name='Fio', sku='FIO-1')
        alheio = Location.objects.create(tenant=TenantFactory(), name='Outro', code='X1')
        with pytest.raises(ValueError):
            StockService.create_movement(tenant, u, 'IN', 1, product=p, location_id=alheio.pk)


@pytest.mark.django_db
def test_relatorio_escapa_nome_de_categoria_e_serializa_tendencia():
    u, tenant = _member('OWNER')
    cat = Category.objects.create(tenant=tenant, name='</script><script>alert(1)</script>')
    p = Product.objects.create(tenant=tenant, name='X', category=cat)
    StockService.create_movement(tenant, u, 'IN', 2, product=p, unit_cost=10)
    html = _client(u).get('/app/analytics/').content.decode()
    assert '<script>alert(1)</script>' not in html
    assert 'datetime.date' not in html and "Decimal(" not in html


@pytest.mark.django_db
@pytest.mark.parametrize('quantity', ['NaN', 'Infinity', '-Infinity', '0', '-1'])
def test_entrada_recusa_quantidade_nao_positiva_ou_nao_finita(quantity):
    u, tenant = _member('OWNER')
    p = Product.objects.create(tenant=tenant, name='Fio', sku='FIO-1')
    with pytest.raises(ValueError):
        StockService.create_movement(tenant, u, 'IN', quantity, product=p)
    assert p.variants.first().current_stock == 0


@pytest.mark.django_db
def test_mobile_trial_vencido_nao_altera_estoque():
    from django.utils import timezone
    u, tenant = _member('OPERATOR')
    tenant.subscription_status = 'TRIAL'
    tenant.trial_ends_at = timezone.now() - timezone.timedelta(days=1)
    tenant.save()
    p = Product.objects.create(tenant=tenant, name='Fio', sku='FIO-1')
    _client(u).post('/mobile/move/', {'type': 'IN', 'sku': 'FIO-1', 'quantity': '5'})
    assert p.variants.first().current_stock == 0


@pytest.mark.django_db
def test_api_header_invalido_nao_da_500():
    u, _ = _member('OWNER')
    api = APIClient()
    api.force_authenticate(u)
    assert api.get('/api/v1/products/search/', HTTP_X_TENANT_ID='invalido').status_code == 400


@pytest.mark.django_db
def test_login_conta_inativa_nao_autentica():
    u, _ = _member('OWNER')
    u.is_active = False
    u.save()
    assert authenticate(username=u.username, password=PWD) is None
