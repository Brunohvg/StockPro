"""
Backup do StockPro: dump do PostgreSQL + arquivos de mídia, conferidos,
opcionalmente criptografados (GPG AES-256) e enviados para um bucket S3
compatível (Backblaze B2, Cloudflare R2, AWS S3, Wasabi, MinIO).

Restauração: ver docs/BACKUP.md.
"""
import gzip
import logging
import os
import shutil
import subprocess
import tarfile
import tempfile
from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

DUMP_PREFIX = 'stockpro_db_'
MEDIA_PREFIX = 'stockpro_media_'
DUMP_FOOTER = b'PostgreSQL database dump complete'
# Pastas de mídia que não precisam de backup (regeráveis)
MEDIA_EXCLUDE = {'exports'}


class BackupError(Exception):
    pass


# ---------------------------------------------------------------- utilidades

def s3_enabled():
    return bool(settings.BACKUP_S3_BUCKET)


def s3_client():
    import boto3
    from botocore.config import Config
    kwargs = {
        'aws_access_key_id': settings.BACKUP_S3_ACCESS_KEY_ID or None,
        'aws_secret_access_key': settings.BACKUP_S3_SECRET_ACCESS_KEY or None,
        'config': Config(retries={'max_attempts': 5, 'mode': 'standard'}),
    }
    if settings.BACKUP_S3_ENDPOINT_URL:
        kwargs['endpoint_url'] = settings.BACKUP_S3_ENDPOINT_URL
    if settings.BACKUP_S3_REGION:
        kwargs['region_name'] = settings.BACKUP_S3_REGION
    return boto3.client('s3', **kwargs)


def _prefix():
    prefix = settings.BACKUP_S3_PREFIX or ''
    return prefix if not prefix or prefix.endswith('/') else prefix + '/'


def verify_dump_gz(path):
    """Confere que o .sql.gz abre inteiro e termina com o rodapé do pg_dump."""
    tail = b''
    try:
        with gzip.open(path, 'rb') as fh:
            while True:
                chunk = fh.read(1024 * 1024)
                if not chunk:
                    break
                tail = (tail + chunk)[-4096:]
    except (OSError, EOFError) as exc:
        raise BackupError(f"Dump corrompido ({exc}).")
    if DUMP_FOOTER not in tail:
        raise BackupError("Dump incompleto: o rodapé do pg_dump não foi encontrado.")


def verify_media_tar(path):
    try:
        with tarfile.open(path, 'r:gz') as tar:
            for _ in tar:
                pass
    except (tarfile.TarError, OSError, EOFError) as exc:
        raise BackupError(f"Arquivo de mídia corrompido ({exc}).")


def _gpg(args, passphrase):
    home = tempfile.mkdtemp(prefix='gpg-')
    try:
        proc = subprocess.run(
            ['gpg', '--batch', '--yes', '--homedir', home, '--pinentry-mode', 'loopback',
             '--passphrase-fd', '0', *args],
            input=passphrase.encode(), capture_output=True, timeout=3600,
        )
    finally:
        shutil.rmtree(home, ignore_errors=True)
    if proc.returncode != 0:
        raise BackupError("gpg falhou: " + proc.stderr.decode('utf-8', 'replace')[-300:])


def encrypt_file(path, passphrase):
    out = path + '.gpg'
    _gpg(['--symmetric', '--cipher-algo', 'AES256', '-o', out, path], passphrase)
    return out


def decrypt_file(path, passphrase, out):
    _gpg(['-d', '-o', out, path], passphrase)
    return out


# ------------------------------------------------------------------- etapas

def dump_database(backup_dir, stamp, db=None):
    db = db or settings.DATABASES.get('default', {})
    if 'postgresql' not in db.get('ENGINE', ''):
        raise BackupError("Banco não é PostgreSQL: dump não suportado (ambiente de desenvolvimento?).")
    path = os.path.join(backup_dir, f'{DUMP_PREFIX}{stamp}.sql.gz')
    env = {**os.environ, 'PGPASSWORD': db.get('PASSWORD') or ''}
    cmd = ['pg_dump', '-h', db.get('HOST') or 'localhost', '-p', str(db.get('PORT') or 5432),
           '-U', db.get('USER') or '', '-d', db.get('NAME') or '',
           '--no-password', '--no-owner', '--no-privileges']
    try:
        with open(path, 'wb') as fh:
            p1 = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
            p2 = subprocess.Popen(['gzip', '-6'], stdin=p1.stdout, stdout=fh, stderr=subprocess.PIPE)
            p1.stdout.close()
            p2.communicate()
            _, pg_err = p1.communicate()
    except FileNotFoundError:
        raise BackupError("pg_dump não encontrado no container (instale postgresql-client-17).")
    if p1.returncode != 0 or p2.returncode != 0:
        if os.path.exists(path):
            os.remove(path)
        raise BackupError("pg_dump falhou: " + pg_err.decode('utf-8', 'replace')[-300:])
    try:
        verify_dump_gz(path)
    except BackupError:
        os.remove(path)  # nunca deixar um dump corrompido parecendo válido
        raise
    return path


def archive_media(backup_dir, stamp):
    media_root = str(settings.MEDIA_ROOT)
    path = os.path.join(backup_dir, f'{MEDIA_PREFIX}{stamp}.tar.gz')
    with tarfile.open(path, 'w:gz') as tar:
        if os.path.isdir(media_root):
            for entry in sorted(os.listdir(media_root)):
                if entry in MEDIA_EXCLUDE:
                    continue
                tar.add(os.path.join(media_root, entry), arcname=entry)
    verify_media_tar(path)
    return path


def upload(path):
    key = f"{_prefix()}{timezone.localdate():%Y/%m}/{os.path.basename(path)}"
    client = s3_client()
    client.upload_file(path, settings.BACKUP_S3_BUCKET, key)
    head = client.head_object(Bucket=settings.BACKUP_S3_BUCKET, Key=key)
    if int(head.get('ContentLength', -1)) != os.path.getsize(path):
        raise BackupError(f"Upload de {key} chegou com tamanho diferente do original.")
    return key


def cleanup_local(backup_dir, days):
    cutoff = datetime.now() - timedelta(days=days)
    removed = 0
    for name in os.listdir(backup_dir):
        if not name.startswith((DUMP_PREFIX, MEDIA_PREFIX)):
            continue
        full = os.path.join(backup_dir, name)
        if datetime.fromtimestamp(os.path.getmtime(full)) < cutoff:
            os.remove(full)
            removed += 1
    return removed


def cleanup_remote(days, min_keep):
    """Apaga do bucket backups mais antigos que `days`, sempre mantendo os `min_keep` mais recentes."""
    client = s3_client()
    objects = []
    paginator = client.get_paginator('list_objects_v2')
    for page in paginator.paginate(Bucket=settings.BACKUP_S3_BUCKET, Prefix=_prefix()):
        for obj in page.get('Contents', []):
            name = os.path.basename(obj['Key'])
            if name.startswith((DUMP_PREFIX, MEDIA_PREFIX)):
                objects.append(obj)
    objects.sort(key=lambda o: o['LastModified'], reverse=True)
    dumps_kept = 0
    cutoff = timezone.now() - timedelta(days=days)
    to_delete = []
    for obj in objects:
        is_dump = os.path.basename(obj['Key']).startswith(DUMP_PREFIX)
        if is_dump:
            dumps_kept += 1
        if obj['LastModified'] < cutoff and (not is_dump or dumps_kept > min_keep):
            to_delete.append({'Key': obj['Key']})
    for i in range(0, len(to_delete), 1000):
        client.delete_objects(Bucket=settings.BACKUP_S3_BUCKET, Delete={'Objects': to_delete[i:i + 1000]})
    return len(to_delete)


def send_alert(subject, body):
    from django.core.mail import mail_admins, send_mail
    try:
        if settings.BACKUP_ALERT_EMAIL:
            send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [settings.BACKUP_ALERT_EMAIL])
        else:
            mail_admins(subject, body)
    except Exception:
        logger.exception("Não foi possível enviar o alerta de backup.")


# ------------------------------------------------------------------ execução

def run_backup(trigger='beat'):
    from .models import BackupRun

    run = BackupRun.objects.create(trigger=trigger)
    backup_dir = settings.BACKUP_DIR
    notes = []
    created = []
    try:
        os.makedirs(backup_dir, exist_ok=True)
        stamp = timezone.localtime().strftime('%Y%m%d_%H%M%S')

        dump = dump_database(backup_dir, stamp)
        run.db_size_bytes = os.path.getsize(dump)
        to_send = [dump]
        if settings.BACKUP_INCLUDE_MEDIA:
            media = archive_media(backup_dir, stamp)
            created.append(media)
            run.media_size_bytes = os.path.getsize(media)
            to_send.append(media)

        if s3_enabled():
            passphrase = settings.BACKUP_ENCRYPTION_PASSPHRASE
            if passphrase:
                encrypted = []
                for path in to_send:
                    out = encrypt_file(path, passphrase)
                    created.append(out)
                    encrypted.append(out)
                to_send = encrypted
                run.encrypted = True
            else:
                notes.append("ATENÇÃO: cópia externa SEM criptografia (defina BACKUP_ENCRYPTION_PASSPHRASE).")
            run.remote_keys = [upload(p) for p in to_send]
            removed = cleanup_remote(settings.BACKUP_REMOTE_RETENTION_DAYS, settings.BACKUP_REMOTE_MIN_KEEP)
            if removed:
                notes.append(f"{removed} arquivo(s) antigo(s) removido(s) do bucket.")
            run.status = 'SUCCESS'
        else:
            notes.append("Cópia externa desligada (BACKUP_S3_BUCKET vazio): backup só no servidor.")
            run.status = 'LOCAL_ONLY'

        removed_local = cleanup_local(backup_dir, settings.BACKUP_RETENTION_DAYS)
        if removed_local:
            notes.append(f"{removed_local} backup(s) local(is) antigo(s) removido(s).")
    except Exception as exc:
        run.status = 'FAILED'
        notes.append(f"{type(exc).__name__}: {exc}")
        logger.exception("Backup falhou")
        send_alert("[StockPro] Backup FALHOU",
                   f"O backup de {timezone.localtime():%d/%m/%Y %H:%M} falhou.\n\n" + "\n".join(notes))
    finally:
        # Mídia e cópias criptografadas são temporárias; o dump .sql.gz fica no volume local
        for path in created:
            if os.path.exists(path):
                os.remove(path)
        run.message = "\n".join(notes)
        run.finished_at = timezone.now()
        run.save()
    return run


def verify_latest_remote(passphrase=None, key=None):
    """Baixa o último dump do bucket, descriptografa e confere a integridade. Retorna a chave verificada."""
    if not s3_enabled():
        raise BackupError("BACKUP_S3_BUCKET não configurado.")
    client = s3_client()
    if key is None:
        newest = None
        paginator = client.get_paginator('list_objects_v2')
        for page in paginator.paginate(Bucket=settings.BACKUP_S3_BUCKET, Prefix=_prefix()):
            for obj in page.get('Contents', []):
                if os.path.basename(obj['Key']).startswith(DUMP_PREFIX) and (
                        newest is None or obj['LastModified'] > newest['LastModified']):
                    newest = obj
        if newest is None:
            raise BackupError("Nenhum dump encontrado no bucket.")
        key = newest['Key']
    tmp = tempfile.mkdtemp(prefix='verify-')
    try:
        local = os.path.join(tmp, os.path.basename(key))
        client.download_file(settings.BACKUP_S3_BUCKET, key, local)
        if local.endswith('.gpg'):
            passphrase = passphrase or settings.BACKUP_ENCRYPTION_PASSPHRASE
            if not passphrase:
                raise BackupError("Backup criptografado: informe a senha (BACKUP_ENCRYPTION_PASSPHRASE).")
            local = decrypt_file(local, passphrase, local[:-4])
        verify_dump_gz(local)
        return key
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

