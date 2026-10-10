"""Monta o conteúdo das etiquetas a partir do cadastro."""
import math
from decimal import Decimal

from django.db.models import Q

from .barcodes import choose_code
from .layout import LabelItem

SAMPLE = LabelItem(name='Caneta gel Pilot G2 0.7 azul', variant='Azul', price=Decimal('12.90'),
                   sku='CAN-G2-AZ', barcode='7891234567895')


def store_name(tenant):
    from apps.core.models import SystemSetting
    cfg = SystemSetting.objects.filter(tenant=tenant).only('company_name').first()
    name = cfg.company_name if cfg and cfg.company_name and cfg.company_name != 'Minha Empresa' else ''
    return name or (tenant.name if tenant else '')


def variant_text(variant):
    attrs = [a.value for a in variant.attribute_values.all()]
    if attrs:
        return ' / '.join(attrs)
    name = (variant.name or '').strip()
    if name and name != 'Padrão' and name.lower() != variant.product.name.strip().lower():
        return name
    return ''


def variant_barcode(variant):
    if variant.barcode:
        return variant.barcode.strip()
    if variant.product.is_simple and variant.product.barcode:
        return variant.product.barcode.strip()
    return ''


def item_from_variant(variant, store=''):
    return LabelItem(
        name=variant.product.name,
        variant=variant_text(variant),
        price=variant.sale_price if variant.sale_price is not None else variant.product.sale_price,
        sku=variant.sku or '',
        barcode=variant_barcode(variant),
        store=store,
    )


def variants_qs(tenant):
    from apps.products.models import ProductVariant
    return (ProductVariant.objects.filter(tenant=tenant, is_active=True, product__is_active=True)
            .select_related('product').prefetch_related('attribute_values'))


def search_variants(tenant, query, limit=20):
    query = (query or '').strip()
    if len(query) < 2:
        return []
    return list(variants_qs(tenant).filter(
        Q(product__name__icontains=query) | Q(name__icontains=query)
        | Q(sku__icontains=query) | Q(barcode=query) | Q(product__barcode=query)
    ).order_by('product__name', 'name')[:limit])


def variant_json(variant, cfg, qty=1):
    item = item_from_variant(variant)
    code = choose_code(item.barcode, item.sku, cfg.code_source)
    return {
        'id': variant.pk,
        'name': item.name,
        'variant': item.variant,
        'sku': item.sku,
        'barcode': item.barcode,
        'price': f'{item.price:.2f}' if item.price is not None else '',
        'code': code['kind'] if code else '',
        'code_value': code['value'] if code else '',
        'stock': float(variant.current_stock or 0),
        'qty': int(qty),
    }


def nfe_quantities(document):
    """[(variação, quantidade em unidades do estoque)] dos itens vinculados de uma NF-e."""
    out = []
    for item in document.items.select_related('variant', 'variant__product').order_by('item_number'):
        if not item.variant_id or item.decision == 'IGNORE' or not item.variant.is_active:
            continue
        units = Decimal(item.quantity or 0) * Decimal(item.conversion_factor or 1)
        out.append((item.variant, max(1, math.ceil(units))))
    return out
