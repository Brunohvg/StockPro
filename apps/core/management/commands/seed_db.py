from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from apps.tenants.models import Plan, Tenant
from apps.accounts.models import TenantMembership, MembershipRole
from apps.core.models import SystemSetting

class Command(BaseCommand):
    help = 'Seeds the database with initial data'

    def handle(self, *args, **kwargs):
        # Create Plans
        plans = [
            {'name': 'FREE', 'display_name': 'Gratuito', 'price': 0, 'max_products': 50, 'max_users': 3},
            {'name': 'STARTER', 'display_name': 'Starter', 'price': 29.90, 'max_products': 500, 'max_users': 5},
            {'name': 'PRO', 'display_name': 'Pro', 'price': 59.90, 'max_products': 2000, 'max_users': 15},
            {'name': 'ENTERPRISE', 'display_name': 'Enterprise', 'price': 199.90, 'max_products': 10000, 'max_users': 50},
        ]

        for p_data in plans:
            Plan.objects.update_or_create(name=p_data['name'], defaults=p_data)
        self.stdout.write(self.style.SUCCESS('Plans created/updated.'))

        # Create Default Tenant
        plan_free = Plan.objects.get(name='FREE')
        tenant, created = Tenant.objects.get_or_create(
            name='Empresa Demo',
            defaults={'plan': plan_free, 'subscription_status': 'TRIAL'}
        )

        if created:
            self.stdout.write(self.style.SUCCESS(f'Tenant created: {tenant.name}'))
        else:
            self.stdout.write(self.style.WARNING(f'Tenant already exists: {tenant.name}'))

        # Create System Settings
        SystemSetting.get_settings(tenant)

        # Create Superuser with TenantMembership
        if not User.objects.filter(username='admin').exists():
            user = User.objects.create_superuser('admin', 'admin@example.com', 'admin123')
            TenantMembership.objects.create(user=user, tenant=tenant, role=MembershipRole.OWNER)
            self.stdout.write(self.style.SUCCESS('Superuser created: admin / admin123'))
        else:
            # Ensure admin has membership
            user = User.objects.get(username='admin')
            TenantMembership.objects.get_or_create(
                user=user,
                tenant=tenant,
                defaults={'role': MembershipRole.OWNER}
            )
            self.stdout.write(self.style.WARNING('Superuser already exists. Ensured membership.'))

