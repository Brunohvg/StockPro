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
