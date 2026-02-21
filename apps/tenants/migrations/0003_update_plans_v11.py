# apps/tenants/migrations/0003_update_plans_v11.py
"""
Data migration: atualiza planos com precificação melhorada e features detalhadas.
Reflete o valor real do sistema após as melhorias V10/V11.
Idempotente — usa update_or_create.
"""
from django.db import migrations


def update_plans(apps, schema_editor):
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
            'features': (
                'Cadastro de até 50 produtos,'
                'Controle de estoque básico,'
                'Movimentações de entrada e saída,'
                'Relatório de estoque simples,'
                'Importação CSV básica,'
                '1 localização de estoque,'
                'Suporte por email'
            ),
        },
        {
            'name': 'PROFISSIONAL',
            'display_name': 'Profissional',
            'price': 97,
            'max_products': 5000,
            'max_users': 10,
            'has_ai_matching': True,
            'has_ai_reconciliation': False,
            'features': (
                'Tudo do Gratuito,'
                'Até 5.000 produtos,'
                'Até 10 usuários,'
                'Importação XML NF-e,'
                'Importação/Exportação CSV completa,'
                'Relatório CMV (Custo de Mercadoria Vendida),'
                'Match inteligente de produtos via IA,'
                'Múltiplas localizações de estoque,'
                'Fornecedores e parceiros,'
                'Suporte prioritário via chat'
            ),
        },
        {
            'name': 'EMPRESARIAL',
            'display_name': 'Empresarial',
            'price': 247,
            'max_products': 999999,
            'max_users': 999,
            'has_ai_matching': True,
            'has_ai_reconciliation': True,
            'features': (
                'Tudo do Profissional,'
                'Produtos ilimitados,'
                'Usuários ilimitados,'
                'IA Conciliação automática de estoque,'
                'Multi-empresa (switch entre CNPJs),'
                'API acesso completo,'
                'Relatórios avançados com exportação,'
                'Suporte dedicado com SLA'
            ),
        },
    ]
    for p in plans:
        Plan.objects.update_or_create(name=p['name'], defaults=p)


def revert_plans(apps, schema_editor):
    """Reverte para os valores anteriores"""
    Plan = apps.get_model('tenants', 'Plan')
    old_plans = [
        {'name': 'GRATUITO',     'display_name': 'Gratuito',      'price': 0,   'max_products': 50,     'max_users': 2,   'has_ai_matching': False, 'has_ai_reconciliation': False, 'features': ''},
        {'name': 'PROFISSIONAL', 'display_name': 'Profissional',  'price': 97,  'max_products': 1000,   'max_users': 10,  'has_ai_matching': True,  'has_ai_reconciliation': False, 'features': 'Importação XML NF-e,Relatório CMV,Suporte prioritário'},
        {'name': 'EMPRESARIAL',  'display_name': 'Empresarial',   'price': 197, 'max_products': 999999, 'max_users': 999, 'has_ai_matching': True,  'has_ai_reconciliation': True,  'features': 'Tudo do Profissional,IA Conciliação automática,Multi-empresa ilimitado,API acesso completo'},
    ]
    for p in old_plans:
        Plan.objects.update_or_create(name=p['name'], defaults=p)


class Migration(migrations.Migration):

    dependencies = [
        ('tenants', '0002_seed_plans'),
    ]

    operations = [
        migrations.RunPython(update_plans, reverse_code=revert_plans),
    ]
