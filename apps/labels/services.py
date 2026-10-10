"""Monta o conteúdo das etiquetas a partir do cadastro."""
import math
from decimal import Decimal

from django.db.models import Q

from .barcodes import choose_code
from .layout import LabelItem

SAMPLE = LabelItem(name='Caneta gel Pilot G2 0.7 azul', variant='Azul', price=Decimal('12.90'),
                   sku='CAN-G2-AZ', barcode='7891234567895')
# Exemplo do estilo "código + nome" (o mesmo da etiqueta de atacado que a loja já usa)
SAMPLE_CODE_NAME = LabelItem(name='Aplique flor prensada - PCT 50 UN', price=Decimal('18.90'), sku='APL-FLOR',
                             barcode='7890000139557', code='139557', title='Aplique flor prensada - PCT 50 UN')


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


def label_override(variant):
    """Texto editado da etiqueta (VariantLabel) ou None."""
    from django.core.exceptions import ObjectDoesNotExist
    try:
        return variant.label_text
    except ObjectDoesNotExist:
        return None


def default_title(variant):
    """Nome padrão no estilo "código + nome": produto com a variação."""
    return variant.display_name


def item_from_variant(variant, store=''):
    override = label_override(variant)
    custom_name = (override.name if override else '').strip()
    custom_code = (override.code if override else '').strip()
    return LabelItem(
        name=custom_name or variant.product.name,
        variant=variant_text(variant),
        price=variant.sale_price if variant.sale_price is not None else variant.product.sale_price,
        sku=variant.sku or '',
        barcode=variant_barcode(variant),
        store=store,
        code=custom_code or variant.sku or '',
        title=custom_name or default_title(variant),
    )


def variants_qs(tenant):
    from apps.products.models import ProductVariant
    return (ProductVariant.objects.filter(tenant=tenant, is_active=True, product__is_active=True)
            .select_related('product', 'label_text').prefetch_related('attribute_values'))


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
    override = label_override(variant)
    return {
        'label_name': override.name if override else '',
        'label_code': override.code if override else '',
        'default_name': default_title(variant) if cfg.layout == 'code_name' else variant.product.name,
        'default_code': variant.sku or '',
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
