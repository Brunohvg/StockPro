# apps/tenants/migrations/0002_seed_plans.py
"""
Data migration: cria os 3 planos padrão.
Roda automaticamente com 'manage.py migrate'.
Idempotente — usa update_or_create.
"""
from django.db import migrations


def seed_plans(apps, schema_editor):
    Plan = apps.get_model('tenants', 'Plan')
    plans = [
        {'name': 'GRATUITO',     'display_name': 'Gratuito',      'price': 0,   'max_products': 50,     'max_users': 2,   'has_ai_matching': False, 'has_ai_reconciliation': False, 'features': ''},
        {'name': 'PROFISSIONAL', 'display_name': 'Profissional',  'price': 97,  'max_products': 1000,   'max_users': 10,  'has_ai_matching': True,  'has_ai_reconciliation': False, 'features': 'Importação XML NF-e,Relatório CMV,Suporte prioritário'},
        {'name': 'EMPRESARIAL',  'display_name': 'Empresarial',   'price': 197, 'max_products': 999999, 'max_users': 999, 'has_ai_matching': True,  'has_ai_reconciliation': True,  'features': 'Tudo do Profissional,IA Conciliação automática,Multi-empresa ilimitado,API acesso completo'},
    ]
    for p in plans:
        Plan.objects.update_or_create(name=p['name'], defaults=p)


def remove_plans(apps, schema_editor):
    # Reversível — remove apenas os planos padrão se não tiver tenants vinculados
    Plan = apps.get_model('tenants', 'Plan')
    Plan.objects.filter(
        name__in=['GRATUITO', 'PROFISSIONAL', 'EMPRESARIAL'],
        tenants__isnull=True
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('tenants', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_plans, reverse_code=remove_plans),
    ]
