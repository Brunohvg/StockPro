from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0012_productvariant_inventory_status'),
    ]

    operations = [
        migrations.AddField(
            model_name='productvariant',
            name='sale_price',
            field=models.DecimalField(
                blank=True, decimal_places=2, max_digits=12,
                null=True, verbose_name='Preço de Venda'
            ),
        ),
        migrations.AddField(
            model_name='product',
            name='sale_price',
            field=models.DecimalField(
                blank=True, decimal_places=2, max_digits=12,
                null=True, verbose_name='Preço de Venda'
            ),
        ),
    ]
