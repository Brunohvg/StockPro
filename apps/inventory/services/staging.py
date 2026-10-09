"""
Curadoria de itens em staging (ImportItem), vindos da API com ?staged=true.

Aprovar cria o produto SIMPLE (ou vincula a um existente pelo SKU) e, se o
item tiver quantidade, registra a entrada pelo StockService.
"""
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.services import StockService
from apps.products.models import Product, ProductType, ProductVariant


class StagingError(ValueError):
    pass


@transaction.atomic
def approve_item(item, user):
    item = type(item).objects.select_for_update().get(pk=item.pk)
    if item.status != 'PENDING':
        raise StagingError("Este item já foi processado.")

    from apps.tenants.models import Tenant
    tenant = Tenant.objects.select_for_update().get(pk=item.tenant_id)
    try:
        qty = Decimal(str(item.quantity))
        cost = Decimal(str(item.unit_cost))
    except (InvalidOperation, ValueError, TypeError):
        raise StagingError("Quantidade ou custo inválido.")
    if not qty.is_finite() or qty < 0 or not cost.is_finite() or cost < 0:
        raise StagingError("Quantidade e custo devem ser finitos e não negativos.")
    if not isinstance(item.raw_data, dict):
        raise StagingError("Dados do item inválidos.")
    sku = (item.supplier_sku or '').strip()
    if not sku or sku == 'N/A':
        sku = None

    variant = ProductVariant.objects.filter(tenant=tenant, sku__iexact=sku).first() if sku else None
    if not variant and sku:
        existing = Product.objects.filter(tenant=tenant, sku__iexact=sku).first()
        if existing:
            if existing.is_variable:
                raise StagingError(f"SKU '{sku}' pertence a um produto variável; vincule a uma variação.")
            variant = existing.variants.first()
    if variant:
        product = variant.product
    else:
        if tenant.products_limit_reached:
            raise StagingError("Limite de produtos do plano atingido.")
        raw = item.raw_data or {}
        product = Product(
            tenant=tenant,
            sku=sku,
            name=(item.description or 'Produto sem nome')[:255],
            product_type=ProductType.SIMPLE,
            barcode=item.ean or None,
            description=raw.get('description') or '',
        )
        try:
            with transaction.atomic():
                product.save()
        except (ValidationError, IntegrityError) as exc:
            raise StagingError("Não foi possível criar o produto. Verifique o SKU e os dados.") from exc
        variant = product.variants.first()

    if qty > 0:
        try:
            StockService.create_movement(
                tenant=tenant,
                user=user,
                movement_type='IN',
                quantity=qty,
                variant=variant,
                unit_cost=item.unit_cost or None,
                reason=f"Aprovação de item em staging ({item.source})",
                source='API',
            )
        except (ValueError, ValidationError, IntegrityError) as exc:
            raise StagingError("Não foi possível registrar a entrada: " + str(exc)) from exc

    item.status = 'DONE'
    item.matched_product = product
    item.matched_variant = variant
    item.processed_at = timezone.now()
    item.save(update_fields=['status', 'matched_product', 'matched_variant', 'processed_at'])
    return product


@transaction.atomic
def reject_item(item):
    item = type(item).objects.select_for_update().get(pk=item.pk)
    if item.status != 'PENDING':
        raise StagingError("Este item já foi processado.")
    item.status = 'REJECTED'
    item.processed_at = timezone.now()
    item.save(update_fields=['status', 'processed_at'])
    return item
