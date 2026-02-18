"""
Migration: Adiciona sale_price em Product e ProductVariant.
Usado no relatório de CMV & Margem para calcular margem bruta por produto.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0012_productvariant_inventory_status'),
    ]

    operations = [
        migrations.AddField(
            model_name='product',
            name='sale_price',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text='Preço de venda praticado. Usado para calcular margem bruta.',
                max_digits=12,
                null=True,
                verbose_name='Preço de Venda',
            ),
        ),
        migrations.AddField(
            model_name='productvariant',
            name='sale_price',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text='Preço de venda da variação (sobrepõe o do produto pai).',
                max_digits=12,
                null=True,
                verbose_name='Preço de Venda',
            ),
        ),
    ]
