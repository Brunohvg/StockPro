from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('inventory', '0005_nfe_variacoes')]

    operations = [
        migrations.AddField(
            model_name='externalorder',
            name='consumption_hash',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
        migrations.AddField(
            model_name='externalorder',
            name='consumption_response',
            field=models.JSONField(blank=True, null=True),
        ),
    ]
