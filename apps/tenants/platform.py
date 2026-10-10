"""
Central da plataforma: ações administrativas sobre empresas e indicadores.

Toda mudança de plano, status, teste ou vencimento passa por aqui e grava um
TenantEvent (quem, quando, antes/depois e motivo). As telas em views_platform.py
só chamam estas funções.
"""
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, IntegerField, Max, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from .models import Plan, Tenant, TenantEvent

STATUS_LABELS = dict(Tenant.SUBSCRIPTION_STATUS)
# Sem uso há este tempo (nenhum login e nenhuma movimentação) = risco de cancelar.
INACTIVE_AFTER = timedelta(days=14)
NEAR_LIMIT_PCT = 80


class PlatformError(ValueError):
    """Ação inválida (mensagem pronta para mostrar ao admin)."""


def record(tenant, kind, message, actor=None, reason='', **data):
    return TenantEvent.objects.create(
        tenant=tenant, kind=kind, message=message[:255], actor=actor,
        reason=(reason or '').strip(), data=data)


def _lock(tenant):
    return Tenant.objects.select_for_update().get(pk=tenant.pk)


# ─── Ações ───────────────────────────────────────────────────────────────────

@transaction.atomic
def change_plan(tenant, plan, actor, reason=''):
    tenant = _lock(tenant)
    old = tenant.plan
    if old and old.pk == plan.pk:
        raise PlatformError("A empresa já está nesse plano.")
    in_use = tenant.products_count
    if plan.max_products and in_use > plan.max_products:
        raise PlatformError(
            f"A empresa tem {in_use} produtos ativos e o plano {plan.display_name} permite "
            f"{plan.max_products}. Peça para arquivar produtos antes ou escolha outro plano.")
    tenant.plan = plan
    tenant.save(update_fields=['plan'])
    record(tenant, 'PLAN', f"Plano: {old.display_name if old else 'nenhum'} → {plan.display_name}",
           actor, reason, before=old.pk if old else None, after=plan.pk,
           price_before=str(old.price) if old else None, price_after=str(plan.price))
    return tenant


# Transições permitidas pela Central. Motivo é obrigatório nas que tiram acesso.
STATUS_ACTIONS = {
    'activate': ('ACTIVE', "Ativar assinatura", False),
    'suspend': ('SUSPENDED', "Suspender", True),
    'cancel': ('CANCELLED', "Cancelar", True),
    'back_to_trial': ('TRIAL', "Voltar para teste", False),
}


@transaction.atomic
def set_status(tenant, action, actor, reason=''):
    if action not in STATUS_ACTIONS:
        raise PlatformError("Ação desconhecida.")
    new_status, label, needs_reason = STATUS_ACTIONS[action]
    if needs_reason and not (reason or '').strip():
        raise PlatformError(f"Informe o motivo para {label.lower()}.")
    tenant = _lock(tenant)
    old_status, old_active = tenant.subscription_status, tenant.is_active
    if old_status == new_status and tenant.is_active:
        raise PlatformError(f"A empresa já está {STATUS_LABELS[new_status].lower()}.")
    tenant.subscription_status = new_status
    fields = ['subscription_status']
    if new_status in ('ACTIVE', 'TRIAL') and not tenant.is_active:
        tenant.is_active = True  # reativar libera o acesso por completo
        fields.append('is_active')
    if new_status == 'TRIAL' and (not tenant.trial_ends_at or tenant.trial_ends_at < timezone.now()):
        tenant.trial_ends_at = timezone.now() + timedelta(days=7)
        fields.append('trial_ends_at')
    tenant.save(update_fields=fields)
    record(tenant, 'STATUS',
           f"Status: {STATUS_LABELS[old_status]} → {STATUS_LABELS[new_status]}"
           + (" (acesso liberado)" if 'is_active' in fields else ''),
           actor, reason, before=old_status, after=new_status, was_active=old_active)
    return tenant


@transaction.atomic
def extend_trial(tenant, actor, days=None, until=None, reason=''):
    tenant = _lock(tenant)
    if tenant.subscription_status != 'TRIAL':
        raise PlatformError("Só dá para estender o teste de empresa em teste. "
                            "Use \"Voltar para teste\" antes, se for o caso.")
    now = timezone.now()
    old = tenant.trial_ends_at
    if until:
        new = timezone.make_aware(timezone.datetime.combine(until, timezone.datetime.max.time()).replace(microsecond=0))
        if new <= now:
            raise PlatformError("A nova data precisa ser no futuro.")
    else:
        try:
            days = int(days)
        except (TypeError, ValueError):
            raise PlatformError("Informe quantos dias.")
        if not 1 <= days <= 365:
            raise PlatformError("Informe de 1 a 365 dias.")
        new = max(old or now, now) + timedelta(days=days)
    tenant.trial_ends_at = new
    tenant.save(update_fields=['trial_ends_at'])
    record(tenant, 'TRIAL',
           f"Teste até {timezone.localtime(new):%d/%m/%Y}"
           + (f" (era {timezone.localtime(old):%d/%m/%Y})" if old else ''),
           actor, reason, before=old.isoformat() if old else None, after=new.isoformat())
    return tenant


@transaction.atomic
def set_due_date(tenant, due_date, actor, reason=''):
    tenant = _lock(tenant)
    old = tenant.next_due_date
    if old == due_date:
        raise PlatformError("Esse já é o vencimento cadastrado.")
    tenant.next_due_date = due_date
    tenant.save(update_fields=['next_due_date'])
    text = f"{due_date:%d/%m/%Y}" if due_date else "sem vencimento"
    record(tenant, 'DUE_DATE', f"Próximo vencimento: {text}", actor, reason,
           before=old.isoformat() if old else None, after=due_date.isoformat() if due_date else None)
    return tenant


def add_note(tenant, text, actor):
    text = (text or '').strip()
    if not text:
        raise PlatformError("A nota está vazia.")
    first_line = text.splitlines()[0]
    return record(tenant, 'NOTE', first_line[:120], actor, text)


# ─── Lista de empresas (uma consulta só, sem N+1) ────────────────────────────

def annotated_tenants():
    from django.contrib.auth.models import User

    from apps.accounts.models import TenantMembership
    from apps.inventory.models import StockMovement
    from apps.products.models import ProductVariant

    since_30 = timezone.now() - timedelta(days=30)
    owner = TenantMembership.objects.filter(
        tenant=OuterRef('pk'), role='OWNER', is_active=True).order_by('joined_at')

    def count_of(qs):
        return Coalesce(Subquery(
            qs.order_by().values('tenant').annotate(c=Count('pk')).values('c')[:1],
            output_field=IntegerField()), Value(0))

    return Tenant.objects.select_related('plan').annotate(
        n_products=count_of(ProductVariant.objects.filter(
            tenant=OuterRef('pk'), is_active=True, product__is_active=True)),
        n_users=count_of(TenantMembership.objects.filter(tenant=OuterRef('pk'), is_active=True)),
        n_moves_30d=count_of(StockMovement.objects.filter(tenant=OuterRef('pk'), created_at__gte=since_30)),
        last_movement_at=Subquery(StockMovement.objects.filter(tenant=OuterRef('pk'))
                                  .order_by('-created_at').values('created_at')[:1]),
        last_login_at=Subquery(User.objects.filter(memberships__tenant=OuterRef('pk'))
                               .exclude(last_login=None).order_by('-last_login').values('last_login')[:1]),
        owner_email=Subquery(owner.values('user__email')[:1]),
        owner_name=Subquery(owner.values('user__first_name')[:1]),
    )


def _pct(used, limit):
    return int(used * 100 / limit) if limit else 0


def decorate(tenant):
    """Campos calculados para a tela (sobre um tenant de annotated_tenants)."""
    now = timezone.now()
    plan = tenant.plan
    tenant.products_pct = _pct(tenant.n_products, plan.max_products if plan else 0)
    tenant.users_pct = _pct(tenant.n_users, plan.max_users if plan else 0)
    last_use = max([d for d in (tenant.last_movement_at, tenant.last_login_at) if d], default=None)
    tenant.last_use_at = last_use
    tenant.is_idle = (tenant.subscription_status in ('ACTIVE', 'TRIAL')
                      and (last_use is None or now - last_use > INACTIVE_AFTER)
                      and now - tenant.created_at > INACTIVE_AFTER)
    tenant.trial_days_left = None
    if tenant.subscription_status == 'TRIAL' and tenant.trial_ends_at:
        tenant.trial_days_left = (tenant.trial_ends_at - now).days if tenant.trial_ends_at > now else -1
    tenant.is_overdue = bool(tenant.next_due_date and tenant.subscription_status == 'ACTIVE'
                             and tenant.next_due_date < timezone.localdate())
    tenant.near_limit = max(tenant.products_pct, tenant.users_pct) >= NEAR_LIMIT_PCT
    return tenant


QUICK_FILTERS = {
    'trial_ending': "Teste vencendo (7 dias)",
    'trial_expired': "Teste vencido",
    'idle': "Sem uso há 14+ dias",
    'near_limit': "Perto do limite",
    'overdue': "Vencimento passado",
    'blocked': "Suspensas/canceladas",
}


def apply_quick_filter(qs, key):
    now = timezone.now()
    if key == 'trial_ending':
        return qs.filter(subscription_status='TRIAL', trial_ends_at__gte=now,
                         trial_ends_at__lte=now + timedelta(days=7))
    if key == 'trial_expired':
        return qs.filter(subscription_status='TRIAL', trial_ends_at__lt=now)
    if key == 'overdue':
        return qs.filter(subscription_status='ACTIVE', next_due_date__lt=timezone.localdate())
    if key == 'blocked':
        return qs.filter(Q(subscription_status__in=['SUSPENDED', 'CANCELLED']) | Q(is_active=False))
    return qs  # idle e near_limit são calculados depois (decorate)


def filter_decorated(tenants, key):
    if key == 'idle':
        return [t for t in tenants if t.is_idle]
    if key == 'near_limit':
        return [t for t in tenants if t.near_limit]
    return tenants


SORTS = {
    'recent': ('-created_at', "Mais recentes"),
    'name': ('name', "Nome"),
    'trial': ('trial_ends_at', "Fim do teste"),
    'usage': ('-n_moves_30d', "Mais uso (30 dias)"),
    'products': ('-n_products', "Mais produtos"),
}


# ─── Visão geral ─────────────────────────────────────────────────────────────

@dataclass
class Overview:
    total: int
    by_status: dict
    mrr: Decimal
    mrr_by_plan: list
    new_this_month: int
    trial_ending: int
    trial_expired: int
    overdue: int
    idle: int
    near_limit: int
    idle_list: list
    near_limit_list: list
    trial_ending_list: list


def overview():
    now = timezone.now()
    by_status = dict(Tenant.objects.values_list('subscription_status').annotate(c=Count('pk')))
    paying = Tenant.objects.filter(subscription_status='ACTIVE', is_active=True, plan__isnull=False)
    mrr = paying.aggregate(v=Sum('plan__price'))['v'] or Decimal('0')
    mrr_by_plan = list(paying.values('plan__display_name').annotate(
        n=Count('pk'), total=Sum('plan__price')).order_by('-total'))
    month_start = timezone.localtime(now).replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    decorated = [decorate(t) for t in annotated_tenants().filter(
        subscription_status__in=['ACTIVE', 'TRIAL'], is_active=True)]
    idle = sorted([t for t in decorated if t.is_idle],
                  key=lambda t: t.last_use_at or t.created_at)
    near = sorted([t for t in decorated if t.near_limit],
                  key=lambda t: -max(t.products_pct, t.users_pct))
    ending = sorted([t for t in decorated if t.trial_days_left is not None and 0 <= t.trial_days_left <= 7],
                    key=lambda t: t.trial_ends_at)
    return Overview(
        total=sum(by_status.values()),
        by_status={k: by_status.get(k, 0) for k in STATUS_LABELS},
        mrr=mrr,
        mrr_by_plan=mrr_by_plan,
        new_this_month=Tenant.objects.filter(created_at__gte=month_start).count(),
        trial_ending=len(ending),
        trial_expired=Tenant.objects.filter(subscription_status='TRIAL', trial_ends_at__lt=now).count(),
        overdue=Tenant.objects.filter(subscription_status='ACTIVE',
                                      next_due_date__lt=timezone.localdate()).count(),
        idle=len(idle), near_limit=len(near),
        idle_list=idle[:6], near_limit_list=near[:6], trial_ending_list=ending[:6],
    )


# ─── Saúde da plataforma ─────────────────────────────────────────────────────

HEARTBEAT_KEY = 'platform:heartbeat'
HEARTBEAT_STALE = timedelta(minutes=15)


def platform_health():
    from django.conf import settings
    from django.core.cache import cache

    from apps.inventory.models import ImportBatch

    from .backup_status import health as backup_health

    now = timezone.now()
    beat = cache.get(HEARTBEAT_KEY)
    worker = {'last': beat, 'ok': bool(beat and now - beat < HEARTBEAT_STALE)}
    since = now - timedelta(hours=24)
    failed_imports = (ImportBatch.objects.filter(created_at__gte=since, status='FAILED')
                      .select_related('tenant').order_by('-created_at'))
    return {
        'worker': worker,
        'backup': backup_health(),
        'failed_imports': failed_imports.count(),
        'failed_imports_list': list(failed_imports[:5]),
        'locked': locked_logins(),
        'axes_enabled': getattr(settings, 'AXES_ENABLED', False),
    }


def locked_logins():
    """Pares usuário+IP bloqueados agora pelo django-axes."""
    from django.conf import settings
    try:
        from axes.models import AccessAttempt
    except Exception:  # axes não instalado
        return []
    cool_off = getattr(settings, 'AXES_COOLOFF_TIME', None)
    qs = AccessAttempt.objects.filter(failures_since_start__gte=getattr(settings, 'AXES_FAILURE_LIMIT', 5))
    if cool_off:
        qs = qs.filter(attempt_time__gte=timezone.now() - cool_off)
    return list(qs.order_by('-attempt_time')[:20])


def tenant_usage(tenant):
    """Números da ficha da empresa."""
    from apps.core.services import AIService
    from apps.inventory.models import ImportBatch, NfeDocument, StockMovement
    from apps.products.models import Product

    now = timezone.now()
    moves = StockMovement.objects.filter(tenant=tenant)
    agg = moves.aggregate(
        d7=Count('pk', filter=Q(created_at__gte=now - timedelta(days=7))),
        d30=Count('pk', filter=Q(created_at__gte=now - timedelta(days=30))),
        last=Max('created_at'),
    )
    ai_used = None
    try:
        from django.core.cache import cache
        # mesma chave do AIService.call_for_tenant
        ai_used = cache.get(f"ai-quota:{tenant.pk}:{timezone.localdate():%Y%m%d}", 0)
    except Exception:
        pass
    return {
        'moves_7d': agg['d7'], 'moves_30d': agg['d30'], 'last_move': agg['last'],
        'products_active': tenant.products_count,
        'products_archived': Product.objects.filter(tenant=tenant, is_active=False).count(),
        'users': tenant.users_count,
        'nfe_imported': NfeDocument.objects.filter(tenant=tenant, status='IMPORTED').count(),
        'imports_30d': ImportBatch.objects.filter(tenant=tenant, created_at__gte=now - timedelta(days=30)).count(),
        'ai_used_today': ai_used,
        'ai_allowed': AIService.tenant_has_ai(tenant),
    }


def config_checks():
    """Conferência rápida da configuração de produção (sem mostrar valores secretos)."""
    from django.conf import settings

    cache_backend = settings.CACHES['default']['BACKEND']
    email_backend = getattr(settings, 'EMAIL_BACKEND', '')

    def item(ok, label, detail, level='danger'):
        return {'ok': bool(ok), 'label': label, 'detail': detail, 'level': 'ok' if ok else level}

    return [
        item(not settings.DEBUG, "Modo de depuração desligado",
             "DEBUG=False em produção." if not settings.DEBUG else "DEBUG está ligado: mostra detalhes internos em erros."),
        item(getattr(settings, 'CELERY_BROKER_URL', ''), "Fila de tarefas (Celery)",
             "CELERY_BROKER_URL configurado." if getattr(settings, 'CELERY_BROKER_URL', '') else
             "Sem CELERY_BROKER_URL: backup, alertas e limpeza não rodam."),
        item('redis' in cache_backend.lower(), "Cache compartilhado (Redis)",
             "Cache no Redis." if 'redis' in cache_backend.lower() else
             "Cache só na memória do processo: limites de login e cota de IA não valem entre containers.",
             level='warning'),
        item(getattr(settings, 'BACKUP_S3_BUCKET', ''), "Cópia externa do backup",
             "Bucket configurado." if getattr(settings, 'BACKUP_S3_BUCKET', '') else
             "Sem BACKUP_S3_BUCKET: se o servidor se perder, o backup vai junto."),
        item(getattr(settings, 'BACKUP_ENCRYPTION_PASSPHRASE', ''), "Backup criptografado",
             "Senha de criptografia configurada." if getattr(settings, 'BACKUP_ENCRYPTION_PASSPHRASE', '') else
             "Sem BACKUP_ENCRYPTION_PASSPHRASE."),
        item('smtp' in email_backend.lower(), "Envio de e-mail",
             "SMTP configurado." if 'smtp' in email_backend.lower() else
             "Sem EMAIL_HOST: recuperação de senha e alertas não saem.", level='warning'),
        item(getattr(settings, 'BACKUP_ALERT_EMAIL', ''), "Alerta de falha no backup",
             "E-mail de alerta configurado." if getattr(settings, 'BACKUP_ALERT_EMAIL', '') else
             "Sem BACKUP_ALERT_EMAIL: falha de backup não avisa ninguém.", level='warning'),
        item(getattr(settings, 'AXES_ENABLED', False), "Limite de tentativas de login",
             "Ligado (django-axes)." if getattr(settings, 'AXES_ENABLED', False) else "Desligado (AXES_ENABLED=False).",
             level='warning'),
    ]
