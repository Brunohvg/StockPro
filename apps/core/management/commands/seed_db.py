# apps/core/management/commands/seed_db.py
import os
import sys
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from apps.accounts.models import MembershipRole, TenantMembership
from apps.core.models import SystemSetting
from apps.tenants.models import Plan, Tenant


class Command(BaseCommand):
    help = 'Cria superuser e tenant de sistema no primeiro deploy.'

    def handle(self, *args, **options):
        User = get_user_model()

        # 1. Garante que os planos existem (idempotente)
        plans_data = [
            {
                'name': 'GRATUITO', 'display_name': 'Gratuito', 'price': 0,
                'max_products': 50, 'max_users': 2,
                'has_ai_matching': False, 'has_ai_reconciliation': False,
                'features': 'Cadastro de até 50 produtos,Controle de estoque básico,Movimentações de entrada e saída,Relatório de estoque simples,Importação CSV básica,1 localização de estoque,Suporte por email',
            },
            {
                'name': 'PROFISSIONAL', 'display_name': 'Profissional', 'price': 97,
                'max_products': 5000, 'max_users': 10,
                'has_ai_matching': True, 'has_ai_reconciliation': False,
                'features': 'Tudo do Gratuito,Até 5.000 produtos,Até 10 usuários,Importação XML NF-e,Importação/Exportação CSV completa,Relatório CMV,Match inteligente via IA,Múltiplas localizações,Fornecedores e parceiros,Suporte prioritário via chat',
            },
            {
                'name': 'EMPRESARIAL', 'display_name': 'Empresarial', 'price': 247,
                'max_products': 999999, 'max_users': 999,
                'has_ai_matching': True, 'has_ai_reconciliation': True,
                'features': 'Tudo do Profissional,Produtos ilimitados,Usuários ilimitados,IA Conciliação automática,Multi-empresa,API acesso completo,Relatórios avançados,Suporte dedicado com SLA',
            },
        ]
        for p_data in plans_data:
            Plan.objects.update_or_create(name=p_data['name'], defaults=p_data)
        self.stdout.write(self.style.SUCCESS('✅ Planos verificados.'))

        # 2. Tenant de sistema para o superuser
        try:
            plan_top = Plan.objects.get(name='EMPRESARIAL')
            tenant, _ = Tenant.objects.get_or_create(
                name='Sistema StockPro',
                defaults={'plan': plan_top, 'subscription_status': 'ACTIVE'}
            )
            SystemSetting.get_settings(tenant)
            self.stdout.write(self.style.SUCCESS('✅ Tenant sistema verificado.'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'❌ Erro ao criar tenant sistema: {e}'))
            return

        # 3. Superuser via variáveis de ambiente
        email = os.environ.get('DJANGO_SUPERUSER_EMAIL', '').strip()
        password = os.environ.get('DJANGO_SUPERUSER_PASSWORD', '').strip()

        if not email or not password:
            self.stdout.write(self.style.WARNING(
                '⚠️  DJANGO_SUPERUSER_EMAIL ou DJANGO_SUPERUSER_PASSWORD não definidos. Superuser não criado.'
            ))
            return

        if User.objects.filter(is_superuser=True).exists():
            self.stdout.write(self.style.WARNING('⚠️  Superuser já existe. Pulando.'))
            return

        try:
            username = email.split('@')[0][:30]
            # Garante username único
            if User.objects.filter(username=username).exists():
                username = f"{username}_su"

            user = User.objects.create_superuser(
                username=username,
                email=email,
                password=password,
            )

            # Vincula ao tenant de sistema como OWNER
            if not TenantMembership.objects.filter(user=user, tenant=tenant).exists():
                TenantMembership.objects.create(
                    user=user,
                    tenant=tenant,
                    role=MembershipRole.OWNER,
                )

            self.stdout.write(self.style.SUCCESS(
                f'✅ Superuser "{email}" criado com sucesso.'
            ))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'❌ Erro ao criar superuser: {e}'))
