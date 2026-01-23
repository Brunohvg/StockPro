import pytest
from django.conf import settings

from apps.tenants.models import Tenant


@pytest.mark.django_db
def test_smoke_settings():
    """Verify vital settings are configured"""
    assert settings.AUTH_USER_MODEL
    assert 'apps.tenants' in settings.INSTALLED_APPS

@pytest.mark.django_db
def test_db_interaction(tenant):
    """Verify Factory Boy and DB access"""
    assert Tenant.objects.count() == 1
    assert tenant.name is not None
    assert tenant.plan is not None

@pytest.mark.django_db
def test_create_user(user):
    """Verify user creation"""
    assert user.check_password("password123")
