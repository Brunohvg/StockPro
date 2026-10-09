"""Tarefas periódicas de contas."""
import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task
def cleanup_login_logs():
    """Apaga o histórico de logins (axes) mais velho que AXES_ACCESS_LOG_RETENTION_DAYS."""
    from axes.models import AccessAttempt, AccessLog

    cutoff = timezone.now() - timedelta(days=settings.AXES_ACCESS_LOG_RETENTION_DAYS)
    logs, _ = AccessLog.objects.filter(attempt_time__lt=cutoff).delete()
    attempts, _ = AccessAttempt.objects.filter(attempt_time__lt=cutoff).delete()
    logger.info("Limpeza de logins: %s registros de acesso e %s tentativas apagados.", logs, attempts)
    return logs + attempts
