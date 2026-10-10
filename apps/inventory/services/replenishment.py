"""
Reposição: o que está abaixo do mínimo, quanto vende por dia e quanto comprar.

Venda = saídas (OUT) no período, sem contar arquivamento e estorno de NF-e.
Sugestão = o que cobre o prazo do fornecedor + os dias de cobertura escolhidos,
nunca abaixo do estoque mínimo, menos o que já tem.
"""
import math
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

from django.db.models import F, Q, Sum
from django.utils import timezone

NOT_SALES = ('ARCHIVE', 'NFE_REVERT')
DEFAULT_LEAD_DAYS = 7
WINDOWS = (30, 60, 90)
COVERAGES = (15, 30, 45, 60)


def low_stock_qs(tenant):
    """Variações ativas com mínimo definido e saldo no mínimo ou abaixo."""
    from apps.products.models import ProductVariant
    return ProductVariant.objects.filter(
        tenant=tenant, is_active=True, product__is_active=True,
        minimum_stock__gt=0, current_stock__lte=F('minimum_stock'),
    )


def sales_by_variant(tenant, days, until=None):
    from apps.inventory.models import StockMovement
    until = until or timezone.now()
    rows = (StockMovement.objects
            .filter(tenant=tenant, type='OUT', created_at__gte=until - timedelta(days=days), created_at__lte=until)
            .exclude(source__in=NOT_SALES)
            .values('variant_id').annotate(qty=Sum('quantity')))
    return {r['variant_id']: Decimal(r['qty'] or 0) for r in rows}


@dataclass
class Line:
    variant: object
    stock: Decimal
    minimum: Decimal
    sold: Decimal
    per_day: Decimal
    days_left: int | None
    lead_days: int
    suggested: int
    unit_cost: Decimal | None
    supplier: object = None
    supplier_sku: str = ''
    pack: Decimal = Decimal('1')
    status: str = ''  # zero, below, soon, ok

    @property
    def total_cost(self):
        return (self.unit_cost or Decimal('0')) * self.suggested

    @property
    def status_label(self):
        return {'zero': 'Zerado', 'below': 'Abaixo do mínimo', 'soon': 'Acaba logo', 'ok': 'OK'}[self.status]


@dataclass
class SupplierGroup:
    supplier: object
    lines: list = field(default_factory=list)

    @property
    def total(self):
        return sum((ln.total_cost for ln in self.lines), Decimal('0'))

    @property
    def units(self):
        return sum(ln.suggested for ln in self.lines)

    @property
    def below_minimum_order(self):
        minimum = getattr(self.supplier, 'minimum_order', None) or Decimal('0')
        return bool(minimum) and self.total < minimum

    @property
    def key(self):
        return self.supplier.pk if self.supplier else 0


def _supplier_maps(tenant, variants):
    """Fornecedor e último custo de cada variação (mapa do fornecedor mais recente)."""
    from apps.partners.models import SupplierProductMap
    product_ids = {v.product_id for v in variants}
    maps = (SupplierProductMap.objects
            .filter(tenant=tenant, is_active=True, product_id__in=product_ids)
            .select_related('supplier')
            .order_by(F('last_purchase').desc(nulls_last=True), '-updated_at'))
    by_variant, by_product = {}, {}
    for m in maps:
        if m.variant_id and m.variant_id not in by_variant:
            by_variant[m.variant_id] = m
        if m.product_id not in by_product:
            by_product[m.product_id] = m
    return by_variant, by_product


def build(tenant, window=30, coverage=30, only='need', supplier_id=None, q=''):
    """
    Monta as linhas de reposição.
    only='need': abaixo do mínimo, zerados com venda, ou que acabam antes de chegar
    a próxima compra; only='all': tudo que vendeu no período ou tem mínimo.
    """
    from apps.products.models import ProductVariant
    window = window if window in WINDOWS else 30
    coverage = max(1, min(int(coverage or 30), 180))
    sales = sales_by_variant(tenant, window)

    qs = (ProductVariant.objects
          .filter(tenant=tenant, is_active=True, product__is_active=True)
          .filter(Q(minimum_stock__gt=0) | Q(pk__in=list(sales.keys())))
          .select_related('product', 'product__default_supplier')
          .prefetch_related('attribute_values'))
    if q:
        qs = qs.filter(Q(product__name__icontains=q) | Q(sku__icontains=q) | Q(barcode=q))
    variants = list(qs)
    by_variant, by_product = _supplier_maps(tenant, variants)

    lines = []
    for v in variants:
        stock = Decimal(v.current_stock or 0)
        minimum = Decimal(v.minimum_stock or 0)
        sold = sales.get(v.pk, Decimal('0'))
        per_day = (sold / window) if sold else Decimal('0')
        smap = by_variant.get(v.pk) or by_product.get(v.product_id)
        supplier = v.product.default_supplier or (smap.supplier if smap else None)
        if smap and supplier and smap.supplier_id != supplier.pk:
            smap = None  # mapa de outro fornecedor: não usar código nem custo dele
        lead = (supplier.lead_time_days if supplier and supplier.lead_time_days else DEFAULT_LEAD_DAYS)
        days_left = int(stock / per_day) if per_day > 0 else None
        target = max(per_day * (lead + coverage), minimum)
        suggested = max(0, math.ceil(target - stock))
        pack = Decimal(smap.conversion_factor) if smap and smap.conversion_factor and smap.conversion_factor > 1 else Decimal('1')
        if suggested and pack > 1:
            suggested = int(math.ceil(suggested / pack) * pack)  # caixa fechada
        if stock <= 0 and (sold > 0 or minimum > 0):
            status = 'zero'
        elif minimum > 0 and stock <= minimum:
            status = 'below'
        elif days_left is not None and days_left <= lead:
            status = 'soon'
        else:
            status = 'ok'
        if only == 'need' and (status == 'ok' or suggested == 0):
            continue
        if supplier_id and (not supplier or supplier.pk != supplier_id):
            continue
        # last_cost já é por unidade do estoque (a importação da NF-e divide pelo fator)
        cost = (smap.last_cost if smap and smap.last_cost else None) or v.avg_unit_cost
        lines.append(Line(v, stock, minimum, sold, per_day.quantize(Decimal('0.01')), days_left, lead,
                          suggested, cost, supplier, smap.supplier_sku if smap else '', pack, status))

    order = {'zero': 0, 'below': 1, 'soon': 2, 'ok': 3}
    lines.sort(key=lambda ln: (order[ln.status], ln.days_left if ln.days_left is not None else 10 ** 6,
                               ln.variant.product.name))
    return lines


def group_by_supplier(lines):
    groups = OrderedDict()
    for ln in lines:
        key = ln.supplier.pk if ln.supplier else 0
        groups.setdefault(key, SupplierGroup(ln.supplier)).lines.append(ln)
    # sem fornecedor por último
    return sorted(groups.values(), key=lambda g: (g.supplier is None, -g.total))


def counts(tenant):
    """Resumo para o e-mail e para o menu."""
    low = low_stock_qs(tenant)
    return {'below': low.count(), 'zero': low.filter(current_stock__lte=0).count()}
