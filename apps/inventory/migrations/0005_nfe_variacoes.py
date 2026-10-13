from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('inventory', '0004_nfe_entrada')]
    operations = [
        migrations.AddField(model_name='nfeitem', name='new_parent_sku', field=models.CharField(max_length=50, blank=True)),
        migrations.AddField(model_name='nfeitem', name='new_parent_name', field=models.CharField(max_length=255, blank=True)),
        migrations.AddField(model_name='nfeitem', name='new_attributes', field=models.CharField(max_length=255, blank=True)),
    ]
