from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Baixa o último dump do bucket, descriptografa e confere se está íntegro."

    def add_arguments(self, parser):
        parser.add_argument('--key', help="Chave específica no bucket (padrão: o dump mais recente).")

    def handle(self, *args, **options):
        from apps.tenants.backup import BackupError, verify_latest_remote
        try:
            key = verify_latest_remote(key=options.get('key'))
        except BackupError as exc:
            raise CommandError(str(exc))
        self.stdout.write(self.style.SUCCESS(f"OK: {key} está íntegro e completo."))

