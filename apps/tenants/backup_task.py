"""
Backup diário automático do StockPro.
- Dump PostgreSQL comprimido (pg_dump + gzip)
- Export CSV de Produtos e Movimentações por tenant ativo
- Limpeza automática de backups com mais de 30 dias
Agendado via CELERY_BEAT_SCHEDULE no settings.py (03:30 todos os dias).
"""
import logging
import os
import subprocess
from datetime import datetime, timedelta

from celery import shared_task
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task
def daily_backup():
    """
    Executa backup completo:
    1. pg_dump comprimido do banco
    2. Export CSV por tenant (produtos + movimentações)
    3. Remove backups com mais de 30 dias
    """
    now = datetime.now().strftime('%Y%m%d_%H%M')
    backup_dir = getattr(settings, 'BACKUP_DIR', '/data/backups')
    os.makedirs(backup_dir, exist_ok=True)

    results = []

    # ------------------------------------------------------------------
    # 1. Dump PostgreSQL
    # ------------------------------------------------------------------
    db = settings.DATABASES.get('default', {})
    db_host = db.get('HOST', '')
    db_name = db.get('NAME', '')
    db_user = db.get('USER', '')
    db_pass = db.get('PASSWORD', '')
    db_port = db.get('PORT', '5432')

    if db_host and db_name:
        dump_path = os.path.join(backup_dir, f'stockpro_db_{now}.sql.gz')
        try:
            env = {**os.environ, 'PGPASSWORD': db_pass}
            pg_cmd = [
                'pg_dump',
                '-h', db_host,
                '-p', str(db_port),
                '-U', db_user,
                '-d', db_name,
                '--no-password',
            ]
            with open(dump_path, 'wb') as f:
                p1 = subprocess.Popen(pg_cmd, stdout=subprocess.PIPE, env=env,
                                      stderr=subprocess.PIPE)
                p2 = subprocess.Popen(['gzip'], stdin=p1.stdout, stdout=f,
                                      stderr=subprocess.PIPE)
                p1.stdout.close()
                _, gzip_err = p2.communicate()
                _, pg_err = p1.communicate()

            if p1.returncode == 0 and p2.returncode == 0:
                size_kb = os.path.getsize(dump_path) // 1024
                results.append(f"DB dump OK: {dump_path} ({size_kb}KB)")
                logger.info(f"Backup DB gerado: {dump_path} ({size_kb}KB)")
            else:
                os.remove(dump_path)
                err_msg = pg_err.decode('utf-8', errors='replace')[:200]
                results.append(f"DB dump ERRO: {err_msg}")
                logger.error(f"pg_dump falhou: {err_msg}")

        except FileNotFoundError:
            results.append("pg_dump não encontrado no container. Instale postgresql-client.")
            logger.warning("pg_dump não encontrado - backup de DB pulado.")
        except Exception as e:
            results.append(f"DB dump exceção: {e}")
            logger.error(f"Erro no backup DB: {e}")
    else:
        results.append("DB dump pulado: DATABASE não configurado.")

    # ------------------------------------------------------------------
    # 2. Export CSV por tenant
    # ------------------------------------------------------------------
    try:
        from apps.tenants.models import Tenant
        from apps.inventory.models import ExportBatch

        active_tenants = Tenant.objects.filter(is_active=True)
        export_count = 0

        for tenant in active_tenants:
            for resource in ['PRODUCTS', 'MOVEMENTS']:
                try:
                    import json
                    params = json.dumps({'variants': True, 'inactive': False, 'days': 1})
                    batch = ExportBatch.objects.create(
                        tenant=tenant,
                        export_type='CSV',
                        resource=resource,
                        params=params,
                        user=None,
                    )
                    from apps.inventory.tasks import process_export_catalog
                    process_export_catalog.delay(str(batch.id))
                    export_count += 1
                except Exception as e:
                    logger.error(f"Erro export {resource} tenant {tenant.id}: {e}")

        results.append(f"CSV exports agendados: {export_count} (para {active_tenants.count()} tenants)")

    except Exception as e:
        results.append(f"CSV export exceção: {e}")
        logger.error(f"Erro no export por tenant: {e}")

    # ------------------------------------------------------------------
    # 3. Limpeza de backups antigos (> 30 dias)
    # ------------------------------------------------------------------
    try:
        retention_days = getattr(settings, 'BACKUP_RETENTION_DAYS', 30)
        cutoff = datetime.now() - timedelta(days=retention_days)
        removed = 0

        for filename in os.listdir(backup_dir):
            if not filename.startswith('stockpro_db_'):
                continue
            filepath = os.path.join(backup_dir, filename)
            file_mtime = datetime.fromtimestamp(os.path.getmtime(filepath))
            if file_mtime < cutoff:
                os.remove(filepath)
                removed += 1

        if removed:
            results.append(f"Limpeza: {removed} backup(s) removido(s) (>{retention_days} dias)")
            logger.info(f"Backup cleanup: {removed} arquivo(s) removido(s)")

    except Exception as e:
        results.append(f"Limpeza exceção: {e}")
        logger.error(f"Erro na limpeza de backups: {e}")

    summary = f"Backup {now}: " + " | ".join(results)
    logger.info(summary)
    return summary
