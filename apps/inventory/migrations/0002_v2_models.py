# Generated manually for StockPro V2

import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    """
    Migração V2 do app Inventory.
    
    Cria apenas os NOVOS modelos:
    - Location (Multi-localização)
    - AdjustmentReason (Motivos de ajuste)
    - PendingAssociation (Itens pendentes de associação)
    
    NÃO altera StockMovement ou ImportBatch existentes.
    """

    dependencies = [
        ('inventory', '0001_initial'),
        ('partners', '0001_initial'),
        ('products', '0001_initial'),
        ('tenants', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # =================================================================
        # 1. LOCATION (Multi-Localização)
        # =================================================================
        migrations.CreateModel(
            name='Location',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.CharField(help_text='Código único do local (ex: LOJ-001)', max_length=20, verbose_name='Código')),
                ('name', models.CharField(max_length=100, verbose_name='Nome')),
                ('location_type', models.CharField(
                    choices=[
                        ('STORE', 'Loja'),
                        ('WAREHOUSE', 'Depósito'),
                        ('SHELF', 'Prateleira'),
                        ('DISPLAY', 'Expositor'),
                        ('TRANSIT', 'Em Trânsito'),
                        ('QUARANTINE', 'Quarentena'),
                    ],
                    default='STORE',
                    max_length=20,
                    verbose_name='Tipo'
                )),
                ('address', models.TextField(blank=True, verbose_name='Endereço')),
                ('is_active', models.BooleanField(default=True, verbose_name='Ativo')),
                ('is_default', models.BooleanField(default=False, help_text='Local padrão para recebimento de mercadorias', verbose_name='Local Padrão')),
                ('allows_negative', models.BooleanField(default=False, help_text='Permite estoque negativo (ex: consignação)', verbose_name='Permite Negativo')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('parent', models.ForeignKey(
                    blank=True,
                    help_text='Para organização hierárquica',
                    null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='children',
                    to='inventory.location',
                    verbose_name='Local Pai'
                )),
                ('tenant', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    to='tenants.tenant',
                    verbose_name='Tenant'
                )),
            ],
            options={
                'verbose_name': 'Localização',
                'verbose_name_plural': 'Localizações',
                'ordering': ['name'],
                'unique_together': {('tenant', 'code')},
            },
        ),
        migrations.AddIndex(
            model_name='location',
            index=models.Index(fields=['tenant', 'code'], name='inv_loc_tenant_code_idx'),
        ),
        migrations.AddIndex(
            model_name='location',
            index=models.Index(fields=['tenant', 'is_active', 'is_default'], name='inv_loc_tenant_active_idx'),
        ),

        # =================================================================
        # 2. ADJUSTMENT REASON (Motivos de Ajuste)
        # =================================================================
        migrations.CreateModel(
            name='AdjustmentReason',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.CharField(max_length=20, verbose_name='Código')),
                ('name', models.CharField(max_length=100, verbose_name='Nome')),
                ('description', models.TextField(blank=True, verbose_name='Descrição')),
                ('impact_type', models.CharField(
                    choices=[
                        ('LOSS', 'Perda'),
                        ('GAIN', 'Ganho'),
                        ('NEUTRAL', 'Neutro'),
                    ],
                    default='NEUTRAL',
                    max_length=10,
                    verbose_name='Tipo de Impacto'
                )),
                ('requires_note', models.BooleanField(default=False, help_text='Obriga preenchimento de observação no ajuste', verbose_name='Exige Observação')),
                ('is_active', models.BooleanField(default=True, verbose_name='Ativo')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('tenant', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    to='tenants.tenant',
                    verbose_name='Tenant'
                )),
            ],
            options={
                'verbose_name': 'Motivo de Ajuste',
                'verbose_name_plural': 'Motivos de Ajuste',
                'ordering': ['name'],
                'unique_together': {('tenant', 'code')},
            },
        ),

        # =================================================================
        # 3. PENDING ASSOCIATION (Itens Pendentes de Associação)
        # =================================================================
        migrations.CreateModel(
            name='PendingAssociation',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('nfe_key', models.CharField(max_length=44)),
                ('nfe_number', models.CharField(max_length=20)),
                ('item_number', models.PositiveIntegerField(verbose_name='nItem')),
                ('supplier_sku', models.CharField(max_length=60, verbose_name='Código Fornecedor (cProd)')),
                ('supplier_ean', models.CharField(blank=True, max_length=14, verbose_name='EAN (cEAN)')),
                ('supplier_name', models.CharField(max_length=120, verbose_name='Descrição (xProd)')),
                ('ncm', models.CharField(blank=True, max_length=8)),
                ('cfop', models.CharField(blank=True, max_length=4)),
                ('unit', models.CharField(max_length=10, verbose_name='Unidade (uCom)')),
                ('quantity', models.DecimalField(decimal_places=4, max_digits=15, verbose_name='Quantidade')),
                ('unit_cost', models.DecimalField(decimal_places=4, max_digits=15, verbose_name='Custo Unitário')),
                ('total_cost', models.DecimalField(decimal_places=2, max_digits=15, verbose_name='Custo Total')),
                ('status', models.CharField(
                    choices=[
                        ('PENDING', 'Aguardando'),
                        ('LINKED', 'Vinculado a Existente'),
                        ('CREATED', 'Produto Criado'),
                        ('IGNORED', 'Ignorado'),
                    ],
                    default='PENDING',
                    max_length=20
                )),
                ('match_suggestions', models.JSONField(blank=True, default=list, help_text='Lista de produtos similares encontrados')),
                ('match_score', models.FloatField(default=0, help_text='Score do melhor match encontrado (0-1)')),
                ('resolved_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('import_batch', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='pending_associations',
                    to='inventory.importbatch'
                )),
                ('resolved_by', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='resolved_associations',
                    to=settings.AUTH_USER_MODEL
                )),
                ('resolved_product', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='resolved_associations',
                    to='products.product'
                )),
                ('resolved_variant', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='resolved_associations',
                    to='products.productvariant'
                )),
                ('supplier', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='pending_associations',
                    to='partners.supplier'
                )),
                ('tenant', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    to='tenants.tenant',
                    verbose_name='Tenant'
                )),
            ],
            options={
                'verbose_name': 'Associação Pendente',
                'verbose_name_plural': 'Associações Pendentes',
                'ordering': ['-created_at'],
                'unique_together': {('import_batch', 'item_number')},
            },
        ),
    ]
