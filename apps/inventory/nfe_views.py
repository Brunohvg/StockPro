"""Telas da importação de NF-e de entrada (Beta). Regras em services/nfe.py."""
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render

from apps.products.models import Category
from apps.tenants.middleware import admin_required, trial_allows_read

from .models import Location, NfeDocument, NfeSettings
from .services import nfe as svc


class NfeSettingsForm(forms.ModelForm):
    class Meta:
        model = NfeSettings
        exclude = ['tenant']

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['default_category'].queryset = Category.objects.filter(tenant=tenant).order_by('name')
        self.fields['default_location'].queryset = Location.objects.filter(tenant=tenant, is_active=True)
        for name, f in self.fields.items():
            if isinstance(f.widget, forms.CheckboxInput):
                f.widget.attrs['class'] = 'w-4 h-4 rounded border-slate-300 text-indigo-600'
            else:
                f.widget.attrs['class'] = ('w-full px-3 py-2 bg-slate-50 border border-slate-200 '
                                           'rounded-xl text-sm font-medium')


@login_required
@admin_required
def nfe_list(request):
    docs = NfeDocument.objects.filter(tenant=request.tenant).select_related('created_by')[:100]
    return render(request, 'inventory/nfe/list.html', {'documents': docs})


@login_required
@admin_required
@trial_allows_read
def nfe_upload(request):
    if request.method != 'POST':
        return redirect('inventory:nfe_list')
    files = request.FILES.getlist('files')
    if not files:
        messages.warning(request, "Selecione um ou mais arquivos XML (ou um .zip).")
        return redirect('inventory:nfe_list')
    try:
        payloads = svc.iter_uploaded_xmls(files)
    except svc.NfeError as exc:
        messages.error(request, str(exc))
        return redirect('inventory:nfe_list')
    created = []
    for name, content in payloads:
        if content is None:
            messages.error(request, f"{name}: arquivo inválido ou maior que 5 MB.")
            continue
        try:
            created.append(svc.create_preview(request.tenant, request.user, name, content))
        except svc.NfeError as exc:
            messages.error(request, f"{name}: {exc}")
    if len(created) == 1:
        return redirect('inventory:nfe_detail', pk=created[0].pk)
    if created:
        messages.success(request, f"{len(created)} nota(s) prontas para revisão.")
    return redirect('inventory:nfe_list')


@login_required
@admin_required
def nfe_detail(request, pk):
    doc = get_object_or_404(NfeDocument, pk=pk, tenant=request.tenant)
    cfg = NfeSettings.for_tenant(request.tenant)

    if request.method == 'POST':
        if request.trial_expired:
            return redirect('tenants:billing')
        action = request.POST.get('action', 'save')
        if doc.status != 'PREVIEW':
            messages.error(request, "Esta nota não está mais em revisão.")
            return redirect('inventory:nfe_detail', pk=pk)
        if action == 'discard':
            doc.status = 'DISCARDED'
            doc.save(update_fields=['status'])
            messages.info(request, f"NF-e {doc.number} descartada. Nada entrou no estoque.")
            return redirect('inventory:nfe_list')
        errors = svc.apply_decisions(doc, request.POST)
        for e in errors:
            messages.error(request, e)
        if action == 'import' and not errors:
            try:
                svc.import_document(doc, request.user,
                                    confirm_recipient=request.POST.get('confirm_recipient') == 'on')
            except svc.NfeError as exc:
                for line in str(exc).splitlines():
                    messages.error(request, line)
            except ValueError as exc:
                messages.error(request, f"Não foi possível importar: {exc}")
            else:
                messages.success(request, f"NF-e {doc.number} importada: entradas registradas no estoque.")
        elif not errors:
            messages.success(request, "Revisão salva.")
        return redirect('inventory:nfe_detail', pk=pk)

    items = list(doc.items.select_related('variant__product', 'new_product_category'))
    for item in items:
        item.calc_stock_qty = item.stock_quantity
        item.calc_unit_cost = item.unit_cost(cfg)
        item.calc_cost_total = item.cost_total(cfg)
    return render(request, 'inventory/nfe/detail.html', {
        'doc': doc,
        'items': items,
        'cfg': cfg,
        'categories': Category.objects.filter(tenant=request.tenant).order_by('name'),
        'needs_confirm': any(w.get('confirm') for w in doc.warnings),
        'ready_errors': svc.validate_ready(doc) if doc.status == 'PREVIEW' else [],
    })


@login_required
@admin_required
@trial_allows_read
def nfe_revert(request, pk):
    doc = get_object_or_404(NfeDocument, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        try:
            svc.revert_document(doc, request.user)
            messages.success(request, f"Entrada da NF-e {doc.number} desfeita com saídas de estorno.")
        except svc.NfeError as exc:
            messages.error(request, str(exc))
    return redirect('inventory:nfe_detail', pk=pk)


@login_required
@admin_required
def nfe_xml(request, pk):
    doc = get_object_or_404(NfeDocument, pk=pk, tenant=request.tenant)
    if not doc.xml_file:
        raise Http404
    return FileResponse(doc.xml_file.open('rb'), as_attachment=True, filename=f"NFe{doc.access_key}.xml",
                        content_type='application/xml')


@login_required
@admin_required
@trial_allows_read
def nfe_settings(request):
    cfg = NfeSettings.for_tenant(request.tenant)
    if request.method == 'POST':
        form = NfeSettingsForm(request.POST, instance=cfg, tenant=request.tenant)
        if form.is_valid():
            form.save()
            messages.success(request, "Padrão de importação de NF-e salvo.")
            return redirect('inventory:nfe_list')
    else:
        form = NfeSettingsForm(instance=cfg, tenant=request.tenant)
    return render(request, 'inventory/nfe/settings.html', {'form': form})

