import pytest
from rest_framework.test import APIClient

from tests.factories import TenantFactory, TenantMembershipFactory, UserFactory


@pytest.fixture
def client():
    return APIClient()

@pytest.fixture
def user():
    return UserFactory()

@pytest.fixture
def tenant():
    return TenantFactory()

@pytest.fixture
def member(user, tenant):
    return TenantMembershipFactory(user=user, tenant=tenant, role='OWNER')


@pytest.fixture(autouse=True)
def _clear_cache(settings):
    """Throttling da API usa o cache; limpa entre testes."""
    settings.CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache', 'LOCATION': 'stockpro-tests'}}
    from django.core.cache import cache
    cache.clear()
    yield
    cache.clear()


@pytest.fixture(autouse=True)
def _static_sem_manifest(request, settings):
    """Os templates usam {% static %} (CSS/JS servidos pelo próprio sistema).

    Em produção o manifest vem do collectstatic do entrypoint; nos testes não há
    collectstatic, então usamos o storage simples. O teste que confere o manifest
    de verdade (test_admin_staticfiles) continua com o storage de produção.
    """
    if request.node.module.__name__.endswith('test_admin_staticfiles'):
        yield
        return
    settings.STORAGES = {**settings.STORAGES, 'staticfiles': {
        'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}}
    yield
