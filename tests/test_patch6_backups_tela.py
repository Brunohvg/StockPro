"""Patch 6.2: tela de backups no painel da plataforma e aviso de backup para o cliente."""
from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone

from apps.accounts.models import TenantMembership
from apps.tenants import backup_status, backup_task
from apps.tenants.models import BackupRun
from tests.factories import TenantFactory, UserFactory
from tests.test_patch4_backup import env  # noqa: F401  (fixture: bucket falso + dump falso)

URL = '/admin-panel/backups/'


@pytest.fixture
def admin_client():
    u = UserFactory(is_superuser=True, is_staff=True)
    TenantMembership.objects.create(user=u, tenant=TenantFactory(), role='OWNER')
    c = Client()
    c.force_login(u)
    return c


@pytest.fixture
def run_now(monkeypatch):
    """Executa a tarefa na hora, em vez de mandar para a fila do Celery."""
    for task in (backup_task.manual_backup, backup_task.verify_backup):
        monkeypatch.setattr(task, 'delay', lambda *a, _t=task, **kw: _t(*a, **kw))


def _run(status, hours_ago=1, trigger='beat', **kw):
    when = timezone.now() - timedelta(hours=hours_ago)
    run = BackupRun.objects.create(trigger=trigger, status=status, **kw)
    BackupRun.objects.filter(pk=run.pk).update(started_at=when, finished_at=when)
    return BackupRun.objects.get(pk=run.pk)


@pytest.mark.django_db
class TestSituacao:
    def test_sem_backup(self, env):
        assert backup_status.health().level == 'danger'

    def test_em_dia(self, env):
        _run('SUCCESS', encrypted=True)
        h = backup_status.health()
        assert h.level == 'ok' and 'criptografado' in h.detail

    def test_so_local(self, env):
        _run('LOCAL_ONLY')
        assert backup_status.health().level == 'warning'

    def test_ultimo_falhou(self, env):
        _run('SUCCESS', hours_ago=25)
        _run('FAILED', hours_ago=1)
        assert backup_status.health().headline == "O último backup falhou"

    def test_atrasado(self, env):
        _run('SUCCESS', hours_ago=30)
        assert backup_status.health().headline == "Backup atrasado"

    def test_conferencia_nao_conta_como_backup(self, env):
        _run('SUCCESS', hours_ago=30)
        _run('SUCCESS', hours_ago=1, trigger='verify')
        h = backup_status.health()
        assert h.headline == "Backup atrasado" and h.last_verify is not None


@pytest.mark.django_db
class TestTelaAdmin:
    def test_so_superusuario(self, env, monkeypatch):
        dono = UserFactory()
        TenantMembership.objects.create(user=dono, tenant=TenantFactory(), role='OWNER')
        c = Client()
        c.force_login(dono)
        chamadas = []
        monkeypatch.setattr(backup_task.manual_backup, 'delay', lambda **kw: chamadas.append(kw))
        assert c.get(URL).status_code == 302
        c.post(URL + 'run/')
        c.post(URL + 'verify/')
        assert chamadas == [] and not BackupRun.objects.exists()

    def test_mostra_historico_e_situacao(self, env, admin_client):
        _run('SUCCESS', encrypted=True, db_size_bytes=2048, remote_keys=['stockpro/stockpro_db_x.sql.gz.gpg'])
        _run('FAILED', hours_ago=30, message='CalledProcessError: pg_dump saiu com erro')
        html = admin_client.get(URL).content.decode()
        assert 'Backup em dia' in html
        assert 'pg_dump saiu com erro' in html and 'stockpro_db_x.sql.gz.gpg' in html
        assert '2,0' in html or '2.0' in html  # tamanho formatado
        assert '.gpg"' not in html and 'href="/media' not in html  # nada para baixar

    def test_painel_principal_mostra_faixa(self, env, admin_client):
        html = admin_client.get('/admin-panel/').content.decode()
        assert 'Nenhum backup concluído ainda' in html and URL in html

    def test_fazer_backup_agora(self, env, admin_client, run_now):
        r = admin_client.post(URL + 'run/', follow=True)
        run = BackupRun.objects.get()
        assert run.trigger == 'painel' and run.status == 'SUCCESS', run.message
        assert run.message.startswith('Pedido por')
        assert 'Solicitação enviada à fila' in r.content.decode()

    def test_nao_roda_dois_ao_mesmo_tempo(self, env, admin_client, run_now):
        _run('RUNNING', hours_ago=0.5)
        r = admin_client.post(URL + 'run/', follow=True)
        assert BackupRun.objects.count() == 1
        assert 'em andamento' in r.content.decode()

    def test_backup_preso_nao_bloqueia(self, env, admin_client, run_now):
        _run('RUNNING', hours_ago=5)
        assert 'Interrompido' in admin_client.get(URL).content.decode()
        admin_client.post(URL + 'run/')
        assert BackupRun.objects.filter(trigger='painel', status='SUCCESS').exists()

    def test_conferir_ultimo_backup(self, env, admin_client, run_now):
        admin_client.post(URL + 'run/')
        admin_client.post(URL + 'verify/')
        v = BackupRun.objects.get(trigger='verify')
        assert v.status == 'SUCCESS' and 'íntegro' in v.message
        assert 'Íntegro' in admin_client.get(URL).content.decode()

    def test_conferir_com_senha_errada_registra_falha(self, env, admin_client, run_now, settings):
        admin_client.post(URL + 'run/')
        settings.BACKUP_ENCRYPTION_PASSPHRASE = 'outra-senha-bem-comprida-123'
        admin_client.post(URL + 'verify/')
        assert BackupRun.objects.get(trigger='verify').status == 'FAILED'

    def test_conferir_sem_bucket(self, env, admin_client, run_now, settings):
        settings.BACKUP_S3_BUCKET = ''
        r = admin_client.post(URL + 'verify/', follow=True)
        assert not BackupRun.objects.exists()
        assert 'bucket não está configurado' in r.content.decode()

    def test_fila_fora_do_ar(self, env, admin_client, monkeypatch):
        def boom(**kw):
            raise ConnectionError('redis')
        monkeypatch.setattr(backup_task.manual_backup, 'delay', boom)
        r = admin_client.post(URL + 'run/', follow=True)
        assert 'fila de tarefas' in r.content.decode()


@pytest.mark.django_db
class TestAvisoCliente:
    def _cliente(self):
        u = UserFactory()
        TenantMembership.objects.create(user=u, tenant=TenantFactory(), role='OWNER')
        c = Client()
        c.force_login(u)
        return c

    def test_mostra_quando_backup_recente(self, env):
        _run('SUCCESS', hours_ago=3)
        assert 'Seus dados estão protegidos' in self._cliente().get('/app/export/').content.decode()

    def test_esconde_quando_backup_velho_ou_inexistente(self, env):
        c = self._cliente()
        assert 'Seus dados estão protegidos' not in c.get('/app/export/').content.decode()
        _run('SUCCESS', hours_ago=50)
        _run('SUCCESS', hours_ago=1, trigger='verify')
        assert 'Seus dados estão protegidos' not in c.get('/app/export/').content.decode()
