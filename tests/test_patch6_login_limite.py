"""Patch 6.1: limite de tentativas de login (django-axes) no site, no admin e na API."""
from datetime import timedelta

import pytest
from django.test import Client, RequestFactory
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import TenantMembership
from apps.accounts.security import client_ip
from tests.factories import TenantFactory, UserFactory

PWD = 'Senha!Forte123'
WEB_LOGIN = '/accounts/login/'
API_LOGIN = '/api/v1/auth/token/'


@pytest.fixture
def dono():
    u = UserFactory(email='dono@loja.com', password=PWD)
    TenantMembership.objects.create(user=u, tenant=TenantFactory(), role='OWNER')
    return u


def _web(ip='10.0.0.1'):
    return Client(REMOTE_ADDR=ip)


def _erra(c, username, vezes=5, url=WEB_LOGIN):
    for i in range(vezes):
        r = c.post(url, {'username': username, 'password': 'errada'})
        # a 5ª senha errada já devolve a tela de bloqueio
        assert r.status_code == (429 if i == 4 else 200)


def _entrou(r):
    return r.status_code == 302 and '_auth_user_id' in r.client.session


@pytest.mark.django_db
class TestLoginWeb:
    def test_bloqueia_apos_5_erros_mesmo_com_senha_certa(self, dono):
        c = _web()
        _erra(c, 'dono@loja.com')
        r = c.post(WEB_LOGIN, {'username': 'dono@loja.com', 'password': PWD})
        assert r.status_code == 429
        assert '_auth_user_id' not in c.session
        html = r.content.decode()
        assert 'Muitas tentativas' in html and '15 minutos' in html
        assert r['Retry-After'] == '900'

    def test_quatro_erros_ainda_entra(self, dono):
        c = _web()
        _erra(c, 'dono@loja.com', vezes=4)
        assert _entrou(c.post(WEB_LOGIN, {'username': 'dono@loja.com', 'password': PWD}))

    def test_login_certo_zera_contagem(self, dono):
        c = _web()
        _erra(c, 'dono@loja.com', vezes=4)
        c.post(WEB_LOGIN, {'username': 'dono@loja.com', 'password': PWD})
        c.logout()
        _erra(c, 'dono@loja.com', vezes=4)
        assert _entrou(c.post(WEB_LOGIN, {'username': 'dono@loja.com', 'password': PWD}))

    def test_maiusculas_espacos_e_username_contam_como_mesmo_usuario(self, dono):
        c = _web()
        for nome in ['DONO@loja.com', 'Dono@Loja.com', ' dono@loja.com', dono.username.upper(), 'dono@loja.com ']:
            c.post(WEB_LOGIN, {'username': nome, 'password': 'errada'})
        assert c.post(WEB_LOGIN, {'username': 'dono@loja.com', 'password': PWD}).status_code == 429

    def test_colega_no_mesmo_ip_continua_entrando(self, dono):
        colega = UserFactory(email='caixa@loja.com', password=PWD)
        TenantMembership.objects.create(user=colega, tenant=TenantFactory(), role='OWNER')
        c = _web()
        _erra(c, 'dono@loja.com')
        assert _entrou(_web().post(WEB_LOGIN, {'username': 'caixa@loja.com', 'password': PWD}))

    def test_mesmo_usuario_em_outro_ip_continua_entrando(self, dono):
        _erra(_web('10.0.0.1'), 'dono@loja.com')
        assert _entrou(_web('10.0.0.2').post(WEB_LOGIN, {'username': 'dono@loja.com', 'password': PWD}))

    def test_desbloqueia_depois_do_prazo(self, dono):
        from axes.models import AccessAttempt
        c = _web()
        _erra(c, 'dono@loja.com')
        AccessAttempt.objects.update(attempt_time=timezone.now() - timedelta(minutes=16))
        assert _entrou(c.post(WEB_LOGIN, {'username': 'dono@loja.com', 'password': PWD}))

    def test_admin_do_django_tambem_e_protegido(self, dono):
        dono.is_staff = dono.is_superuser = True
        dono.save()
        c = _web()
        for _ in range(5):
            c.post('/admin/login/', {'username': dono.username, 'password': 'errada'})
        r = c.post('/admin/login/', {'username': dono.username, 'password': PWD})
        assert r.status_code == 429


@pytest.mark.django_db
class TestLoginApi:
    def test_api_bloqueia_com_json(self, dono):
        api = APIClient(REMOTE_ADDR='10.0.0.9')
        for i in range(5):
            r = api.post(API_LOGIN, {'username': 'dono@loja.com', 'password': 'errada'}, format='json')
            assert r.status_code == (429 if i == 4 else 401)
        r = api.post(API_LOGIN, {'username': 'dono@loja.com', 'password': PWD}, format='json')
        assert r.status_code == 429
        body = r.json()
        assert body['code'] == 'login_locked' and body['retry_after_minutes'] == 15
        assert 'access' not in body

    def test_api_funciona_normalmente(self, dono):
        r = APIClient().post(API_LOGIN, {'username': 'dono@loja.com', 'password': PWD}, format='json')
        assert r.status_code == 200 and 'access' in r.data


class TestIpDoCliente:
    def _req(self, xff=None, remote='172.18.0.5'):
        meta = {'REMOTE_ADDR': remote}
        if xff:
            meta['HTTP_X_FORWARDED_FOR'] = xff
        return RequestFactory().post('/accounts/login/', **meta)

    def test_usa_ip_que_o_proxy_acrescentou(self, settings):
        settings.AXES_NUM_PROXIES = 1
        # O cliente tentou forjar "1.1.1.1"; o Traefik acrescentou o IP real no fim.
        assert client_ip(self._req('1.1.1.1, 200.10.20.30')) == '200.10.20.30'

    def test_sem_proxy_usa_remote_addr(self, settings):
        settings.AXES_NUM_PROXIES = 0
        assert client_ip(self._req('1.1.1.1')) == '172.18.0.5'

    def test_sem_cabecalho_usa_remote_addr(self, settings):
        settings.AXES_NUM_PROXIES = 1
        assert client_ip(self._req()) == '172.18.0.5'


@pytest.mark.django_db
def test_limpeza_do_historico_de_login(dono):
    from axes.models import AccessLog
    from apps.accounts.tasks import cleanup_login_logs
    _web().post(WEB_LOGIN, {'username': 'dono@loja.com', 'password': PWD})
    assert AccessLog.objects.count() == 1
    AccessLog.objects.update(attempt_time=timezone.now() - timedelta(days=91))
    assert cleanup_login_logs() == 1
    assert AccessLog.objects.count() == 0
