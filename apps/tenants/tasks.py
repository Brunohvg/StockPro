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
        logger.info(f"CELERY BEAT: Detectados {count} tenants com trial expirado.")
        # Aqui poderíamos disparar e-mails ou logs específicos

    return f"Checked {count} expired trials."


@shared_task
def send_expiry_alerts():
    """Alerta diário de validade (lotes vencidos ou perto de vencer) por e-mail."""
    from apps.inventory.services.expiry import send_expiry_alerts as _send
    sent = _send()
    logger.info(f"CELERY BEAT: alertas de validade enviados para {sent} empresa(s).")
    return f"Expiry alerts sent: {sent}"
