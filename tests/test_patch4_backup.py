"""Patch 4.2: backup conferido, criptografado e enviado ao bucket; exportações antigas limpas."""
import gzip
import os
import stat
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.tenants import backup as bk
from apps.tenants.models import BackupRun

FOOTER = b"--\n-- PostgreSQL database dump complete\n--\n"


class FakeS3:
    """Bucket em memória com a parte da API do boto3 que o backup usa."""

    def __init__(self):
        self.objects = {}

    def upload_file(self, path, bucket, key):
        with open(path, 'rb') as fh:
            self.objects[key] = {'Body': fh.read(), 'LastModified': timezone.now()}

    def head_object(self, Bucket, Key):
        return {'ContentLength': len(self.objects[Key]['Body'])}

    def download_file(self, bucket, key, path):
        with open(path, 'wb') as fh:
            fh.write(self.objects[key]['Body'])

    def get_paginator(self, name):
        store = self

        class P:
            def paginate(self, Bucket, Prefix):
                yield {'Contents': [{'Key': k, 'LastModified': v['LastModified']}
                                    for k, v in store.objects.items() if k.startswith(Prefix)]}
        return P()

    def delete_objects(self, Bucket, Delete):
        for obj in Delete['Objects']:
            self.objects.pop(obj['Key'], None)


@pytest.fixture
def env(settings, tmp_path, monkeypatch):
    settings.BACKUP_DIR = str(tmp_path / 'backups')
    settings.MEDIA_ROOT = str(tmp_path / 'media')
    os.makedirs(os.path.join(settings.MEDIA_ROOT, 'products'))
    os.makedirs(os.path.join(settings.MEDIA_ROOT, 'exports'))
    open(os.path.join(settings.MEDIA_ROOT, 'products', 'foto.jpg'), 'wb').write(b'img')
    open(os.path.join(settings.MEDIA_ROOT, 'exports', 'tmp.csv'), 'wb').write(b'x')
    settings.BACKUP_S3_BUCKET = 'bucket'
    settings.BACKUP_S3_PREFIX = 'stockpro/'
    settings.BACKUP_ENCRYPTION_PASSPHRASE = 'senha-de-teste-123-com-mais-caracteres'
    settings.BACKUP_INCLUDE_MEDIA = True
    settings.BACKUP_ALERT_EMAIL = 'ops@example.com'
    fake = FakeS3()
    monkeypatch.setattr(bk, 's3_client', lambda: fake)

    def fake_dump(backup_dir, stamp, db=None):
        path = os.path.join(backup_dir, f'{bk.DUMP_PREFIX}{stamp}.sql.gz')
        with gzip.open(path, 'wb') as fh:
            fh.write(b"CREATE TABLE x();\n" + FOOTER)
        return path
    monkeypatch.setattr(bk, 'dump_database', fake_dump)
    return fake


@pytest.mark.django_db
def test_backup_completo_criptografado_no_bucket(env):
    run = bk.run_backup(trigger='manual')
    assert run.status == 'SUCCESS', run.message
    assert run.encrypted
    keys = sorted(env.objects)
    assert len(keys) == 2 and all(k.endswith('.gpg') for k in keys)
    assert any('stockpro_db_' in k for k in keys) and any('stockpro_media_' in k for k in keys)
    # conteúdo no bucket não é legível sem a senha
    assert all(b'CREATE TABLE' not in v['Body'] for v in env.objects.values())
    # a verificação baixa, descriptografa e confere o rodapé
    assert 'stockpro_db_' in bk.verify_latest_remote()
    # mídia temporária e .gpg locais foram apagados; o dump local continua
    local = os.listdir(bk.settings.BACKUP_DIR)
    assert len(local) == 1 and local[0].endswith('.sql.gz')


@pytest.mark.django_db
def test_midia_ignora_exportacoes(env, settings, tmp_path):
    path = bk.archive_media(str(tmp_path), 'x')
    import tarfile
    names = tarfile.open(path).getnames()
    assert 'products/foto.jpg' in names and not any(n.startswith('exports') for n in names)


@pytest.mark.django_db
def test_senha_errada_nao_abre(env):
    bk.run_backup()
    with pytest.raises(bk.BackupError):
        bk.verify_latest_remote(passphrase='errada')


@pytest.mark.django_db
def test_sem_bucket_fica_local_only(env, settings):
    settings.BACKUP_S3_BUCKET = ''
    run = bk.run_backup()
    assert run.status == 'LOCAL_ONLY' and not env.objects


@pytest.mark.django_db
def test_falha_registra_e_alerta(env, monkeypatch, mailoutbox):
    def broken(*a, **k):
        raise bk.BackupError("pg_dump falhou: conexão recusada")
    monkeypatch.setattr(bk, 'dump_database', broken)
    run = bk.run_backup()
    assert run.status == 'FAILED' and 'conexão recusada' in run.message
    assert BackupRun.objects.get(pk=run.pk).finished_at is not None
    assert len(mailoutbox) == 1 and 'FALHOU' in mailoutbox[0].subject
    assert not env.objects


def test_dump_corrompido_e_rejeitado(tmp_path):
    bad = tmp_path / 'stockpro_db_x.sql.gz'
    with gzip.open(bad, 'wb') as fh:
        fh.write(b'CREATE TABLE x(); -- cortado no meio')
    with pytest.raises(bk.BackupError, match='incompleto'):
        bk.verify_dump_gz(str(bad))
    trunc = tmp_path / 'trunc.sql.gz'
    trunc.write_bytes(bad.read_bytes()[:20])
    with pytest.raises(bk.BackupError):
        bk.verify_dump_gz(str(trunc))


def test_dump_real_com_pg_dump_simulado(tmp_path, monkeypatch):
    """Exercita o pipeline pg_dump | gzip com um executável falso no PATH."""
    bindir = tmp_path / 'bin'
    bindir.mkdir()
    script = bindir / 'pg_dump'
    script.write_text("#!/bin/sh\necho 'CREATE TABLE t();'\necho '-- PostgreSQL database dump complete'\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv('PATH', f"{bindir}:{os.environ['PATH']}")
    db = {'ENGINE': 'django.db.backends.postgresql', 'HOST': 'h', 'PORT': 5432,
          'USER': 'u', 'NAME': 'n', 'PASSWORD': 'p'}
    path = bk.dump_database(str(tmp_path), 'x', db=db)
    bk.verify_dump_gz(path)

    script.write_text("#!/bin/sh\necho 'erro de auth' >&2\nexit 1\n")
    with pytest.raises(bk.BackupError, match='pg_dump falhou'):
        bk.dump_database(str(tmp_path), 'y', db=db)
    assert not (tmp_path / 'stockpro_db_y.sql.gz').exists()


@pytest.mark.django_db
def test_retencao_remota_mantem_minimo(env, settings):
    old = timezone.now() - timedelta(days=60)
    for i in range(10):
        env.objects[f'stockpro/2026/01/stockpro_db_{i:02d}.sql.gz.gpg'] = {
            'Body': b'x', 'LastModified': old + timedelta(minutes=i)}
    env.objects['stockpro/outra-coisa.txt'] = {'Body': b'x', 'LastModified': old}
    settings.BACKUP_REMOTE_MIN_KEEP = 7
    removed = bk.cleanup_remote(days=30, min_keep=7)
    assert removed == 3
    assert 'stockpro/outra-coisa.txt' in env.objects  # só mexe em arquivos de backup


@pytest.mark.django_db
def test_limpeza_de_exportacoes(settings, tmp_path):
    from django.core.files.base import ContentFile
    from apps.inventory.models import ExportBatch
    from apps.tenants.backup_task import cleanup_old_exports
    from tests.factories import TenantFactory, UserFactory
    settings.MEDIA_ROOT = str(tmp_path)
    t, u = TenantFactory(), UserFactory()
    sistema = ExportBatch.objects.create(tenant=t, user=None)
    sistema.file.save('a.csv', ContentFile(b'x'))
    recente = ExportBatch.objects.create(tenant=t, user=u)
    antiga = ExportBatch.objects.create(tenant=t, user=u)
    ExportBatch.objects.filter(pk=sistema.pk).update(created_at=timezone.now() - timedelta(days=2))
    ExportBatch.objects.filter(pk=antiga.pk).update(created_at=timezone.now() - timedelta(days=40))
    cleanup_old_exports()
    assert list(ExportBatch.objects.values_list('pk', flat=True)) == [recente.pk]
    assert not os.path.exists(os.path.join(tmp_path, 'exports', 'a.csv'))

