"""
Números do negócio num lugar só.

A Visão Geral, a Inteligência (BI) e o resumo semanal por e-mail leem daqui,
para que a mesma pergunta tenha sempre a mesma resposta. Regras:

- Saldo e custo vêm só das variações (o ledger). Os campos antigos do produto
  (Product.current_stock / avg_unit_cost) não entram em conta nenhuma.
- Produto arquivado não conta no estoque.
- Saída usada como proxy de venda = OUT exceto arquivamento e estorno de NF-e.
  Não equivale a uma venda confirmada.
- Valor em estoque = saldo × custo médio. "Na prateleira" = saldo × preço de venda.
- Faturamento do período = unidades vendidas × preço de venda atual (o sistema
  não guarda o preço de cada venda). CMV = custo gravado na saída ou, sem ele,
  o custo médio atual da variação.
"""
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.db.models import F, Q, Sum
from django.utils import timezone

from apps.inventory.services.replenishment import NOT_SALES  # noqa: E402  (mesma regra do Repor)
STALLED_DAYS = 60
ZERO = Decimal('0')

PERIODS = OrderedDict([
    ('7', '7 dias'),
    ('30', '30 dias'),
    ('90', '90 dias'),
    ('mes', 'Este mês'),
])


# ------------------------------------------------------------------ período

@dataclass
class Period:
    key: str
    label: str
    start: object  # date
    end: object    # date (inclusive)
    prev_start: object
    prev_end: object

    @property
    def days(self):
        return (self.end - self.start).days + 1

    def bounds(self, previous=False):
        """Datetimes com fuso (início do primeiro dia, fim do último)."""
        start, end = (self.prev_start, self.prev_end) if previous else (self.start, self.end)
        tz = timezone.get_current_timezone()
        return (timezone.make_aware(datetime.combine(start, time.min), tz),
                timezone.make_aware(datetime.combine(end, time.max), tz))

    def dates(self):
        return [self.start + timedelta(days=i) for i in range(self.days)]


def period(key='30', today=None):
    today = today or timezone.localdate()
    key = key if key in PERIODS else '30'
    if key == 'mes':
        start = today.replace(day=1)
        prev_end = start - timedelta(days=1)
        # mesmo número de dias no mês anterior, para comparar parecido com parecido
        prev_start = prev_end.replace(day=1)
        span = (today - start).days
        prev_end = min(prev_start + timedelta(days=span), prev_end)
        return Period(key, PERIODS[key], start, today, prev_start, prev_end)
    days = int(key)
    start = today - timedelta(days=days - 1)
    prev_end = start - timedelta(days=1)
    return Period(key, PERIODS[key], start, today, prev_end - timedelta(days=days - 1), prev_end)


def change(current, previous):
    """Variação percentual (None quando não há base de comparação)."""
    current, previous = Decimal(current or 0), Decimal(previous or 0)
    if previous == 0:
        return None
    return float((current - previous) / abs(previous) * 100)


# ------------------------------------------------------------------ base

def active_variants(tenant):
    from apps.products.models import ProductVariant
    return ProductVariant.objects.filter(tenant=tenant, is_active=True, product__is_active=True)


def sales_qs(tenant, start=None, end=None):
    from apps.inventory.models import StockMovement
    qs = StockMovement.objects.filter(tenant=tenant, type='OUT').exclude(source__in=NOT_SALES)
    if start is not None:
        qs = qs.filter(created_at__gte=start)
    if end is not None:
        qs = qs.filter(created_at__lte=end)
    return qs


def entries_qs(tenant, start=None, end=None):
    from apps.inventory.models import StockMovement
    qs = StockMovement.objects.filter(tenant=tenant, type='IN').exclude(source__in=NOT_SALES)
    if start is not None:
        qs = qs.filter(created_at__gte=start)
    if end is not None:
        qs = qs.filter(created_at__lte=end)
    return qs


def effective_price(variant):
    if variant.sale_price is not None:
        return variant.sale_price
    return variant.product.sale_price


# ------------------------------------------------------------------ estoque

def stock_snapshot(tenant):
    """Retrato do estoque agora."""
    rows = active_variants(tenant).select_related('product').only(
        'current_stock', 'minimum_stock', 'avg_unit_cost', 'sale_price', 'barcode', 'inventory_status',
        'product__sale_price', 'product__barcode', 'product__product_type')
    out = {'skus': 0, 'with_stock': 0, 'zeroed': 0, 'units': ZERO, 'value': ZERO, 'shelf_value': ZERO,
           'no_price': 0, 'no_barcode': 0, 'no_cost_with_stock': 0, 'divergent': 0}
    for v in rows:
        stock = v.current_stock or ZERO
        out['skus'] += 1
        if stock > 0:
            out['with_stock'] += 1
        else:
            out['zeroed'] += 1
        out['units'] += stock
        out['value'] += stock * (v.avg_unit_cost or ZERO)
        price = effective_price(v)
        if price:
            out['shelf_value'] += stock * price
        else:
            out['no_price'] += 1
        if not (v.barcode or (v.product.product_type == 'SIMPLE' and v.product.barcode)):
            out['no_barcode'] += 1
        if stock > 0 and not v.avg_unit_cost:
            out['no_cost_with_stock'] += 1
        if v.inventory_status == 'DIVERGENT':
            out['divergent'] += 1
    return out


def low_stock_qs(tenant):
    """No mínimo ou abaixo (só quem tem mínimo definido)."""
    return active_variants(tenant).filter(minimum_stock__gt=0, current_stock__lte=F('minimum_stock'))


def category_values(tenant):
    """[{'name', 'value'}] do valor em estoque por categoria, com "Sem categoria"."""
    rows = (active_variants(tenant).filter(current_stock__gt=0)
            .values('product__category__name')
            .annotate(value=Sum(F('current_stock') * F('avg_unit_cost'))))
    out = [{'name': r['product__category__name'] or 'Sem categoria', 'value': r['value'] or ZERO}
           for r in rows]
    out = [r for r in out if r['value'] > 0]
    out.sort(key=lambda r: r['value'], reverse=True)
    return out


def stalled(tenant, days=STALLED_DAYS, now=None, limit=10):
    """Com saldo e sem venda há `days` dias."""
    now = now or timezone.now()
    sold = set(sales_qs(tenant, start=now - timedelta(days=days), end=now)
               .values_list('variant_id', flat=True))
    qs = (active_variants(tenant).filter(current_stock__gt=0).exclude(pk__in=sold)
          .select_related('product').prefetch_related('attribute_values')
          .annotate(value=F('current_stock') * F('avg_unit_cost')))
    items = sorted(qs, key=lambda v: v.value or ZERO, reverse=True)
    return {'count': len(items), 'value': sum((v.value or ZERO for v in items), ZERO), 'items': items[:limit]}


# ------------------------------------------------------------------ vendas

def sales_summary(tenant, start, end):
    """Vendas no intervalo: unidades, faturamento estimado, CMV, margem e por variação."""
    from apps.products.models import ProductVariant
    moves = list(sales_qs(tenant, start, end).values('variant_id', 'quantity', 'unit_cost'))
    ids = {m['variant_id'] for m in moves}
    variants = {v.pk: v for v in ProductVariant.objects.filter(pk__in=ids).select_related('product')
                .prefetch_related('attribute_values')}
    by_variant = {}
    units = revenue = cogs = ZERO
    priced_units = ZERO
    for m in moves:
        v = variants.get(m['variant_id'])
        if v is None:
            continue
        qty = m['quantity'] or ZERO
        cost = m['unit_cost'] if m['unit_cost'] is not None else (v.avg_unit_cost or ZERO)
        price = effective_price(v)
        row = by_variant.setdefault(v.pk, {'variant': v, 'qty': ZERO, 'revenue': ZERO, 'cogs': ZERO,
                                           'has_price': bool(price)})
        row['qty'] += qty
        row['cogs'] += qty * cost
        units += qty
        cogs += qty * cost
        if price:
            row['revenue'] += qty * price
            revenue += qty * price
            priced_units += qty
    # margem só sobre o que tem preço, senão vira margem negativa falsa
    priced_cogs = sum((r['cogs'] for r in by_variant.values() if r['has_price']), ZERO)
    margin = revenue - priced_cogs
    return {
        'units': units, 'revenue': revenue, 'cogs': cogs, 'margin': margin,
        'margin_pct': float(margin / revenue * 100) if revenue else None,
        'unpriced_units': units - priced_units,
        'by_variant': sorted(by_variant.values(), key=lambda r: (r['revenue'], r['qty']), reverse=True),
    }


def abc_by_revenue(by_variant):
    """Curva ABC pelo faturamento: A = 80% da receita, B = próximos 15%, C = últimos 5%."""
    rows = [r for r in by_variant if r['revenue'] > 0]
    rows.sort(key=lambda r: r['revenue'], reverse=True)
    total = sum((r['revenue'] for r in rows), ZERO)
    classes = {'A': [], 'B': [], 'C': []}
    acc = ZERO
    for r in rows:
        share_before = acc / total * 100 if total else 0
        acc += r['revenue']
        grade = 'A' if share_before < 80 else ('B' if share_before < 95 else 'C')
        classes[grade].append(r)
    out = {}
    for grade, items in classes.items():
        value = sum((r['revenue'] for r in items), ZERO)
        out[grade] = {'count': len(items), 'revenue': value,
                      'pct': float(value / total * 100) if total else 0.0, 'items': items}
    out['total'] = total
    return out


def daily_series(tenant, per):
    """Entradas e vendas por dia, com todos os dias do período (zerados inclusive)."""
    from django.db.models.functions import TruncDate
    start, end = per.bounds()
    tz = timezone.get_current_timezone()

    def by_day(qs):
        rows = qs.annotate(day=TruncDate('created_at', tzinfo=tz)).values('day').annotate(q=Sum('quantity'))
        return {r['day']: float(r['q'] or 0) for r in rows}

    ins = by_day(entries_qs(tenant, start, end))
    outs = by_day(sales_qs(tenant, start, end))
    return [{'date': d.isoformat(), 'label': d.strftime('%d/%m'), 'in': ins.get(d, 0.0), 'out': outs.get(d, 0.0)}
            for d in per.dates()]


def has_history(tenant, days=14, now=None):
    """A IA só entra com histórico: vendas registradas há pelo menos `days` dias."""
    now = now or timezone.now()
    return sales_qs(tenant, end=now - timedelta(days=days)).exists()


def units_in(tenant, start, end):
    return entries_qs(tenant, start, end).aggregate(t=Sum('quantity'))['t'] or ZERO


def units_out(tenant, start, end):
    return sales_qs(tenant, start, end).aggregate(t=Sum('quantity'))['t'] or ZERO


# ------------------------------------------------------------------ telas

def today_numbers(tenant, now=None):
    """Saídas e entradas de hoje e de ontem (para o "desde ontem")."""
    from apps.products.models import ProductVariant
    now = now or timezone.now()
    today = timezone.localtime(now).date()
    tz = timezone.get_current_timezone()

    def day_bounds(d):
        return (timezone.make_aware(datetime.combine(d, time.min), tz),
                timezone.make_aware(datetime.combine(d, time.max), tz))

    t0, t1 = day_bounds(today)
    y0, y1 = day_bounds(today - timedelta(days=1))
    out_today = list(sales_qs(tenant, t0, t1).values('variant_id', 'quantity'))
    prices = {v.pk: effective_price(v) for v in ProductVariant.objects.filter(
        pk__in={m['variant_id'] for m in out_today}).select_related('product')}
    out_value = sum(((m['quantity'] or ZERO) * (prices.get(m['variant_id']) or ZERO) for m in out_today), ZERO)
    return {
        'out_units': sum((m['quantity'] or ZERO for m in out_today), ZERO),
        'out_value': out_value,
        'out_yesterday': units_out(tenant, y0, y1),
        'in_units': units_in(tenant, t0, t1),
        'in_yesterday': units_in(tenant, y0, y1),
    }


def attention(tenant, snapshot=None):
    """
    Quadro "Precisa de atenção": cada linha com a contagem e para onde ir.
    Só entra o que tem contagem > 0.
    """
    from django.urls import reverse

    from apps.core.models import SystemSetting
    from apps.inventory.models import NfeDocument
    from apps.inventory.services.expiry import expiring_lots

    snapshot = snapshot or stock_snapshot(tenant)
    now = timezone.now()
    sold_30 = set(sales_qs(tenant, now - timedelta(days=30), now).values_list('variant_id', flat=True))
    # mesma regra do Repor: zerado que vendeu nos últimos 30 dias ou que tem estoque mínimo
    zeroed = active_variants(tenant).filter(current_stock__lte=0).filter(
        Q(pk__in=sold_30) | Q(minimum_stock__gt=0)).count()
    below = low_stock_qs(tenant).filter(current_stock__gt=0).count()
    settings_obj = SystemSetting.objects.filter(tenant=tenant).first()
    window = settings_obj.expiry_alert_days if settings_obj else 30
    expired, soon = expiring_lots(tenant, window)
    nfe_review = NfeDocument.objects.filter(tenant=tenant, status='PREVIEW').count()

    replenish = reverse('inventory:replenish')
    catalog = reverse('products:product_list')
    rows = [
        ('zeroed', zeroed, 'zerado(s) para repor', 'Acabaram e vendem ou têm estoque mínimo.',
         'Repor', replenish, 'danger'),
        ('below', below, 'abaixo do mínimo', 'Ainda têm saldo, mas já chegaram no mínimo.',
         'Repor', replenish, 'warning'),
        ('expired', len(expired), 'lote(s) vencido(s)', 'Com saldo e validade passada.',
         'Ver lotes', '#validade', 'danger'),
        ('expiring', len(soon), f'lote(s) vencendo em {window} dias', 'Priorize a venda ou a troca.',
         'Ver lotes', '#validade', 'warning'),
        ('nfe_review', nfe_review, 'NF-e esperando revisão', 'Notas enviadas que ainda não deram entrada.',
         'Revisar', reverse('inventory:nfe_list'), 'warning'),
        ('no_price', snapshot['no_price'], 'sem preço de venda', 'Sem preço não há margem nem etiqueta com preço.',
         'Ver no catálogo', f'{catalog}?falta=preco', 'info'),
        ('no_barcode', snapshot['no_barcode'], 'sem código de barras', 'A etiqueta sai com o SKU em Code 128.',
         'Ver no catálogo', f'{catalog}?falta=codigo', 'info'),
        ('divergent', snapshot['divergent'], 'com saldo divergente', 'O saldo não bate com o histórico.',
         'Ver no catálogo', f'{catalog}?stock=divergent', 'danger'),
    ]
    return [{'key': k, 'count': c, 'title': t, 'help': h, 'action': a, 'url': u, 'tone': tone}
            for k, c, t, h, a, u, tone in rows if c]


def onboarding(tenant):
    """Primeiros passos de uma empresa nova; cada um é marcado sozinho quando acontece."""
    from django.urls import reverse

    from apps.accounts.models import TenantMembership
    from apps.inventory.models import ImportBatch, NfeDocument
    from apps.labels.models import LabelSettings
    from apps.products.models import Product

    has_products = Product.objects.filter(tenant=tenant).exists()
    steps = [
        ('Cadastrar ou importar os produtos', 'Planilha no modelo do sistema ou um a um.',
         has_products or ImportBatch.objects.filter(tenant=tenant, status='COMPLETED').exists(),
         reverse('inventory:import_list')),
        ('Dar entrada na primeira NF-e', 'Envie o XML: o sistema cria os produtos e soma o estoque.',
         NfeDocument.objects.filter(tenant=tenant, status='IMPORTED').exists(), reverse('inventory:nfe_list')),
        ('Escolher o modelo de etiqueta', 'Tamanho do rolo e o que vai impresso.',
         LabelSettings.objects.filter(tenant=tenant).exists(), reverse('labels:settings')),
        ('Definir o estoque mínimo', 'É ele que liga os avisos e a tela Repor.',
         active_variants(tenant).filter(minimum_stock__gt=0).exists(), reverse('products:product_list')),
        ('Convidar a equipe', 'Cada pessoa com o seu acesso.',
         TenantMembership.objects.filter(tenant=tenant, is_active=True).count() > 1,
         reverse('accounts:invite_user')),
    ]
    items = [{'title': t, 'help': h, 'done': bool(d), 'url': u} for t, h, d, u in steps]
    return {'steps': items, 'done': sum(1 for s in items if s['done']), 'total': len(items)}


def overview(tenant, now=None):
    """Tudo o que a Visão Geral mostra."""
    snap = stock_snapshot(tenant)
    return {
        'stock': snap,
        'today': today_numbers(tenant, now),
        'attention': attention(tenant, snap),
        'low_count': low_stock_qs(tenant).count(),
    }


def intelligence(tenant, per):
    """Tudo o que a Inteligência mostra para o período escolhido."""
    start, end = per.bounds()
    p0, p1 = per.bounds(previous=True)
    snap = stock_snapshot(tenant)
    cur = sales_summary(tenant, start, end)
    prev = sales_summary(tenant, p0, p1)
    entries = units_in(tenant, start, end)
    per_day_cogs = cur['cogs'] / per.days if per.days else ZERO
    coverage = int(snap['value'] / per_day_cogs) if per_day_cogs > 0 else None
    stall = stalled(tenant)
    abc = abc_by_revenue(cur['by_variant'])
    from apps.inventory.services import replenishment as rep
    ending = [line for line in rep.build(tenant, window=30, coverage=30, only='need')][:5]
    return {
        'period': per,
        'stock': snap,
        'sales': cur,
        'prev': prev,
        'entries': entries,
        'entries_prev': units_in(tenant, p0, p1),
        'changes': {
            'units': change(cur['units'], prev['units']),
            'revenue': change(cur['revenue'], prev['revenue']),
            'cogs': change(cur['cogs'], prev['cogs']),
            'margin': change(cur['margin'], prev['margin']),
        },
        'coverage_days': coverage,
        'stalled': stall,
        'abc': abc,
        'top': cur['by_variant'][:10],
        'categories': category_values(tenant),
        'series': daily_series(tenant, per),
        'ending': ending,
        'low_count': low_stock_qs(tenant).count(),
    }


def insights(data):
    """Frases curtas a partir dos números reais (sem se contradizerem)."""
    out = []
    snap, sales, stall = data['stock'], data['sales'], data['stalled']
    per = data['period']
    if not snap['skus']:
        return [{'tone': 'info', 'title': 'Cadastre os produtos',
                 'text': 'Sem produtos ativos ainda: importe a planilha ou dê entrada numa NF-e.'}]
    if sales['units'] == 0:
        out.append({'tone': 'info', 'title': 'Nenhuma venda no período',
                    'text': f'Nenhuma saída de venda nos últimos {per.days} dias. '
                            'Se as vendas são lançadas por outro sistema, registre as saídas para ver giro e margem.'})
    else:
        ch = data['changes']['units']
        prev_units = data['prev']['units']
        text = f'{_q(sales["units"])} unidades contra {_q(prev_units)} no período anterior.'
        if ch is not None and (prev_units < 10 or abs(ch) >= 200):
            # base pequena: percentual não diz nada
            word = 'bem acima' if ch > 0 else 'bem abaixo'
            out.append({'tone': 'success' if ch > 0 else 'warning',
                        'title': f'Vendas {word} do período anterior', 'text': text})
        elif ch is not None and abs(ch) >= 10:
            word = 'subiram' if ch > 0 else 'caíram'
            out.append({'tone': 'success' if ch > 0 else 'warning', 'title': f'Vendas {word} {abs(ch):.0f}%',
                        'text': text})
        if sales['margin_pct'] is not None and sales['margin_pct'] < 25:
            out.append({'tone': 'warning', 'title': f'Margem de {sales["margin_pct"]:.0f}%',
                        'text': 'Abaixo de 25%. Confira os preços em CMV e margem.'})
    if data['low_count']:
        out.append({'tone': 'warning', 'title': f'{data["low_count"]} no mínimo',
                    'text': 'A tela Repor já traz a quantidade sugerida e o pedido por fornecedor.'})
    if stall['count'] and snap['value'] > 0:
        share = float(stall['value'] / snap['value'] * 100)
        if share >= 20:
            out.append({'tone': 'warning', 'title': f'{share:.0f}% do estoque parado',
                        'text': f'{stall["count"]} itens sem venda há {STALLED_DAYS}+ dias. '
                                'Promoção ou devolução ao fornecedor liberam caixa.'})
    if data['coverage_days'] is not None and data['coverage_days'] > 180:
        out.append({'tone': 'info', 'title': f'Estoque para {data["coverage_days"]} dias',
                    'text': 'No ritmo de venda do período, o estoque dura mais de 6 meses.'})
    if snap['no_price']:
        out.append({'tone': 'info', 'title': f'{snap["no_price"]} sem preço de venda',
                    'text': 'Sem preço, a venda não entra no faturamento nem na margem.'})
    return out[:4]


def _q(value):
    value = Decimal(value or 0)
    if value == value.to_integral_value():
        return f'{int(value):,}'.replace(',', '.')
    return f'{value:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')
