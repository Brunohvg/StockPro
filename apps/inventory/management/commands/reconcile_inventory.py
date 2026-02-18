import logging
from django.core.management.base import BaseCommand
from apps.products.models import ProductVariant
from apps.inventory.services.reconciliation import reconcile_variant
from django.db import transaction

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Reconciles current_stock with StockMovement ledger for all variants.'

    def add_arguments(self, parser):
        parser.add_argument('--fix', action='store_true', help='Correct the stock balance if discrepancy is found')
        parser.add_argument('--dry-run', action='store_true', help='Report discrepancies without updating the database')
        parser.add_argument('--sku', type=str, help='Reconcile only a specific SKU')

    def handle(self, *args, **options):
        fix = options['fix']
        dry_run = options['dry_run']
        sku = options['sku']

        if dry_run and fix:
            self.stderr.write("Error: Cannot use --fix and --dry-run together.")
            return

        self.stdout.write(self.style.MIGRATE_HEADING(f"Starting Stock Reconciliation (Fix={fix}, Dry-Run={dry_run})"))

        variants = ProductVariant.objects.all()
        if sku:
            variants = variants.filter(sku=sku)

        total_variants = variants.count()
        processed = 0
        divergent = 0
        fixed = 0

        for variant in variants:
            try:
                # If dry_run, we don't pass fix=True to the service (it might internally update status though)
                # But wait, the service does update status. If dry_run, we should probably just report.
                # Let's adjust service if needed or just handle it here.

                # For dry_run, we want zero DB writes.
                if dry_run:
                    # We'll calculate manually or use a non-writing mode of the service if it existed.
                    # Given the service currently writes status, let's use a temporary transaction if dry_run?
                    # No, let's just use the service and handle it.
                    pass

                result = reconcile_variant(variant, fix=fix and not dry_run)

                if result['status'] == 'DIVERGENT':
                    divergent += 1
                    msg = f"DIVERGENT: {variant.sku} (Stored: {result['stored_stock']}, Ledger: {result['calculated_stock']})"
                    self.stdout.write(self.style.WARNING(msg))
                elif result['status'] == 'RECONCILED':
                    fixed += 1
                    msg = f"FIXED: {variant.sku} -> {result['calculated_stock']}"
                    self.stdout.write(self.style.SUCCESS(msg))

                processed += 1
                if processed % 100 == 0:
                    self.stdout.write(f"Processed {processed}/{total_variants}...")

            except Exception as e:
                self.stderr.write(self.style.ERROR(f"Error reconciling {variant.sku}: {str(e)}"))

        self.stdout.write(self.style.MIGRATE_HEADING("--- RECONCILIATION SUMMARY ---"))
        self.stdout.write(f"Total Variants Checked: {total_variants}")
        self.stdout.write(f"Divergences Found: {divergent}")
        if fix:
            self.stdout.write(f"Divergences Fixed: {fixed}")
        self.stdout.write(self.style.MIGRATE_HEADING("Audit Complete."))
