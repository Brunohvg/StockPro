"""Patch 7: Central da plataforma (/admin-panel/)."""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core.cache import cache
from django.test import Client
from django.utils import timezone

from apps.accounts.models import TenantMembership
from apps.tenants import platform
from apps.tenants.models import Plan, Tenant, TenantEvent
from apps.tenants.tasks import cleanup_expired_trials, platform_heartbeat
from tests.factories import (PlanFactory, ProductFactory, StockMovementFactory, TenantFactory,
                             TenantMembershipFactory, UserFactory)

HOME = '/admin-panel/'
LIST = '/admin-panel/empresas/'


@pytest.fixture
def admin_user():
    u = UserFactory(is_superuser=True, is_staff=True)
    TenantMembership.objects.create(user=u, tenant=TenantFactory(name='Plataforma'), role='OWNER')
    return u


@pytest.fixture
def admin_client(admin_user):
    c = Client()
    c.force_login(admin_user)
    return c


@pytest.fixture
def loja():
    t = TenantFactory(name='Loja Bibelô', subscription_status='TRIAL',
                      plan=PlanFactory(display_name='Gratuito', price=0, max_products=10, max_users=2))
    TenantMembershipFactory(tenant=t, role='OWNER', user=UserFactory(email='dono@bibelo.com', first_name='Ana'))
    return t


def _action(client, tenant, **data):
    return client.post(f'/admin-panel/empresas/{tenant.pk}/acao/', data, follow=True)


@pytest.mark.django_db
class TestAcesso:
    @pytest.mark.parametrize('url', [HOME, LIST, '/admin-panel/empresas.csv', '/admin-panel/planos/',
                                     '/admin-panel/saude/', '/admin-panel/atividade/',
                                     '/admin-panel/planos/novo/'])
    def test_usuario_comum_nao_entra(self, url, member):
        c = Client()
        c.force_login(member.user)
        r = c.get(url)
        assert r.status_code == 302 and '/admin-panel' not in r['Location']

    def test_anonimo_vai_para_login(self):
        r = Client().get(HOME)
        assert r.status_code == 302 and 'login' in r['Location']

    def test_acao_de_usuario_comum_nao_muda_nada(self, member, loja):
        c = Client()
        c.force_login(member.user)
        c.post(f'/admin-panel/empresas/{loja.pk}/acao/', {'action': 'activate'})
        loja.refresh_from_db()
        assert loja.subscription_status == 'TRIAL'
        assert not TenantEvent.objects.filter(tenant=loja).exists()

    def test_acao_so_por_post(self, admin_client, loja):
        assert admin_client.get(f'/admin-panel/empresas/{loja.pk}/acao/').status_code == 405


@pytest.mark.django_db
class TestXSS:
    def test_nome_malicioso_nao_vira_script(self, admin_client):
        evil = "Loja');alert(document.domain);//<script>x()</script>"
        t = TenantFactory(name=evil)
        platform.add_note(t, "nota", None)
        for url in (HOME, LIST, f'/admin-panel/empresas/{t.pk}/', '/admin-panel/atividade/'):
            html = admin_client.get(url).content.decode()
            assert '<script>x()</script>' not in html
            assert "openModal(" not in html
            assert 'Loja&#x27;);alert' in html


@pytest.mark.django_db
class TestVisaoGeral:
    def test_home_mostra_indicadores(self, admin_client, loja):
        TenantFactory(subscription_status='ACTIVE', plan=PlanFactory(price=Decimal('99.90')))
        r = admin_client.get(HOME)
        assert r.status_code == 200
        assert 'Loja Bibelô' in r.content.decode()  # cadastros recentes
        assert r.context['ov'].mrr >= Decimal('99.90')
        assert 'dono@bibelo.com' in admin_client.get(LIST).content.decode()

    def test_mrr_ignora_suspensa_e_teste(self, loja):
        TenantFactory(subscription_status='SUSPENDED', plan=PlanFactory(price=50))
        TenantFactory(subscription_status='ACTIVE', is_active=False, plan=PlanFactory(price=70))
        ativa = TenantFactory(subscription_status='ACTIVE', plan=PlanFactory(price=30))
        assert platform.overview().mrr == ativa.plan.price + sum(
            t.plan.price for t in Tenant.objects.filter(subscription_status='ACTIVE', is_active=True)
            .exclude(pk=ativa.pk))

    def test_busca_por_email_do_dono(self, admin_client, loja):
        TenantFactory(name='Outra')
        r = admin_client.get(LIST, {'q': 'dono@bibelo'})
        names = [t.name for t in r.context['page']]
        assert names == ['Loja Bibelô']

    def test_filtro_teste_vencendo_e_vencido(self, admin_client, loja):
        Tenant.objects.filter(pk=loja.pk).update(trial_ends_at=timezone.now() + timedelta(days=3))
        vencida = TenantFactory(subscription_status='TRIAL')
        Tenant.objects.filter(pk=vencida.pk).update(trial_ends_at=timezone.now() - timedelta(days=1))
        ending = [t.pk for t in admin_client.get(LIST, {'f': 'trial_ending'}).context['page']]
        expired = [t.pk for t in admin_client.get(LIST, {'f': 'trial_expired'}).context['page']]
        assert ending == [loja.pk] and expired == [vencida.pk]

    def test_sem_uso_e_perto_do_limite(self, admin_client, loja):
        Tenant.objects.filter(pk=loja.pk).update(created_at=timezone.now() - timedelta(days=30))
        for _ in range(8):
            ProductFactory(tenant=loja)
        idle = [t.pk for t in admin_client.get(LIST, {'f': 'idle'}).context['page']]
        near = [t.pk for t in admin_client.get(LIST, {'f': 'near_limit'}).context['page']]
        assert loja.pk in idle and loja.pk in near

    def test_movimentacao_tira_de_sem_uso(self, loja):
        Tenant.objects.filter(pk=loja.pk).update(created_at=timezone.now() - timedelta(days=30))
        StockMovementFactory(tenant=loja)
        t = platform.decorate(platform.annotated_tenants().get(pk=loja.pk))
        assert t.n_moves_30d == 1 and not t.is_idle

    def test_csv(self, admin_client, loja):
        r = admin_client.get('/admin-panel/empresas.csv', {'q': 'Bibelô'})
        body = r.content.decode('utf-8')
        assert r['Content-Type'].startswith('text/csv')
        assert body.startswith('﻿')
        lines = body.strip().splitlines()
        assert len(lines) == 2 and 'Loja Bibelô;' in lines[1] and 'dono@bibelo.com' in lines[1]

    def test_ficha(self, admin_client, loja):
        platform.add_note(loja, "Ligar sexta", None)
        r = admin_client.get(f'/admin-panel/empresas/{loja.pk}/')
        assert r.status_code == 200
        html = r.content.decode()
        assert 'Ligar sexta' in html and 'Ana' in html

    def test_sem_n_mais_1(self, admin_client, django_assert_max_num_queries):
        for _ in range(15):
            TenantMembershipFactory(tenant=TenantFactory())
        for url in (HOME, LIST):
            with django_assert_max_num_queries(30):
                admin_client.get(url)


@pytest.mark.django_db
class TestAcoes:
    def test_trocar_plano_grava_historico(self, admin_client, admin_user, loja):
        pro = PlanFactory(display_name='Pro', max_products=0)
        _action(admin_client, loja, action='plan', plan_id=pro.pk, reason='pediu upgrade')
        loja.refresh_from_db()
        assert loja.plan == pro
        e = TenantEvent.objects.get(tenant=loja, kind='PLAN')
        assert e.actor == admin_user and e.reason == 'pediu upgrade' and 'Pro' in e.message

    def test_plano_menor_que_uso_e_recusado(self, admin_client, loja):
        for _ in range(3):
            ProductFactory(tenant=loja)
        pequeno = PlanFactory(display_name='Mini', max_products=2)
        r = _action(admin_client, loja, action='plan', plan_id=pequeno.pk)
        loja.refresh_from_db()
        assert loja.plan.display_name == 'Gratuito'
        assert 'permite 2' in r.content.decode()

    def test_suspender_exige_motivo(self, admin_client, loja):
        _action(admin_client, loja, action='suspend', reason='  ')
        loja.refresh_from_db()
        assert loja.subscription_status == 'TRIAL'
        _action(admin_client, loja, action='suspend', reason='calote')
        loja.refresh_from_db()
        assert loja.subscription_status == 'SUSPENDED'
        assert TenantEvent.objects.get(tenant=loja, kind='STATUS').reason == 'calote'

    def test_ativar_libera_acesso_bloqueado(self, admin_client, loja):
        Tenant.objects.filter(pk=loja.pk).update(is_active=False, subscription_status='SUSPENDED')
        _action(admin_client, loja, action='activate')
        loja.refresh_from_db()
        assert loja.is_active and loja.subscription_status == 'ACTIVE'

    def test_voltar_para_teste_da_novo_prazo(self, admin_client, loja):
        Tenant.objects.filter(pk=loja.pk).update(subscription_status='CANCELLED',
                                                 trial_ends_at=timezone.now() - timedelta(days=40))
        _action(admin_client, loja, action='back_to_trial')
        loja.refresh_from_db()
        assert loja.subscription_status == 'TRIAL' and loja.trial_ends_at > timezone.now()

    def test_estender_teste_por_dias_e_data(self, admin_client, loja):
        Tenant.objects.filter(pk=loja.pk).update(trial_ends_at=timezone.now() - timedelta(days=2))
        _action(admin_client, loja, action='trial', days='10')
        loja.refresh_from_db()
        assert 9 <= (loja.trial_ends_at - timezone.now()).days <= 10
        alvo = timezone.localdate() + timedelta(days=60)
        _action(admin_client, loja, action='trial', until=alvo.isoformat())
        loja.refresh_from_db()
        assert timezone.localtime(loja.trial_ends_at).date() == alvo
        assert TenantEvent.objects.filter(tenant=loja, kind='TRIAL').count() == 2

    @pytest.mark.parametrize('days', ['0', '400', 'abc'])
    def test_estender_teste_valores_invalidos(self, admin_client, loja, days):
        before = Tenant.objects.get(pk=loja.pk).trial_ends_at
        _action(admin_client, loja, action='trial', days=days)
        assert Tenant.objects.get(pk=loja.pk).trial_ends_at == before

    def test_estender_teste_so_em_teste(self, admin_client):
        t = TenantFactory(subscription_status='ACTIVE')
        r = _action(admin_client, t, action='trial', days='5')
        assert 'Só dá para estender' in r.content.decode()

    def test_vencimento(self, admin_client, loja):
        _action(admin_client, loja, action='due_date', due_date='2026-11-10', reason='Pix')
        loja.refresh_from_db()
        assert loja.next_due_date == date(2026, 11, 10)
        _action(admin_client, loja, action='due_date', due_date='')
        loja.refresh_from_db()
        assert loja.next_due_date is None
        assert TenantEvent.objects.filter(tenant=loja, kind='DUE_DATE').count() == 2

    def test_vencimento_data_invalida(self, admin_client, loja):
        r = _action(admin_client, loja, action='due_date', due_date='31/02/2026')
        assert 'Data inválida' in r.content.decode()

    def test_vencido_aparece_no_filtro(self, admin_client):
        t = TenantFactory(subscription_status='ACTIVE', next_due_date=timezone.localdate() - timedelta(days=1))
        assert [x.pk for x in admin_client.get(LIST, {'f': 'overdue'}).context['page']] == [t.pk]

    def test_nota(self, admin_client, loja):
        _action(admin_client, loja, action='note', note='Primeira linha\nresto')
        e = TenantEvent.objects.get(tenant=loja, kind='NOTE')
        assert e.message == 'Primeira linha' and e.reason == 'Primeira linha\nresto'

    def test_acao_desconhecida(self, admin_client, loja):
        r = _action(admin_client, loja, action='delete_everything')
        assert 'Ação desconhecida' in r.content.decode()


@pytest.mark.django_db
class TestPlanos:
    def test_lista_e_receita(self, admin_client):
        p = PlanFactory(display_name='Pro', price=Decimal('49.90'))
        TenantFactory(plan=p, subscription_status='ACTIVE')
        TenantFactory(plan=p, subscription_status='ACTIVE')
        TenantFactory(plan=p, subscription_status='TRIAL')
        r = admin_client.get('/admin-panel/planos/')
        plan = next(x for x in r.context['plans'] if x.pk == p.pk)
        assert plan.n == 3 and plan.n_active == 2 and plan.revenue == Decimal('99.80')

    def _data(self, **kw):
        data = {'display_name': 'Pro', 'name': 'pro', 'price': '59.90', 'max_products': '500',
                'max_users': '5', 'features': ''}
        data.update(kw)
        return data

    def test_criar(self, admin_client):
        admin_client.post('/admin-panel/planos/novo/', self._data())
        assert Plan.objects.get(name='pro').price == Decimal('59.90')

    def test_preco_negativo(self, admin_client):
        r = admin_client.post('/admin-panel/planos/novo/', self._data(price='-1'))
        assert r.status_code == 200 and not Plan.objects.filter(name='pro').exists()

    def test_editar_registra_nas_empresas(self, admin_client, loja):
        plan = loja.plan
        admin_client.post(f'/admin-panel/planos/{plan.pk}/', self._data(name=plan.name, price='19.90'))
        plan.refresh_from_db()
        assert plan.price == Decimal('19.90')
        assert TenantEvent.objects.filter(tenant=loja, kind='PLAN').exists()

    def test_limite_abaixo_do_uso_e_recusado(self, admin_client, loja):
        for _ in range(3):
            ProductFactory(tenant=loja)
        plan = loja.plan
        r = admin_client.post(f'/admin-panel/planos/{plan.pk}/', self._data(name=plan.name, max_products='2'))
        plan.refresh_from_db()
        assert plan.max_products == 10 and 'Loja Bibelô' in r.content.decode()


@pytest.mark.django_db
class TestSaudeESeguranca:
    def test_heartbeat(self):
        assert not platform.platform_health()['worker']['ok']
        platform_heartbeat()
        assert platform.platform_health()['worker']['ok']

    def test_heartbeat_velho(self):
        cache.set(platform.HEARTBEAT_KEY, timezone.now() - timedelta(hours=1))
        assert not platform.platform_health()['worker']['ok']

    def test_desbloquear_login(self, admin_client, loja, settings):
        from axes.models import AccessAttempt
        owner = loja.memberships.get().user
        a = AccessAttempt.objects.create(username=owner.username, ip_address='10.0.0.1', user_agent='x',
                                         failures_since_start=settings.AXES_FAILURE_LIMIT,
                                         get_data='', post_data='', http_accept='', path_info='/')
        assert a in platform.locked_logins()
        r = admin_client.post(f'/admin-panel/seguranca/desbloquear/{a.pk}/',
                              {'next': f'/admin-panel/empresas/{loja.pk}/'})
        assert r['Location'] == f'/admin-panel/empresas/{loja.pk}/'
        assert not AccessAttempt.objects.exists()
        assert TenantEvent.objects.filter(tenant=loja, kind='SECURITY').exists()

    def test_desbloquear_nao_redireciona_para_fora(self, admin_client):
        from axes.models import AccessAttempt
        a = AccessAttempt.objects.create(username='x', ip_address='10.0.0.2', user_agent='x',
                                         failures_since_start=9, get_data='', post_data='',
                                         http_accept='', path_info='/')
        r = admin_client.post(f'/admin-panel/seguranca/desbloquear/{a.pk}/', {'next': 'https://evil.example/'})
        assert r['Location'] == '/admin-panel/saude/'


@pytest.mark.django_db
class TestEventosAutomaticos:
    def test_cadastro_grava_evento(self):
        Plan.objects.get_or_create(name='GRATUITO', defaults={'display_name': 'Gratuito'})
        Client().post('/signup/', {'company_name': 'Nova Loja', 'first_name': 'Bia', 'email': 'bia@x.com',
                                   'password': 'Senha-forte-123'})
        t = Tenant.objects.get(name='Nova Loja')
        assert TenantEvent.objects.get(tenant=t).kind == 'CREATED'

    def test_suspensao_automatica_grava_evento(self, settings):
        settings.TRIAL_SUSPEND_AFTER_DAYS = 3
        t = TenantFactory(subscription_status='TRIAL')
        Tenant.objects.filter(pk=t.pk).update(trial_ends_at=timezone.now() - timedelta(days=10))
        cleanup_expired_trials()
        t.refresh_from_db()
        assert t.subscription_status == 'SUSPENDED'
        assert TenantEvent.objects.get(tenant=t, kind='STATUS').actor is None


@pytest.mark.django_db
class TestPatch8Navegacao:
    """Patch 8: cada área da Central tem rota própria e o menu marca onde você está."""

    @pytest.mark.parametrize('url,section', [
        (HOME, 'home'), (LIST, 'tenants'), ('/admin-panel/planos/', 'plans'),
        ('/admin-panel/planos/novo/', 'plans'), ('/admin-panel/saude/', 'health'),
        ('/admin-panel/atividade/', 'activity'), ('/admin-panel/backups/', 'backups'),
    ])
    def test_menu_marca_a_secao(self, admin_client, url, section):
        r = admin_client.get(url)
        assert r.status_code == 200 and r.context['section'] == section
        html = r.content.decode()
        assert html.count('pf-nav-item-active') == 1
        assert 'tenants/platform/base_platform.html' in [t.name for t in r.templates]

    def test_ficha_marca_empresas(self, admin_client, loja):
        assert admin_client.get(f'/admin-panel/empresas/{loja.pk}/').context['section'] == 'tenants'

    def test_menu_sem_ancoras_nem_links_duplicados(self, admin_client):
        html = admin_client.get(HOME).content.decode()
        assert "admin-panel/#" not in html
        assert html.count('href="/admin/"') == 1
        assert 'css/platform.css' not in html

    def test_voltar_ao_sistema(self, admin_client):
        assert 'href="/app/"' in admin_client.get(HOME).content.decode()

    def test_mensagens_com_cor_por_tipo(self, admin_client, loja):
        r = _action(admin_client, loja, action='suspend', reason='')
        assert 'border-rose-200' in r.content.decode()


@pytest.mark.django_db
class TestPatch8SaudeEAtividade:
    def test_configuracao_de_producao(self, admin_client, settings):
        settings.BACKUP_S3_BUCKET = ''
        r = admin_client.get('/admin-panel/saude/')
        checks = {c['label']: c for c in r.context['checks']}
        assert checks['Cópia externa do backup']['ok'] is False
        settings.BACKUP_S3_BUCKET = 'bucket-x'
        checks = {c['label']: c for c in admin_client.get('/admin-panel/saude/').context['checks']}
        assert checks['Cópia externa do backup']['ok'] is True

    def test_configuracao_nao_mostra_segredo(self, admin_client, settings):
        settings.BACKUP_ENCRYPTION_PASSPHRASE = 'segredo-super-secreto-123'
        assert 'segredo-super-secreto-123' not in admin_client.get('/admin-panel/saude/').content.decode()

    def test_atividade_filtra_por_tipo_e_busca(self, admin_client, loja):
        outra = TenantFactory(name='Outra Loja')
        platform.add_note(loja, "ligar amanhã", None)
        platform.record(outra, 'PLAN', "Plano: A → B")
        r = admin_client.get('/admin-panel/atividade/', {'kind': 'NOTE'})
        assert [e.tenant_id for e in r.context['page']] == [loja.pk]
        r = admin_client.get('/admin-panel/atividade/', {'q': 'Outra'})
        assert [e.tenant_id for e in r.context['page']] == [outra.pk]

    def test_atividade_pagina(self, admin_client, loja):
        for i in range(55):
            platform.record(loja, 'NOTE', f"nota {i}")
        r = admin_client.get('/admin-panel/atividade/', {'page': 2})
        assert len(r.context['page']) == 5

    def test_home_mostra_atividade_recente_sem_notas(self, admin_client, loja):
        platform.add_note(loja, "nota interna", None)
        platform.record(loja, 'PLAN', "Plano: X → Y")
        kinds = [e.kind for e in admin_client.get(HOME).context['recent_events']]
        assert kinds == ['PLAN']

    def test_lista_mantem_filtros_ao_trocar_atalho(self, admin_client, loja):
        r = admin_client.get(LIST, {'q': 'Bibelô', 'f': 'idle'})
        assert r.context['chips_qs'] == 'q=Bibel%C3%B4'
