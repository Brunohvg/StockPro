"""Etiquetas com código de barras para impressoras Zebra."""
import json
from copy import copy
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from apps.tenants.middleware import admin_required, trial_allows_read

from . import preview, services, zpl
from .forms import LabelSettingsForm
from .layout import build_label, build_test_label, page_width
from .models import PRESETS, LabelSettings

MAX_LABELS = zpl.MAX_LABELS


def _cfg(request):
    return LabelSettings.for_tenant(request.tenant)


@login_required
@require_GET
def index(request):
    tenant = request.tenant
    cfg = _cfg(request)
    initial, source = [], ''
    qs = services.variants_qs(tenant)

    variant_ids = [v for v in request.GET.getlist('variant') if v.isdigit()]
    if variant_ids:
        for v in qs.filter(pk__in=variant_ids):
            initial.append(services.variant_json(v, cfg))
    product_id = request.GET.get('product', '')
    if product_id.isdigit():
        for v in qs.filter(product_id=product_id).order_by('name'):
            initial.append(services.variant_json(v, cfg))
    nfe = None
    nfe_id = request.GET.get('nfe', '')
    if nfe_id:
        from apps.inventory.models import NfeDocument
        try:
            nfe = NfeDocument.objects.filter(tenant=tenant, pk=nfe_id).first()
        except Exception:  # id malformado
            nfe = None
        if nfe:
            for variant, qty in services.nfe_quantities(nfe):
                initial.append(services.variant_json(variant, cfg, qty))
            source = f'NF-e {nfe.number}'

    from apps.inventory.models import NfeDocument
    recent_nfes = (NfeDocument.objects.filter(tenant=tenant, status='IMPORTED')
                   .order_by('-imported_at')[:8])
    return render(request, 'labels/index.html', {
        'cfg': cfg,
        'initial_json': initial,
        'source': source,
        'recent_nfes': recent_nfes,
        'max_labels': MAX_LABELS,
        'page_width_mm': page_width(cfg) / (12 if cfg.dpi >= 300 else 8),
    })


@login_required
@require_GET
def search(request):
    cfg = _cfg(request)
    results = [services.variant_json(v, cfg) for v in services.search_variants(request.tenant, request.GET.get('q'))]
    return JsonResponse({'results': results})


@login_required
@require_GET
def nfe_items(request, pk):
    from apps.inventory.models import NfeDocument
    doc = get_object_or_404(NfeDocument, tenant=request.tenant, pk=pk)
    cfg = _cfg(request)
    items = [services.variant_json(v, cfg, qty) for v, qty in services.nfe_quantities(doc)]
    return JsonResponse({'results': items, 'source': f'NF-e {doc.number}'})


@login_required
@require_POST
def save_text(request, pk):
    """Grava o nome e o código impressos na etiqueta deste produto (vazio = padrão do cadastro)."""
    from .models import VariantLabel
    variant = get_object_or_404(services.variants_qs(request.tenant), pk=pk)
    name = ' '.join((request.POST.get('name') or '').split())
    code = ' '.join((request.POST.get('code') or '').split())
    if len(name) > 80 or len(code) > 30:
        return HttpResponseBadRequest('Nome com até 80 letras e código com até 30.')
    cfg = _cfg(request)
    defaults = {services.default_title(variant).upper(), variant.product.name.upper()}
    if name.upper() in defaults:
        name = ''
    if code == (variant.sku or ''):
        code = ''
    if name or code:
        VariantLabel.objects.update_or_create(
            tenant=request.tenant, variant=variant,
            defaults={'name': name, 'code': code, 'updated_by': request.user})
    else:
        VariantLabel.objects.filter(tenant=request.tenant, variant=variant).delete()
    variant = services.variants_qs(request.tenant).get(pk=pk)
    return JsonResponse({'item': services.variant_json(variant, cfg)})


def _override(cfg, params):
    """Aplica na configuração (sem salvar) os valores do formulário, para a prévia ao vivo."""
    form = LabelSettingsForm(params, instance=copy(cfg))
    if form.is_valid():
        return form.save(commit=False)
    return cfg


@login_required
@require_GET
def preview_svg(request):
    cfg = _cfg(request)
    if request.GET.get('live') == '1':
        cfg = _override(cfg, request.GET)
    store = services.store_name(request.tenant)
    if request.GET.get('test') == '1':
        labels = [build_test_label(cfg)] * int(cfg.columns)
    else:
        ids = [v for v in request.GET.get('v', '').split(',') if v.isdigit()][: int(cfg.columns)]
        variants = {v.pk: v for v in services.variants_qs(request.tenant).filter(pk__in=ids)}
        items = [services.item_from_variant(variants[int(i)], store) for i in ids if int(i) in variants]
        if not items:
            sample = copy(services.SAMPLE_CODE_NAME if cfg.layout == 'code_name' else services.SAMPLE)
            sample.store = store
            items = [sample] * int(cfg.columns)
        labels = [build_label(item, cfg) for item in items]
    svg = preview.render_svg(labels, cfg, css_class='w-full h-auto')
    warnings = sorted({w for lb in labels for w in lb.warnings})
    response = HttpResponse(svg, content_type='image/svg+xml; charset=utf-8')
    response['X-Label-Warnings'] = json.dumps(warnings, ensure_ascii=True)
    response['Cache-Control'] = 'no-store'
    return response


def _parse_quantities(post):
    out = []
    for key, value in post.items():
        if key.startswith('q_') and key[2:].isdigit():
            try:
                qty = int(Decimal(value or '0'))
            except (InvalidOperation, ValueError):
                continue
            if qty > 0:
                out.append((int(key[2:]), qty))
    return out


def _sequence(request, cfg, pairs):
    """Lista [(chave, Label)] na ordem dos itens, repetida pela quantidade."""
    store = services.store_name(request.tenant)
    variants = {v.pk: v for v in services.variants_qs(request.tenant).filter(pk__in=[p for p, _ in pairs])}
    seq, warnings = [], set()
    for pk, qty in pairs:
        variant = variants.get(pk)
        if not variant:
            continue
        label = build_label(services.item_from_variant(variant, store), cfg)
        warnings.update(f'{variant.sku}: {w}' for w in label.warnings)
        seq += [(pk, label)] * qty
    return seq, sorted(warnings)


@login_required
@require_POST
def generate(request):
    """
    Gera a impressão. formato=zpl devolve o ZPL (para a Zebra Browser Print ou download);
    formato=html devolve a página para imprimir pelo navegador (driver da Zebra).
    """
    cfg = _cfg(request)
    fmt = request.POST.get('formato', 'zpl')
    if request.POST.get('teste') == '1':
        test = build_test_label(cfg)
        seq = [('test', test)] * int(cfg.columns)
        warnings = []
    else:
        # A ordem dos campos no POST é a ordem da fila na tela.
        pairs = _parse_quantities(request.POST)
        total = sum(q for _, q in pairs)
        if not pairs:
            return HttpResponseBadRequest('Nenhuma etiqueta na lista.')
        if total > MAX_LABELS:
            return HttpResponseBadRequest(f'Máximo de {MAX_LABELS} etiquetas por impressão. Divida em partes.')
        seq, warnings = _sequence(request, cfg, pairs)
        if not seq:
            return HttpResponseBadRequest('Nenhum produto válido na lista.')

    if fmt == 'html':
        cols = int(cfg.columns)
        rows = [[lb for _, lb in seq[i:i + cols]] for i in range(0, len(seq), cols)]
        pw_mm = page_width(cfg) / (12 if cfg.dpi >= 300 else 8)
        svgs = [preview.render_svg(row, cfg, liner=False, outline=False) for row in rows]
        return render(request, 'labels/print.html', {
            'cfg': cfg, 'svgs': svgs, 'page_width_mm': pw_mm, 'count': len(seq), 'warnings': warnings,
        })

    data = zpl.render_job(seq, cfg)
    response = HttpResponse(data, content_type='text/plain; charset=utf-8')
    response['X-Label-Count'] = str(len(seq))
    response['X-Label-Warnings'] = json.dumps(warnings, ensure_ascii=True)
    if request.POST.get('download') == '1':
        stamp = timezone.localtime().strftime('%Y%m%d-%H%M')
        response['Content-Disposition'] = f'attachment; filename="etiquetas-{stamp}.zpl"'
    return response


@login_required
@admin_required
@trial_allows_read
def settings_view(request):
    cfg = _cfg(request)
    form = LabelSettingsForm(request.POST or None, instance=cfg)
    if request.method == 'POST':
        if form.is_valid():
            form.save()
            messages.success(request, 'Modelo de etiqueta salvo.')
            return redirect('labels:settings')
        messages.error(request, 'Confira os campos destacados.')
    return render(request, 'labels/settings.html', {
        'form': form, 'cfg': cfg,
        'presets': [{'key': k, 'label': lbl, 'w': w, 'h': h, 'cols': c, 'gap': str(g)}
                    for k, lbl, w, h, c, g in PRESETS],
    })
