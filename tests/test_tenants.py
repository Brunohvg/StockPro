import pytest
from django.test import Client

from apps.accounts.models import TenantMembership
from tests.factories import TenantFactory, TenantMembershipFactory


@pytest.mark.django_db
class TestTenantLogic:
    def test_create_tenant_with_plan(self, tenant):
        """Verify tenant is created with active subscription"""
        assert tenant.name
        assert tenant.plan
        assert tenant.subscription_status == 'ACTIVE'
        assert tenant.is_active

    def test_tenant_limits(self, tenant):
        """Verify plan limits calculation"""
        # Default plan limits (from factory): 50 products, 3 users
        assert tenant.plan.max_products == 50
        assert tenant.products_limit_reached is False

    def test_add_member(self, tenant, user):
        """Verify adding a member to tenant"""
        membership = TenantMembership.objects.create(
            tenant=tenant,
            user=user,
            role='ADMIN'
        )
        assert membership in tenant.memberships.all()
        assert membership.is_admin is True
        assert tenant.users_count == 1

    def test_owner_permissions(self, member):
        """Verify owner has full permissions"""
        assert member.is_owner is True
        assert member.can_manage_users is True
        assert member.can_manage_billing is True

    def test_multiple_companies_require_explicit_selection(self, user, member):
        second_tenant = TenantFactory()
        TenantMembershipFactory(user=user, tenant=second_tenant, role='ADMIN')
        client = Client()
        client.force_login(user)

        response = client.get('/app/')

        assert response.status_code == 302
        assert response.url == '/select-company/'

    def test_invalid_selected_company_does_not_fall_back_to_another_company(self, user, member):
        second_tenant = TenantFactory()
        TenantMembershipFactory(user=user, tenant=second_tenant, role='ADMIN')
        client = Client()
        client.force_login(user)
        session = client.session
        session['active_tenant_id'] = 999999
        session.save()

        response = client.get('/app/')

        assert response.status_code == 302
        assert response.url == '/select-company/'
