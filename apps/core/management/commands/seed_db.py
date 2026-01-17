from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from apps.tenants.models import Tenant, Plan
from apps.accounts.models import TenantMembership, MembershipRole
from apps.core.models import SystemSetting
from decouple import config

class Command(BaseCommand):
    help = 'Inicializa Planos, Tenant do Sistema e Superusuário'

    def handle(self, *args, **options):
        self.stdout.write('🔄 Iniciando seed_db...')

        # 1. Criar Planos
        plans = [
            {'name': 'GRATUITO', 'display_name': 'Plano Gratuito', 'price': 0, 'max_products': 50, 'max_users': 2},
            {'name': 'BASIC', 'display_name': 'Plano Basic', 'price': 49.90, 'max_products': 500, 'max_users': 5},
            {'name': 'PROFISSIONAL', 'display_name': 'Plano Profissional', 'price': 97.00, 'max_products': 2000, 'max_users': 15},
            {'name': 'PREMIUM', 'display_name': 'Plano Premium', 'price': 197.00, 'max_products': 10000, 'max_users': 50}
        ]

        for p in plans:
            Plan.objects.get_or_create(name=p['name'], defaults=p)

        # 2. Criar Tenant do Admin
        plan_premium = Plan.objects.get(name='PREMIUM')
        tenant, _ = Tenant.objects.get_or_create(
            name='Sistema Gestor',
            defaults={'plan': plan_premium, 'subscription_status': 'ACTIVE'}
        )
        SystemSetting.get_settings(tenant)

        # 3. Criar Superusuário (Lendo do .env)
        User = get_user_model()
        u = config('DJANGO_SUPERUSER_USERNAME', default='admin')
        e = config('DJANGO_SUPERUSER_EMAIL', default='admin@example.com')
        p = config('DJANGO_SUPERUSER_PASSWORD', default='admin123')

        if not User.objects.filter(username=u).exists():
            user = User.objects.create_superuser(u, e, p)
            TenantMembership.objects.create(
                user=user, tenant=tenant, role=MembershipRole.OWNER
            )
            self.stdout.write(self.style.SUCCESS(f'✅ Superuser "{u}" criado com sucesso!'))
        else:
            self.stdout.write(self.style.WARNING(f'ℹ️ Superuser "{u}" já existe.'))
