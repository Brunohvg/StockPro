"""Regressão da migração de preço: catálogo, rollback e valores personalizados."""
from decimal import Decimal
from importlib import import_module
from types import SimpleNamespace

import pytest
from django.apps import apps
from django.db import connection

from apps.tenants.models import Plan


@pytest.mark.django_db
def test_enterprise_pricing_migration_preserves_other_plans_and_custom_prices():
    migration = import_module("apps.tenants.migrations.0004_enterprise_price_697")
    editor = SimpleNamespace(connection=connection)
    enterprise = Plan.objects.create(name="EMPRESARIAL", price=247, max_users=999)
    professional = Plan.objects.create(name="PROFISSIONAL", price=97)
    free = Plan.objects.create(name="GRATUITO", price=0)

    migration.update_enterprise_price(apps, editor)
    migration.update_enterprise_price(apps, editor)
    enterprise.refresh_from_db()
    professional.refresh_from_db()
    free.refresh_from_db()
    assert enterprise.price == Decimal("697.00")
    assert enterprise.max_users == 999
    assert professional.price == Decimal("97.00")
    assert free.price == Decimal("0.00")

    migration.revert_enterprise_price(apps, editor)
    enterprise.refresh_from_db()
    assert enterprise.price == Decimal("247.00")

    enterprise.price = Decimal("799.00")
    enterprise.save(update_fields=["price"])
    migration.update_enterprise_price(apps, editor)
    migration.revert_enterprise_price(apps, editor)
    enterprise.refresh_from_db()
    assert enterprise.price == Decimal("799.00")
