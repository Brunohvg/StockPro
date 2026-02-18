import logging
from django.db import transaction
from django.db.models import Sum
from apps.inventory.models import StockMovement

logger = logging.getLogger(__name__)

def reconcile_variant(variant, fix=False):
    """
    Reconciles a variant's current_stock with its StockMovement history.

    Formula: current_stock == SUM(IN) - SUM(OUT) +/- SUM(ADJ)

    Returns a dict with reconciliation details.
    """
    ledger = StockMovement.objects.filter(variant=variant)

    # Calculate totals
    in_sum = ledger.filter(type='IN').aggregate(total=Sum('quantity'))['total'] or 0
    out_sum = ledger.filter(type='OUT').aggregate(total=Sum('quantity'))['total'] or 0
    adj_sum = ledger.filter(type='ADJ').aggregate(total=Sum('quantity'))['total'] or 0

    # Mathematical balance based on ledger
    calculated_stock = in_sum - out_sum + adj_sum
    stored_stock = variant.current_stock

    discrepancy = calculated_stock - stored_stock

    status = 'OK'
    if discrepancy != 0:
        status = 'DIVERGENT'

    result = {
        'variant_id': variant.id,
        'sku': variant.sku,
        'calculated_stock': float(calculated_stock),
        'stored_stock': float(stored_stock),
        'discrepancy': float(discrepancy),
        'status': status
    }

    if fix and discrepancy != 0:
        with transaction.atomic():
            # Allow stock change to bypass the model-level protection if needed
            variant._allow_stock_change = True
            variant.current_stock = calculated_stock
            variant.inventory_status = 'RECONCILED'
            variant.save(update_fields=['current_stock', 'inventory_status'])

            logger.info(f"FIXED Variant {variant.sku}: Store {stored_stock} -> Calc {calculated_stock}")
            result['status'] = 'RECONCILED'
    elif not fix and discrepancy != 0:
        variant.inventory_status = 'DIVERGENT'
        variant.save(update_fields=['inventory_status'])
    else:
        variant.inventory_status = 'OK'
        variant.save(update_fields=['inventory_status'])

    return result
