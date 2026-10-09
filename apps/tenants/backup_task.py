"""
Tarefas agendadas de backup (Celery Beat, ver CELERY_BEAT_SCHEDULE no settings.py).

- daily_backup (03:30): dump do PostgreSQL + mídia, conferidos, opcionalmente
  criptografados e enviados ao bucket S3 compatível. Lógica em apps/tenants/backup.py.
- cleanup_old_exports (04:15): apaga exportações antigas e as criadas pelo backup antigo.
"""
import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task
def daily_backup():
    from .backup import run_backup
    run = run_backup(trigger='beat')
    summary = f"Backup {run.get_status_display()}: {run.message}".strip()
    logger.info(summary)
    return summary


@shared_task
def manual_backup(requested_by=''):
    """Backup pedido pelo painel da plataforma."""
    from .backup import run_backup
    run = run_backup(trigger='painel')
    if requested_by:
        run.message = (f"Pedido por {requested_by}.\n" + run.message).strip()
        run.save(update_fields=['message'])
    return f"Backup {run.get_status_display()}"


@shared_task
def verify_backup(requested_by=''):
    """Baixa o último dump do bucket, descriptografa e confere. Registra como BackupRun(trigger='verify')."""
    from .backup import verify_latest_remote
    from .backup_status import VERIFY
    from .models import BackupRun

    run = BackupRun.objects.create(trigger=VERIFY)
    prefix = f"Pedido por {requested_by}.\n" if requested_by else ''
    try:
        key = verify_latest_remote()
    except Exception as exc:
        run.status = 'FAILED'
        run.message = f"{prefix}{type(exc).__name__}: {exc}"
        logger.exception("Conferência do backup falhou")
    else:
        run.status = 'SUCCESS'
        run.remote_keys = [key]
        run.encrypted = key.endswith('.gpg')
        run.message = f"{prefix}{key} baixado, aberto e conferido: íntegro e completo."
    run.finished_at = timezone.now()
    run.save()
    return run.get_status_display()


@shared_task
def cleanup_old_exports():
    """
    Remove exportações (registro + arquivo):
    - criadas pelo sistema (sem usuário), como as que o backup antigo gerava todo dia;
    - com mais de EXPORT_RETENTION_DAYS dias.
    """
    from django.db.models import Q

    from apps.inventory.models import ExportBatch

    now = timezone.now()
    old = ExportBatch.objects.filter(
        Q(user__isnull=True, created_at__lt=now - timedelta(days=1))
        | Q(created_at__lt=now - timedelta(days=settings.EXPORT_RETENTION_DAYS))
    )
    removed = 0
    for batch in old.iterator():
        if batch.file:
            batch.file.delete(save=False)
        batch.delete()
        removed += 1
    logger.info(f"Limpeza de exportações: {removed} removida(s).")
    return f"Exports removed: {removed}"
