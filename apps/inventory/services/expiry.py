"""Consultas e alertas de validade (lotes)."""
import logging
from datetime import timedelta

from django.utils import timezone

logger = logging.getLogger(__name__)


def expiring_lots(tenant, days=30):
    """Retorna (vencidos, vencendo_em_ate_N_dias) com saldo > 0, ordenados pela validade."""
    from apps.inventory.models import StockLot
    if tenant is None:
        return [], []
    today = timezone.localdate()
    base = StockLot.objects.filter(
        tenant=tenant, quantity__gt=0, expiry_date__isnull=False, variant__is_active=True,
    ).select_related('variant', 'variant__product').order_by('expiry_date')
    expired = list(base.filter(expiry_date__lt=today))
    soon = list(base.filter(expiry_date__gte=today, expiry_date__lte=today + timedelta(days=days)))
    return expired, soon


def send_expiry_alerts():
    """E-mail diário para o alert_email de cada empresa com lotes vencidos ou perto de vencer."""
    from django.conf import settings
    from django.core.mail import send_mail

    from apps.core.models import SystemSetting

    sent = 0
    for cfg in SystemSetting.objects.select_related('tenant').filter(
        tenant__is_active=True, alert_email__isnull=False,
    ).exclude(alert_email=''):
        expired, soon = expiring_lots(cfg.tenant, cfg.expiry_alert_days)
        if not expired and not soon:
            continue
        lines = [f"StockPro: validade dos produtos de {cfg.company_name}", ""]
        if expired:
            lines.append(f"VENCIDOS ({len(expired)}):")
            lines += [f"  - {l.variant.display_name if hasattr(l.variant, 'display_name') else l.variant.sku} "
                      f"(SKU {l.variant.sku}) lote {l.lot_number or '-'}: venceu em {l.expiry_date:%d/%m/%Y}, "
                      f"saldo {l.quantity.normalize()}" for l in expired[:100]]
            lines.append("")
        if soon:
            lines.append(f"VENCEM EM ATÉ {cfg.expiry_alert_days} DIAS ({len(soon)}):")
            lines += [f"  - {l.variant.display_name if hasattr(l.variant, 'display_name') else l.variant.sku} "
                      f"(SKU {l.variant.sku}) lote {l.lot_number or '-'}: {l.expiry_date:%d/%m/%Y} "
                      f"({l.days_to_expiry} dias), saldo {l.quantity.normalize()}" for l in soon[:100]]
        try:
            send_mail(
                subject=f"[StockPro] {len(expired)} vencido(s), {len(soon)} perto de vencer",
                message="\n".join(lines),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[cfg.alert_email],
            )
            sent += 1
        except Exception as exc:  # e-mail fora do ar não pode derrubar a task
            logger.error("Falha ao enviar alerta de validade para tenant %s: %s", cfg.tenant_id, exc)
    return sent
