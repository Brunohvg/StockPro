import pytest

from apps.accounts.models import TenantMembership


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
