from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from apps.tenants.models import Plan, Tenant
from apps.accounts.models import UserProfile
from apps.core.models import SystemSetting

class Command(BaseCommand):
    help = 'Seeds the database with initial data'

    def handle(self, *args, **kwargs):
        # Create Plans
        plans = [
            {'name': 'FREE', 'display_name': 'Free', 'price': 0, 'max_products': 50, 'max_users': 1},
            {'name': 'STARTER', 'display_name': 'Starter', 'price': 29.90, 'max_products': 500, 'max_users': 3},
            {'name': 'PRO', 'display_name': 'Pro', 'price': 59.90, 'max_products': 2000, 'max_users': 10},
            {'name': 'ENTERPRISE', 'display_name': 'Enterprise', 'price': 199.90, 'max_products': 10000, 'max_users': 50},
        ]

        for p_data in plans:
            Plan.objects.get_or_create(name=p_data['name'], defaults=p_data)
        self.stdout.write(self.style.SUCCESS('Plans created.'))

        # Create Default Tenant
        plan_free = Plan.objects.get(name='FREE')
        tenant, created = Tenant.objects.get_or_create(
            name='Demo Company',
            defaults={'plan': plan_free, 'subscription_status': 'ACTIVE'}
        )

        # Create System Settings
        SystemSetting.get_settings(tenant)

        # Create Superuser
        if not User.objects.filter(username='admin').exists():
            user = User.objects.create_superuser('admin', 'admin@example.com', 'admin')
            UserProfile.objects.create(user=user, tenant=tenant)
            self.stdout.write(self.style.SUCCESS('Superuser created: admin/admin'))
        else:
            self.stdout.write(self.style.WARNING('Superuser already exists.'))
