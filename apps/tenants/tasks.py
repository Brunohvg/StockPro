import logging

from celery import shared_task
from django.utils import timezone

from .models import Tenant

logger = logging.getLogger(__name__)

@shared_task
def cleanup_expired_trials():
    """
    Task diária para verificar e registrar
    status de períodos de teste expirados.
    """
    now = timezone.now()
    # Pega tenants em TRIAL que já passaram da validade e ainda estão is_active
    expired = Tenant.objects.filter(
        subscription_status='TRIAL',
        trial_ends_at__lt=now,
        is_active=True
    )

    count = expired.count()
    if count > 0:
        logger.info(f"CELERY BEAT: Detectados {count} tenants com trial expirado (modo leitura).")

    # Suspensão automática é decisão comercial: desligada por padrão (0).
    from django.conf import settings
    suspend_after = getattr(settings, 'TRIAL_SUSPEND_AFTER_DAYS', 0)
    suspended = 0
    if suspend_after > 0:
        from .platform import record
        to_suspend = list(expired.filter(trial_ends_at__lt=now - timezone.timedelta(days=suspend_after)))
        for tenant in to_suspend:
            tenant.subscription_status = 'SUSPENDED'
            tenant.save(update_fields=['subscription_status'])
            record(tenant, 'STATUS', f"Status: Em Teste → Suspenso (automático, teste vencido há "
                   f"mais de {suspend_after} dias)")
        suspended = len(to_suspend)
        if suspended:
            logger.info(f"CELERY BEAT: {suspended} empresa(s) suspensa(s) após {suspend_after} dias de trial vencido.")

    return f"Checked {count} expired trials. Suspended {suspended}."


@shared_task
def send_expiry_alerts():
    """Alerta diário de validade (lotes vencidos ou perto de vencer) por e-mail."""
    from apps.inventory.services.expiry import send_expiry_alerts as _send
    sent = _send()
    logger.info(f"CELERY BEAT: alertas de validade enviados para {sent} empresa(s).")
    return f"Expiry alerts sent: {sent}"


@shared_task
def platform_heartbeat():
    """Sinal de vida do worker + agendador, mostrado na Central da plataforma."""
    from django.core.cache import cache
    from .platform import HEARTBEAT_KEY
    cache.set(HEARTBEAT_KEY, timezone.now(), timeout=60 * 60 * 24)
    return "ok"

# Celery autodiscover_tasks() importa apps.tenants.tasks, mas não backup_task.
# Importar explicitamente registra daily_backup, manual_backup, verify_backup
# e cleanup_old_exports nos workers de produção.
from . import backup_task  # noqa: F401, E402
