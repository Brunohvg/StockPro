from django.db import migrations


class Migration(migrations.Migration):
    """
    Merge das duas migrations 0013 que conflitavam.
    Resolve o conflito sem perda de dados.
    """

    dependencies = [
        ('products', '0013_productvariant_sale_price'),
    ]

    operations = []
