from django.db import migrations

def migrate_to_variants(apps, schema_editor):
    Product = apps.get_model('products', 'Product')
    ProductVariant = apps.get_model('products', 'ProductVariant')
    StockMovement = apps.get_model('inventory', 'StockMovement')

    for product in Product.objects.all():
        # Para cada produto, garantimos que existe ao menos uma variante
        # Se for SIMPLE, ele deve ter exatamente uma. Se for VARIABLE, já deve ter.
        variant = product.variants.first()

        if not variant:
            # Se não tem variante, cria a variante padrão baseada nos dados do produto
            sku = product.sku
            if not sku:
                sku = f"MIG-{product.id}"

            variant = ProductVariant.objects.create(
                product=product,
                tenant=product.tenant,
                sku=sku,
                name="Geral",
                barcode=product.barcode,
                current_stock=product.current_stock or 0,
                minimum_stock=product.minimum_stock or 0,
                avg_unit_cost=product.avg_unit_cost,
                is_active=product.is_active
            )

        # Vincula todas as movimentações órfãs (que só tinham o product_id) à variante encontrada/criada
        StockMovement.objects.filter(product=product, variant__isnull=True).update(variant=variant)

def reverse_migrate(apps, schema_editor):
    # Opcional: Reverter não é estritamente necessário para este caso, mas boa prática
    pass

class Migration(migrations.Migration):
    dependencies = [
        ('products', '0007_alter_product_avg_unit_cost_alter_product_barcode_and_more'),
        ('inventory', '0014_alter_stockmovement_product_and_more'),
    ]

    operations = [
        migrations.RunPython(migrate_to_variants, reverse_migrate),
    ]
