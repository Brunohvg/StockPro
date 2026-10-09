"""
Central da plataforma (/admin-panel/): só superusuário.

Regras e indicadores ficam em platform.py; aqui só HTTP e telas.
Toda ação é POST com CSRF, pede confirmação na tela e grava TenantEvent.
"""
import csv
from datetime import date
from functools import wraps

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import platform
from .models import Plan, Tenant, TenantEvent


def superuser_required(view):
    @login_required
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_superuser:
            messages.error(request, "Acesso restrito a administradores da plataforma.")
            return redirect('reports:dashboard')
        return view(request, *args, **kwargs)
    return wrapper


# ─── Visão geral + lista ─────────────────────────────────────────────────────

def _filtered_tenants(request):
    qs = platform.annotated_tenants()
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(cnpj__icontains=q)
                       | Q(memberships__user__email__icontains=q)).distinct()
    status = request.GET.get('status', '')
    if status in platform.STATUS_LABELS:
        qs = qs.filter(subscription_status=status)
    plan = request.GET.get('plan', '')
    if plan.isdigit():
        qs = qs.filter(plan_id=int(plan))
    quick = request.GET.get('f', '')
    if quick in platform.QUICK_FILTERS:
        qs = platform.apply_quick_filter(qs, quick)
    sort = request.GET.get('sort', 'recent')
    order = platform.SORTS.get(sort, platform.SORTS['recent'])[0]
    qs = qs.order_by(order, 'pk')
    tenants = [platform.decorate(t) for t in qs]
    return platform.filter_decorated(tenants, quick)


@superuser_required
def platform_home(request):
    tenants = _filtered_tenants(request)
    page = Paginator(tenants, 30).get_page(request.GET.get('page'))
    params = request.GET.copy()
    params.pop('page', None)
    return render(request, 'tenants/platform/home.html', {
        'ov': platform.overview(),
        'health': platform.platform_health(),
        'page': page,
        'plans': Plan.objects.order_by('price'),
        'status_choices': Tenant.SUBSCRIPTION_STATUS,
        'quick_filters': platform.QUICK_FILTERS,
        'sorts': {k: v[1] for k, v in platform.SORTS.items()},
        'querystring': params.urlencode(),
        'filtered': any(request.GET.get(k) for k in ('q', 'status', 'plan', 'f')),
    })


@superuser_required
def tenants_csv(request):
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="empresas-{date.today():%Y%m%d}.csv"'
    response.write('﻿')  # Excel abre com acento
    w = csv.writer(response, delimiter=';')
    w.writerow(['ID', 'Empresa', 'CNPJ', 'Dono', 'E-mail do dono', 'Plano', 'Preço', 'Status', 'Acesso liberado',
                'Fim do teste', 'Próximo vencimento', 'Produtos', 'Limite produtos', 'Usuários', 'Limite usuários',
                'Movimentações 30d', 'Último uso', 'Cadastro'])

    def fmt(d):
        if not d:
            return ''
        return timezone.localtime(d).strftime('%d/%m/%Y %H:%M') if hasattr(d, 'hour') else d.strftime('%d/%m/%Y')

    for t in _filtered_tenants(request):
        w.writerow([
            t.pk, t.name, t.cnpj or '', t.owner_name or '', t.owner_email or '',
            t.plan.display_name if t.plan else '', str(t.plan.price).replace('.', ',') if t.plan else '',
            t.get_subscription_status_display(), 'sim' if t.is_active else 'não',
            fmt(t.trial_ends_at), fmt(t.next_due_date), t.n_products,
            t.plan.max_products if t.plan else '', t.n_users, t.plan.max_users if t.plan else '',
            t.n_moves_30d, fmt(t.last_use_at), fmt(t.created_at),
        ])
    return response


# ─── Ficha da empresa ────────────────────────────────────────────────────────

@superuser_required
def tenant_detail(request, pk):
    from apps.accounts.models import TenantMembership

    tenant = platform.decorate(get_object_or_404(platform.annotated_tenants(), pk=pk))
    members = (TenantMembership.objects.filter(tenant=tenant)
               .select_related('user').order_by('-is_active', 'role', 'user__first_name'))
    events = TenantEvent.objects.filter(tenant=tenant).select_related('actor')
    kind = request.GET.get('kind', '')
    if kind in dict(TenantEvent.KINDS):
        events = events.filter(kind=kind)
    return render(request, 'tenants/platform/tenant_detail.html', {
        't': tenant,
        'members': members,
        'usage': platform.tenant_usage(tenant),
        'events': events[:100],
        'event_kinds': TenantEvent.KINDS,
        'kind': kind,
        'plans': Plan.objects.annotate(n=Count('tenants')).order_by('price'),
        'status_actions': [(k, label, needs_reason) for k, (status, label, needs_reason)
                           in platform.STATUS_ACTIONS.items()
                           if status != tenant.subscription_status or not tenant.is_active],
        'locked': [a for a in platform.locked_logins()
                   if a.username in {m.user.username.lower() for m in members}],
        'today': timezone.localdate(),
    })


@superuser_required
@require_POST
def tenant_action(request, pk):
    tenant = get_object_or_404(Tenant, pk=pk)
    action = request.POST.get('action', '')
    reason = request.POST.get('reason', '')
    try:
        if action == 'plan':
            plan = get_object_or_404(Plan, pk=request.POST.get('plan_id') or 0)
            platform.change_plan(tenant, plan, request.user, reason)
            done = f"Plano alterado para {plan.display_name}."
        elif action in platform.STATUS_ACTIONS:
            platform.set_status(tenant, action, request.user, reason)
            done = f"{platform.STATUS_ACTIONS[action][1]}: feito."
        elif action == 'trial':
            until = request.POST.get('until') or None
            platform.extend_trial(tenant, request.user,
                                  days=request.POST.get('days'),
                                  until=date.fromisoformat(until) if until else None,
                                  reason=reason)
            done = "Período de teste atualizado."
        elif action == 'due_date':
            value = request.POST.get('due_date') or None
            platform.set_due_date(tenant, date.fromisoformat(value) if value else None, request.user, reason)
            done = "Vencimento atualizado."
        elif action == 'note':
            platform.add_note(tenant, request.POST.get('note'), request.user)
            done = "Nota registrada."
        else:
            raise platform.PlatformError("Ação desconhecida.")
    except platform.PlatformError as exc:
        messages.error(request, str(exc))
    except ValueError:
        messages.error(request, "Data inválida.")
    else:
        messages.success(request, done)
    return redirect('tenants:platform_tenant', pk=pk)


# ─── Planos ──────────────────────────────────────────────────────────────────

class PlanForm(forms.ModelForm):
    class Meta:
        model = Plan
        fields = ['display_name', 'name', 'price', 'max_products', 'max_users',
                  'has_ai_matching', 'has_ai_reconciliation', 'features']
        labels = {
            'display_name': "Nome exibido", 'name': "Identificador (interno, único)",
            'price': "Preço mensal (R$)", 'max_products': "Limite de produtos (0 = sem limite)",
            'max_users': "Limite de usuários (0 = sem limite)",
            'has_ai_matching': "IA: match de produtos", 'has_ai_reconciliation': "IA: conciliação",
            'features': "Recursos (separados por vírgula, aparecem na página de planos)",
        }
        widgets = {'features': forms.Textarea(attrs={'rows': 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if not isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs['class'] = 'w-full px-3 py-2 border border-slate-300 rounded-xl text-sm'

    def clean_price(self):
        price = self.cleaned_data['price']
        if price < 0:
            raise forms.ValidationError("O preço não pode ser negativo.")
        return price

    def clean(self):
        cleaned = super().clean()
        if self.instance.pk:
            max_products = cleaned.get('max_products')
            if max_products:
                over = [t.name for t in self.instance.tenants.all() if t.products_count > max_products]
                if over:
                    self.add_error('max_products', "Estas empresas já passam do novo limite: "
                                   + ", ".join(over[:5]) + ("…" if len(over) > 5 else ""))
        return cleaned


@superuser_required
def plan_list(request):
    plans = Plan.objects.annotate(
        n=Count('tenants'),
        n_active=Count('tenants', filter=Q(tenants__subscription_status='ACTIVE')),
    ).order_by('price')
    for p in plans:
        p.revenue = p.price * p.n_active
    return render(request, 'tenants/platform/plans.html', {'plans': plans})


@superuser_required
def plan_edit(request, pk=None):
    plan = get_object_or_404(Plan, pk=pk) if pk else None
    form = PlanForm(request.POST or None, instance=plan)
    if request.method == 'POST' and form.is_valid():
        changed = form.changed_data
        saved = form.save()
        if plan:
            # Registra nas empresas afetadas quando preço ou limites mudam
            relevant = [f for f in changed if f in ('price', 'max_products', 'max_users',
                                                     'has_ai_matching', 'has_ai_reconciliation')]
            if relevant:
                for tenant in saved.tenants.all():
                    platform.record(tenant, 'PLAN', f"Plano {saved.display_name} alterado: "
                                    + ", ".join(form.fields[f].label for f in relevant), request.user,
                                    fields=relevant)
        messages.success(request, f"Plano {saved.display_name} salvo.")
        return redirect('tenants:platform_plans')
    return render(request, 'tenants/platform/plan_form.html', {
        'form': form, 'plan': plan,
        'n_tenants': plan.tenants.count() if plan else 0,
    })


# ─── Segurança ───────────────────────────────────────────────────────────────

@superuser_required
@require_POST
def unlock_login(request, attempt_id):
    from axes.models import AccessAttempt

    attempt = get_object_or_404(AccessAttempt, pk=attempt_id)
    username, ip = attempt.username, attempt.ip_address
    AccessAttempt.objects.filter(username=username, ip_address=ip).delete()
    from apps.accounts.models import TenantMembership
    for m in TenantMembership.objects.filter(user__username__iexact=username).select_related('tenant'):
        platform.record(m.tenant, 'SECURITY', f"Login de {username} desbloqueado (IP {ip})", request.user)
    messages.success(request, f"Login de {username} desbloqueado.")
    nxt = request.POST.get('next', '')
    return redirect(nxt if nxt.startswith('/admin-panel/') else 'tenants:admin_panel')
