"""
Migration: Insere planos padrão do StockPro.
Roda automaticamente no deploy. Seguro para re-executar (get_or_create).
"""
from django.db import migrations


def seed_plans(apps, schema_editor):
    Plan = apps.get_model('tenants', 'Plan')

    plans = [
        {
            'name': 'GRATUITO',
            'display_name': 'Gratuito',
            'price': 0,
            'max_products': 50,
            'max_users': 2,
            'has_ai_matching': False,
            'has_ai_reconciliation': False,
            'features': 'Até 50 produtos,2 usuários,Movimentações ilimitadas,Importação CSV,Relatórios básicos,Suporte por e-mail',
        },
        {
            'name': 'PROFISSIONAL',
            'display_name': 'Profissional',
            'price': 97,
            'max_products': 1000,
            'max_users': 10,
            'has_ai_matching': True,
            'has_ai_reconciliation': False,
            'features': 'Até 1.000 produtos,10 usuários,Movimentações ilimitadas,Importação CSV e XML (NF-e),IA para match de produtos,Relatórios avançados + BI,App mobile,Backup diário automático,Suporte prioritário',
        },
        {
            'name': 'EMPRESARIAL',
            'display_name': 'Empresarial',
            'price': 197,
            'max_products': 999999,
            'max_users': 999,
            'has_ai_matching': True,
            'has_ai_reconciliation': True,
            'features': 'Produtos ilimitados,Usuários ilimitados,Multi-empresa (tenants),Movimentações ilimitadas,Importação CSV e XML (NF-e),IA completa (match + conciliação automática),Relatórios avançados + BI,App mobile,Backup diário automático,API para integração,Suporte dedicado',
        },
    ]

    for data in plans:
        Plan.objects.update_or_create(
            name=data['name'],
            defaults=data
        )


def remove_plans(apps, schema_editor):
    Plan = apps.get_model('tenants', 'Plan')
    Plan.objects.filter(name__in=['GRATUITO', 'PROFISSIONAL', 'EMPRESARIAL']).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('tenants', '0003_alter_plan_name'),
    ]

    operations = [
        migrations.RunPython(seed_plans, reverse_code=remove_plans),
    ]
