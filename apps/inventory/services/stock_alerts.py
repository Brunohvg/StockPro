"""E-mails de estoque mínimo (diário) e resumo semanal para o dono (patch 9)."""
import logging
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db.models import F, Sum
from django.template.loader import render_to_string
from django.utils import timezone

from . import replenishment as rep

logger = logging.getLogger(__name__)


def _site(path):
    base = getattr(settings, 'SITE_URL', '') or ''
    return f'{base}{path}' if base else ''


def _send(cfg, subject, template, context):
    context = {**context, 'company': cfg.company_name, 'site_url': getattr(settings, 'SITE_URL', '')}
    html = render_to_string(f'emails/{template}.html', context)
    text = render_to_string(f'emails/{template}.txt', context)
    msg = EmailMultiAlternatives(subject, text, settings.DEFAULT_FROM_EMAIL, [cfg.alert_email])
    msg.attach_alternative(html, 'text/html')
    msg.send()


def _configs(flag):
    from apps.core.models import SystemSetting
    return (SystemSetting.objects.select_related('tenant')
            .filter(tenant__is_active=True, alert_email__isnull=False, **{flag: True})
            .exclude(alert_email=''))


def send_low_stock_alerts():
    """
    Diário. Manda e-mail só quando há variação NOVA no mínimo desde o último aviso;
    quem voltou acima do mínimo sai da lista e, se cair de novo, avisa outra vez.
    """
    sent = 0
    for cfg in _configs('low_stock_alerts_enabled'):
        low = list(rep.low_stock_qs(cfg.tenant).select_related('product', 'product__default_supplier')
                   .prefetch_related('attribute_values').order_by('current_stock', 'product__name'))
        current = sorted(v.pk for v in low)
        already = set(cfg.low_stock_alerted_ids or [])
        new = [v for v in low if v.pk not in already]
        if new:
            try:
                _send(cfg, f'[StockPro] {len(new)} produto(s) chegaram ao estoque mínimo', 'low_stock', {
                    'new': new[:50], 'new_count': len(new), 'total': len(low),
                    'zero': sum(1 for v in low if v.current_stock <= 0),
                    'link': _site('/inventory/repor/'),
                })
                sent += 1
            except Exception as exc:  # e-mail fora do ar não pode derrubar a task
                logger.error('Falha no alerta de estoque mínimo do tenant %s: %s', cfg.tenant_id, exc)
                continue
        if current != sorted(already):
            type(cfg).objects.filter(pk=cfg.pk).update(low_stock_alerted_ids=current)
    return sent


def weekly_summary(tenant, now=None):
    """
    Números da semana que terminou (7 dias até agora). Vêm do mesmo serviço da
    Visão Geral e da Inteligência (apps/reports/metrics.py), para os três baterem.
    """
    from apps.inventory.services.expiry import expiring_lots
    from apps.reports import metrics

    now = now or timezone.now()
    start = now - timedelta(days=7)
    sales = metrics.sales_summary(tenant, start, now)
    ins = metrics.entries_qs(tenant, start, now)
    in_value = sum((m.quantity * (m.unit_cost or 0) for m in ins.only('quantity', 'unit_cost')), Decimal('0'))
    top = [{'variant': r['variant'], 'qty': r['qty']}
           for r in sorted(sales['by_variant'], key=lambda r: r['qty'], reverse=True)[:5]]

    low_qs = metrics.low_stock_qs(tenant)
    low = list(low_qs.select_related('product').prefetch_related('attribute_values')
               .order_by('current_stock', 'product__name')[:10])
    stall = metrics.stalled(tenant, now=now, limit=5)
    snap = metrics.stock_snapshot(tenant)
    expired, soon = expiring_lots(tenant, 30)
    return {
        'start': timezone.localtime(start).date(), 'end': timezone.localtime(now).date(),
        'out_qty': sales['units'], 'in_qty': metrics.units_in(tenant, start, now), 'in_value': in_value,
        'revenue': sales['revenue'], 'top': top,
        'low': low, 'low_count': low_qs.count(),
        'stalled': stall['items'], 'stalled_count': stall['count'], 'stalled_value': stall['value'],
        'expired': len(expired), 'expiring': soon[:5], 'expiring_count': len(soon),
        'stock_value': snap['value'], 'skus': snap['skus'],
    }


def send_weekly_summaries():
    sent = 0
    for cfg in _configs('weekly_summary_enabled'):
        try:
            data = weekly_summary(cfg.tenant)
            if not data['skus']:
                continue  # empresa sem produto: nada para resumir
            _send(cfg, f"[StockPro] Resumo da semana {data['start']:%d/%m} a {data['end']:%d/%m}", 'weekly_summary', {
                **data, 'link_replenish': _site('/inventory/repor/'), 'link_dashboard': _site('/app/'),
            })
            sent += 1
        except Exception as exc:
            logger.error('Falha no resumo semanal do tenant %s: %s', cfg.tenant_id, exc)
    return sent
