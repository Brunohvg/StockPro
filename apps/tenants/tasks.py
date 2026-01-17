from celery import shared_task
from django.utils import timezone
from .models import Tenant
import logging

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
