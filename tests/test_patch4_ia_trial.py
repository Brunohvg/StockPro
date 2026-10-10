"""Patch 4.3/4.4: IA só nos planos com IA, com cache e limite diário; trial vencido em modo leitura."""
from datetime import timedelta
from unittest import mock

import pytest
from django.core.cache import cache
from django.test import Client
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import TenantMembership
from apps.core.services import AIService, AIUnavailable, StockService
from apps.products.models import Product
from tests.factories import TenantFactory, UserFactory

PWD = 'Senha!Forte123'
AI_JSON = '{"insights": [{"icon": "x", "title": "Da IA", "text": "t", "type": "info"}]}'


def _member(role='OWNER', tenant=None, **tenant_kwargs):
    tenant = tenant or TenantFactory(**tenant_kwargs)
    u = UserFactory(password=PWD)
    TenantMembership.objects.create(user=u, tenant=tenant, role=role)
    return u, tenant


def _client(u):
    c = Client()
    c.force_login(u)
    return c


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.mark.django_db
class TestIA:
    def test_plano_sem_ia_nao_chama_provedor(self):
        u, t = _member(plan__has_ai_matching=False)
        p = Product.objects.create(tenant=t, name='Caneta', sku='CAN-1')
        StockService.create_movement(t, u, 'IN', 5, product=p, unit_cost=2)
        with mock.patch.object(AIService, 'call_ai') as call:
            html = _client(u).get('/app/analytics/').content.decode()
            r = _client(u).get('/products/api/ai-enhance/?name=Caneta azul')
        call.assert_not_called()
        assert r.status_code == 403
        assert 'Análise com IA disponível no plano Profissional' in html

    def test_insights_ficam_em_cache(self):
        u, t = _member(plan__has_ai_matching=True)
        # Patch 10: a IA só entra com histórico de vendas (14 dias) e venda no período
        from apps.inventory.models import StockMovement
        p = Product.objects.create(tenant=t, name='Caneta', sku='CAN-1', sale_price=5)
        StockService.create_movement(t, u, 'IN', 10, product=p, unit_cost=2)
        old = StockService.create_movement(t, u, 'OUT', 1, product=p)
        StockMovement.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=20))
        StockService.create_movement(t, u, 'OUT', 2, product=p)
        with mock.patch.object(AIService, 'call_ai', return_value=AI_JSON) as call:
            c = _client(u)
            for _ in range(3):
                assert 'Da IA' in c.get('/app/analytics/').content.decode()
        assert call.call_count == 1

    def test_limite_diario_por_empresa(self, monkeypatch):
        monkeypatch.setenv('AI_DAILY_LIMIT_PER_TENANT', '2')
        _, t = _member(plan__has_ai_matching=True)
        with mock.patch.object(AIService, 'call_ai', return_value='{}'):
            AIService.call_for_tenant(t, 'p')
            AIService.call_for_tenant(t, 'p')
            with pytest.raises(AIUnavailable) as exc:
                AIService.call_for_tenant(t, 'p')
        assert exc.value.status == 429
        # outra empresa não é afetada
        _, outra = _member(plan__has_ai_matching=True)
        with mock.patch.object(AIService, 'call_ai', return_value='{}'):
            AIService.call_for_tenant(outra, 'p')

    def test_trial_vencido_sem_ia(self):
        _, t = _member(plan__has_ai_matching=True, subscription_status='TRIAL')
        t.trial_ends_at = timezone.now() - timedelta(days=1)
        t.save()
        with pytest.raises(AIUnavailable):
            AIService.check_tenant_access(t)

    def test_matcher_sem_ia_usa_reconhecimento_local(self):
        from apps.inventory.services.matcher import MatchResult, ProductMatcher
        _, t = _member(plan__has_ai_matching=False)
        parsed = MatchResult(confidence=0.4, action='NEW')
        item = mock.Mock(description='LINHA AZUL', supplier_sku='X1')
        with mock.patch.object(AIService, 'call_ai') as call:
            assert ProductMatcher._try_ai_enhancement(item, t, None, parsed) is parsed
        call.assert_not_called()


@pytest.mark.django_db
class TestTrialVencido:
    def _expired(self, role='OWNER'):
        u, t = _member(role, subscription_status='TRIAL')
        t.trial_ends_at = timezone.now() - timedelta(days=1)
        t.save()
        return u, t

    def test_leitura_liberada(self):
        u, _ = self._expired()
        c = _client(u)
        assert c.get('/products/').status_code == 200
        assert c.get('/app/analytics/').status_code == 200

    @pytest.mark.parametrize('path,data', [
        ('/products/add/', {'name': 'X', 'product_type': 'SIMPLE'}),
        ('/settings/', {'company_name': 'X'}),
        ('/inventory/locations/create/', {'name': 'X', 'code': 'X'}),
        ('/partners/suppliers/add/', {'company_name': 'X'}),
    ])
    def test_gravacao_bloqueada_em_qualquer_tela(self, path, data):
        u, t = self._expired()
        r = _client(u).post(path, data)
        assert r.status_code == 302 and r.url.endswith('/billing/')
        assert not Product.objects.filter(tenant=t).exists()

    def test_mobile_bloqueado(self):
        u, t = self._expired('OPERATOR')
        p = Product.objects.create(tenant=t, name='Caneta', sku='CAN-1')
        _client(u).post('/mobile/move/', {'type': 'IN', 'sku': 'CAN-1', 'quantity': '1'})
        assert p.variants.first().current_stock == 0

    def test_htmx_recebe_403_json(self):
        u, _ = self._expired()
        r = _client(u).post('/products/add/', {'name': 'X'}, HTTP_HX_REQUEST='true')
        assert r.status_code == 403 and 'modo leitura' in r.json()['error']

    def test_api_bloqueia_escrita_e_libera_leitura(self):
        u, _ = self._expired()
        api = APIClient()
        tok = api.post('/api/v1/auth/token/', {'username': u.username, 'password': PWD},
                       format='json').data['access']
        api.credentials(HTTP_AUTHORIZATION=f'Bearer {tok}')
        assert api.get('/api/v1/products/').status_code == 200
        assert api.post('/api/v1/products/', {'name': 'X', 'sku': 'X'}, format='json').status_code == 403

    def test_suspensao_automatica_desligada_por_padrao(self, settings):
        from apps.tenants.tasks import cleanup_expired_trials
        _, t = self._expired()
        t.trial_ends_at = timezone.now() - timedelta(days=90)
        t.save()
        cleanup_expired_trials()
        t.refresh_from_db()
        assert t.subscription_status == 'TRIAL'
        settings.TRIAL_SUSPEND_AFTER_DAYS = 30
        cleanup_expired_trials()
        t.refresh_from_db()
        assert t.subscription_status == 'SUSPENDED'

    def test_trial_valido_grava_normalmente(self):
        u, t = _member(subscription_status='TRIAL')
        r = _client(u).post('/products/add/', {'name': 'Caneta', 'sku': 'C1', 'product_type': 'SIMPLE', 'uom': 'UN',
                                               'current_stock': 0, 'minimum_stock': 0})
        assert Product.objects.filter(tenant=t, sku='C1').exists(), r.content[:500]

