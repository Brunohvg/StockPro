from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import StockMovement

@receiver(post_save, sender=StockMovement)
def update_stock_cache(sender, instance, created, **kwargs):
    """
    Update Product/Variant current_stock cache after a movement is recorded.
    This ensures the 'current_stock' field is always a reflection of the ledger.
    """
    if not created:
        return # Movements are immutable, we only care about new ones

    target = instance.variant or instance.product
    if not target:
        return

    # Use the special flag to bypass the lockdown
    target._allow_stock_change = True

    # We don't calculate here (StockService already did),
    # we just trust the balance_after from the movement/ledger.
    target.current_stock = instance.balance_after
    target.save(update_fields=['current_stock'])
