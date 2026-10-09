"""
Situação do backup para as telas (painel da plataforma e aviso ao cliente).

As execuções ficam em BackupRun. ``trigger='verify'`` marca uma conferência
(download + descriptografia do último dump), não um backup novo.
"""
import os
import shutil
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from django.conf import settings
from django.utils import timezone

VERIFY = 'verify'
# Um backup que passa disso ainda "em andamento" é considerado interrompido
# (worker reiniciado no meio, por exemplo) e não impede um novo.
RUNNING_STALE_AFTER = timedelta(hours=3)
# O backup roda uma vez por dia; com folga para atrasos do agendador.
FRESH_FOR = timedelta(hours=26)


@dataclass
class BackupHealth:
    level: str              # ok | warning | danger
    headline: str
    detail: str
    last_success: Optional[object]   # BackupRun
    last_run: Optional[object]
    last_verify: Optional[object]
    running: Optional[object]
    external_enabled: bool
    encryption_enabled: bool


def backups():
    from .models import BackupRun
    return BackupRun.objects.exclude(trigger=VERIFY)


def running_backup():
    """Backup em andamento de verdade (ignora os que ficaram presos)."""
    cutoff = timezone.now() - RUNNING_STALE_AFTER
    return backups().filter(status='RUNNING', started_at__gte=cutoff).first()


def is_stale_running(run):
    return run.status == 'RUNNING' and run.started_at < timezone.now() - RUNNING_STALE_AFTER


def health():
    from .backup import s3_enabled
    from .models import BackupRun

    external = s3_enabled()
    encryption = bool(getattr(settings, 'BACKUP_ENCRYPTION_PASSPHRASE', ''))
    last_success = backups().filter(status__in=['SUCCESS', 'LOCAL_ONLY']).first()
    last_run = backups().exclude(status='RUNNING').first()
    last_verify = BackupRun.objects.filter(trigger=VERIFY).exclude(status='RUNNING').first()
    running = running_backup()
    now = timezone.now()

    def build(level, headline, detail):
        return BackupHealth(level, headline, detail, last_success, last_run, last_verify,
                            running, external, encryption)

    if last_success is None:
        return build('danger', "Nenhum backup concluído ainda",
                     "Rode \"Fazer backup agora\" e confira se termina sem erro.")
    when = timezone.localtime(last_success.finished_at or last_success.started_at)
    if last_run and last_run.status == 'FAILED' and last_run.started_at > last_success.started_at:
        return build('danger', "O último backup falhou",
                     f"Último que deu certo: {when:%d/%m/%Y %H:%M}. Veja a mensagem de erro abaixo.")
    if now - (last_success.finished_at or last_success.started_at) > FRESH_FOR:
        return build('danger', "Backup atrasado",
                     f"O último concluído foi em {when:%d/%m/%Y %H:%M}. Confira se o worker e o beat estão rodando.")
    if last_success.status == 'LOCAL_ONLY':
        return build('warning', "Backup só no próprio servidor",
                     "Se o servidor for perdido, o backup vai junto. Configure o bucket (BACKUP_S3_*).")
    return build('ok', "Backup em dia",
                 f"Último concluído em {when:%d/%m/%Y %H:%M}, enviado ao bucket"
                 f"{' e criptografado' if last_success.encrypted else ''}.")


def last_success_for_clients():
    """Data do último backup concluído nas últimas 48 h, para o aviso ao cliente (ou None)."""
    run = backups().filter(status__in=['SUCCESS', 'LOCAL_ONLY']).first()
    if run is None:
        return None
    finished = run.finished_at or run.started_at
    if timezone.now() - finished > timedelta(hours=48):
        return None
    return finished


def local_disk():
    """Espaço usado pelos dumps locais e livre no volume de backup."""
    path = settings.BACKUP_DIR
    if not os.path.isdir(path):
        return None
    used = 0
    files = 0
    for name in os.listdir(path):
        full = os.path.join(path, name)
        if os.path.isfile(full):
            used += os.path.getsize(full)
            files += 1
    usage = shutil.disk_usage(path)
    return {'used': used, 'files': files, 'free': usage.free, 'total': usage.total,
            'free_pct': round(usage.free * 100 / usage.total) if usage.total else 0}
