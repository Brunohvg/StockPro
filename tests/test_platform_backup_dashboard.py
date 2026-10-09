"""Painel global de backup: isolamento e indicadores reais."""
import pytest
from django.test import Client
from apps.tenants.models import BackupRun
from tests.factories import UserFactory

@pytest.mark.django_db
def test_backup_dashboard_exige_superusuario():
    user = UserFactory()
    client = Client()
    client.force_login(user)
    response = client.get('/admin-panel/backups/')
    assert response.status_code in (302, 403)

@pytest.mark.django_db
def test_backup_dashboard_global_autenticado():
    user = UserFactory(is_superuser=True, is_staff=True)
    client = Client()
    client.force_login(user)
    response = client.get('/admin-panel/backups/')
    assert response.status_code == 200
    assert b'Central de backups' in response.content
    assert b'Escopo global' in response.content
    assert response.context['dashboard']['total_jobs'] == 0
    BackupRun.objects.create(trigger='beat', status='LOCAL_ONLY')
    response = client.get('/admin-panel/backups/')
    assert response.context['dashboard']['total_jobs'] == 1
    assert response.context['dashboard']['success_14d'] == 1

@pytest.mark.django_db
def test_backup_dashboard_avisa_quando_worker_sem_sinal(settings):
    from django.core.cache import cache
    from apps.tenants.platform import HEARTBEAT_KEY
    cache.delete(HEARTBEAT_KEY)
    user = UserFactory(is_superuser=True, is_staff=True)
    client = Client()
    client.force_login(user)
    result = client.get('/admin-panel/backups/')
    assert result.status_code == 200
    assert result.context['worker_health']['ok'] is False
    assert 'sem sinal recente' in result.content.decode()
