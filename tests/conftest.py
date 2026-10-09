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
