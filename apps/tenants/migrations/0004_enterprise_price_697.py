"""Atualiza o preço padrão Empresarial sem sobrescrever preços personalizados."""
from decimal import Decimal

from django.db import migrations


def update_enterprise_price(apps, schema_editor):
    Plan = apps.get_model("tenants", "Plan")
    Plan.objects.using(schema_editor.connection.alias).filter(
        name="EMPRESARIAL", price=Decimal("247.00")
    ).update(price=Decimal("697.00"))


def revert_enterprise_price(apps, schema_editor):
    Plan = apps.get_model("tenants", "Plan")
    Plan.objects.using(schema_editor.connection.alias).filter(
        name="EMPRESARIAL", price=Decimal("697.00")
    ).update(price=Decimal("247.00"))


class Migration(migrations.Migration):
    dependencies = [("tenants", "0003_update_plans_v11")]
    operations = [
        migrations.RunPython(update_enterprise_price, revert_enterprise_price),
    ]
