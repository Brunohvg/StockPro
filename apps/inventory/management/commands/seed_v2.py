"""
Management Command: seed_v2

Cria dados iniciais para a versão 2 do StockPro:
- Localização padrão por tenant
- Motivos de ajuste padrão por tenant

Uso:
    python manage.py seed_v2
    python manage.py seed_v2 --tenant=empresa-teste
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.tenants.models import Tenant


class Command(BaseCommand):
    help = 'Cria dados iniciais para StockPro V2 (Location, AdjustmentReason)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--tenant',
            type=str,
            help='Slug do tenant específico (opcional)',
        )

    def handle(self, *args, **options):
        from apps.inventory.models import AdjustmentReason, Location

        tenant_slug = options.get('tenant')

        if tenant_slug:
            try:
                tenants = [Tenant.objects.get(slug=tenant_slug)]
            except Tenant.DoesNotExist:
                raise CommandError(f'Tenant "{tenant_slug}" não encontrado')
        else:
            tenants = Tenant.objects.filter(is_active=True)

        self.stdout.write(f'Processando {len(tenants)} tenant(s)...\n')

        for tenant in tenants:
            self.stdout.write(f'\n📦 Tenant: {tenant.name}')

            with transaction.atomic():
                # 1. Cria localização padrão
                location, loc_created = Location.objects.get_or_create(
                    tenant=tenant,
                    code='PRINCIPAL',
                    defaults={
                        'name': 'Localização Principal',
                        'location_type': 'STORE',
                        'is_default': True,
                    }
                )

                if loc_created:
                    self.stdout.write(self.style.SUCCESS(f'  ✓ Localização criada: {location.name}'))
                else:
                    self.stdout.write(f'  · Localização já existe: {location.name}')

                # 2. Cria motivos de ajuste
                reasons_created = AdjustmentReason.seed_defaults(tenant)

                if reasons_created:
                    self.stdout.write(self.style.SUCCESS(
                        f'  ✓ {len(reasons_created)} motivos de ajuste criados'
                    ))
                else:
                    self.stdout.write('  · Motivos de ajuste já existem')

        self.stdout.write(self.style.SUCCESS('\n✅ Seed V2 concluído!'))
