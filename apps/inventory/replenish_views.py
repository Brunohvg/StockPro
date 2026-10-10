"""Tela Repor: o que comprar, de quem e quanto (patch 9)."""
import csv
import re
from decimal import Decimal, InvalidOperation
from urllib.parse import quote

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import render
from django.utils import timezone
from django.utils.text import slugify

from apps.tenants.middleware import admin_required

from .services import replenishment as rep


def _int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@login_required
@admin_required
def replenish(request):
    tenant = request.tenant
    window = _int(request.GET.get('janela'), 30)
    coverage = _int(request.GET.get('cobertura'), 30)
    only = 'all' if request.GET.get('mostrar') == 'todos' else 'need'
    supplier_id = _int(request.GET.get('fornecedor'), 0) or None
    q = (request.GET.get('q') or '').strip()[:80]

    lines = rep.build(tenant, window=window, coverage=coverage, only=only, supplier_id=supplier_id, q=q)
    groups = rep.group_by_supplier([ln for ln in lines if ln.suggested > 0])
    from apps.partners.models import Supplier
    suppliers = Supplier.objects.filter(tenant=tenant, is_active=True).order_by('trade_name', 'company_name')
    return render(request, 'inventory/replenish/list.html', {
        'lines': lines,
        'groups': groups,
        'window': window if window in rep.WINDOWS else 30,
        'coverage': coverage,
        'windows': rep.WINDOWS,
        'coverages': rep.COVERAGES,
        'only': only,
        'supplier_id': supplier_id,
        'suppliers': suppliers,
        'q': q,
        'kpi': {
            'zero': sum(1 for ln in lines if ln.status == 'zero'),
            'below': sum(1 for ln in lines if ln.status == 'below'),
            'soon': sum(1 for ln in lines if ln.days_left is not None and ln.days_left <= ln.lead_days),
            'total': sum((g.total for g in groups), Decimal('0')),
        },
    })


def _whatsapp_number(phone):
    digits = re.sub(r'\D', '', phone or '')
    if len(digits) in (10, 11):
        digits = '55' + digits
    return digits if len(digits) >= 12 else ''


def _brl(value):
    q = Decimal(value or 0).quantize(Decimal('0.01'))
    inteiro, cent = f'{q:.2f}'.split('.')
    return f"R$ {int(inteiro):,}".replace(',', '.') + f',{cent}'


def _csv_safe(value):
    """Neutralize spreadsheet formulas in downloaded supplier orders."""
    value = str(value if value is not None else '')
    return "'" + value if value.lstrip().startswith(('=', '+', '-', '@', '\t', '\r')) else value


def _qty(value):
    value = Decimal(value)
    return f'{value.normalize():f}' if value == value.to_integral() else f'{value:.2f}'.replace('.', ',')


@login_required
@admin_required
def purchase_order(request):
    """Pedido ao fornecedor a partir das quantidades escolhidas na tela Repor. Não grava nada."""
    tenant = request.tenant
    from apps.core.models import SystemSetting
    from apps.partners.models import Supplier
    from apps.products.models import ProductVariant

    supplier = None
    supplier_id = _int(request.GET.get('fornecedor'), 0)
    if supplier_id:
        supplier = Supplier.objects.filter(tenant=tenant, pk=supplier_id).first()

    wanted = {}
    for key, value in request.GET.items():
        if key.startswith('qty_') and key[4:].isdigit():
            try:
                qty = Decimal(value.replace(',', '.'))
            except (InvalidOperation, ValueError):
                return HttpResponseBadRequest('Quantidade inválida.')
            if not qty.is_finite() or qty <= 0 or qty > 100000 or qty.as_tuple().exponent < -3:
                return HttpResponseBadRequest('Quantidade fora do intervalo permitido.')
            wanted[int(key[4:])] = qty
            if len(wanted) > 200:
                return HttpResponseBadRequest('Máximo de 200 produtos por pedido.')
    variants = {v.pk: v for v in ProductVariant.objects.filter(tenant=tenant, pk__in=wanted.keys())
                .select_related('product').prefetch_related('attribute_values')}

    # Código e custo do fornecedor, se houver
    lines_info = {ln.variant.pk: ln for ln in rep.build(tenant, only='all') if ln.variant.pk in variants}
    rows = []
    for pk, qty in wanted.items():
        v = variants.get(pk)
        if not v:
            continue
        info = lines_info.get(pk)
        if supplier and (not info or not info.supplier or info.supplier.pk != supplier.pk):
            return HttpResponseBadRequest('Produto não pertence ao fornecedor escolhido.')
        same_supplier = info and supplier and info.supplier and info.supplier.pk == supplier.pk
        cost = (info.unit_cost if info else None) or v.avg_unit_cost or Decimal('0')
        rows.append({
            'variant': v, 'qty': qty, 'uom': v.product.uom or 'UN',
            'supplier_sku': info.supplier_sku if same_supplier else '',
            'pack': info.pack if info else Decimal('1'),
            'unit_cost': cost, 'total': cost * qty,
        })
    rows.sort(key=lambda r: r['variant'].product.name)
    total = sum((r['total'] for r in rows), Decimal('0'))
    store = SystemSetting.get_settings(tenant)
    store_name = store.company_name if store and store.company_name != 'Minha Empresa' else tenant.name
    today = timezone.localdate()

    if request.GET.get('formato') == 'csv':
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        name = slugify(supplier.trade_name or supplier.company_name) if supplier else 'sem-fornecedor'
        response['Content-Disposition'] = f'attachment; filename="pedido-{name}-{today:%Y%m%d}.csv"'
        response.write('﻿')
        w = csv.writer(response, delimiter=';')
        w.writerow(['Código do fornecedor', 'SKU', 'EAN', 'Produto', 'Quantidade', 'Unidade', 'Custo unitário', 'Total'])
        for r in rows:
            v = r['variant']
            w.writerow([_csv_safe(x) for x in [r['supplier_sku'], v.sku, v.barcode or '', v.display_name, _qty(r['qty']), r['uom'],
                        f"{r['unit_cost']:.2f}".replace('.', ','), f"{r['total']:.2f}".replace('.', ',')]])
        return response

    greet = (supplier.contact_name.split()[0] if supplier and supplier.contact_name else '')
    text = [f"Olá{', ' + greet if greet else ''}! Segue o pedido da {store_name} ({today:%d/%m/%Y}):", '']
    for r in rows:
        code = f" (cód. {r['supplier_sku']})" if r['supplier_sku'] else (f" (EAN {r['variant'].barcode})" if r['variant'].barcode else '')
        text.append(f"• {_qty(r['qty'])} {r['uom'].lower()} - {r['variant'].display_name}{code}")
    text += ['', f'Total estimado: {_brl(total)}', 'Pode confirmar preço e prazo de entrega? Obrigado!']
    message = '\n'.join(text)
    phone = _whatsapp_number(supplier.phone if supplier else '')
    whatsapp = f"https://wa.me/{phone}?text={quote(message)}" if phone else f"https://wa.me/?text={quote(message)}"

    minimum = (supplier.minimum_order if supplier and supplier.minimum_order else Decimal('0'))
    return render(request, 'inventory/replenish/order.html', {
        'supplier': supplier, 'rows': rows, 'total': total, 'store_name': store_name, 'today': today,
        'message': message, 'whatsapp': whatsapp, 'has_phone': bool(phone),
        'minimum': minimum, 'below_minimum': bool(minimum) and total < minimum,
        'missing': max(Decimal('0'), minimum - total),
        'csv_query': request.GET.urlencode() + '&formato=csv',
    })
