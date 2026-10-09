from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Executa o backup agora (dump + mídia + envio ao bucket, se configurado)."

    def handle(self, *args, **options):
        from apps.tenants.backup import run_backup
        run = run_backup(trigger='manual')
        self.stdout.write(f"Status: {run.get_status_display()}")
        self.stdout.write(f"Dump: {run.db_size_bytes // 1024} KB | Mídia: {run.media_size_bytes // 1024} KB"
                          f" | Criptografado: {'sim' if run.encrypted else 'não'}")
        for key in run.remote_keys:
            self.stdout.write(f"Enviado: {key}")
        if run.message:
            self.stdout.write(run.message)
        if run.status == 'FAILED':
            raise CommandError("Backup falhou.")

