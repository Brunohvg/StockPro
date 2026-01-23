# Generated manually for StockPro V2

import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """
    Migração inicial do app Partners.

    Cria:
    - Supplier (Fornecedores)
    - SupplierProductMap (Mapeamento de Produtos)
    """

    initial = True

    dependencies = [
        ('tenants', '0001_initial'),
        ('products', '0001_initial'),
    ]

    operations = [
        # =================================================================
        # 1. SUPPLIER (Fornecedores)
        # =================================================================
        migrations.CreateModel(
            name='Supplier',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('cnpj', models.CharField(
                    help_text='CNPJ do fornecedor (com ou sem formatação)',
                    max_length=18,
                    verbose_name='CNPJ'
                )),
                ('company_name', models.CharField(max_length=200, verbose_name='Razão Social')),
                ('trade_name', models.CharField(blank=True, max_length=200, verbose_name='Nome Fantasia')),
                ('state_registration', models.CharField(blank=True, max_length=20, verbose_name='Inscrição Estadual')),
                ('email', models.EmailField(blank=True, max_length=254, verbose_name='E-mail')),
                ('phone', models.CharField(blank=True, max_length=20, verbose_name='Telefone')),
                ('contact_name', models.CharField(blank=True, max_length=100, verbose_name='Nome do Contato')),
                ('payment_terms', models.CharField(
                    blank=True,
                    help_text='Ex: 30/60/90 DDL, À vista, etc.',
                    max_length=100,
                    verbose_name='Condições de Pagamento'
                )),
                ('lead_time_days', models.PositiveIntegerField(
                    default=7,
                    help_text='Prazo médio em dias úteis',
                    verbose_name='Prazo de Entrega (dias)'
                )),
                ('minimum_order', models.DecimalField(
                    blank=True,
                    decimal_places=2,
                    max_digits=12,
                    null=True,
                    verbose_name='Pedido Mínimo (R$)'
                )),
                ('address', models.TextField(blank=True, verbose_name='Endereço')),
                ('city', models.CharField(blank=True, max_length=100, verbose_name='Cidade')),
                ('state', models.CharField(
                    blank=True,
                    max_length=2,
                    validators=[django.core.validators.RegexValidator('^[A-Z]{2}$', 'UF deve ter 2 letras maiúsculas')],
                    verbose_name='UF'
                )),
                ('zip_code', models.CharField(blank=True, max_length=9, verbose_name='CEP')),
                ('notes', models.TextField(blank=True, verbose_name='Observações')),
                ('is_active', models.BooleanField(default=True, verbose_name='Ativo')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('tenant', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    to='tenants.tenant',
                    verbose_name='Tenant'
                )),
            ],
            options={
                'verbose_name': 'Fornecedor',
                'verbose_name_plural': 'Fornecedores',
                'ordering': ['trade_name', 'company_name'],
                'unique_together': {('tenant', 'cnpj')},
            },
        ),
        migrations.AddIndex(
            model_name='supplier',
            index=models.Index(fields=['tenant', 'cnpj'], name='partners_supplier_cnpj_idx'),
        ),
        migrations.AddIndex(
            model_name='supplier',
            index=models.Index(fields=['tenant', 'is_active'], name='partners_supplier_active_idx'),
        ),

        # =================================================================
        # 2. SUPPLIER PRODUCT MAP (Mapeamento de Produtos)
        # =================================================================
        migrations.CreateModel(
            name='SupplierProductMap',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('supplier_sku', models.CharField(
                    help_text='cProd da NF-e',
                    max_length=60,
                    verbose_name='Código do Fornecedor'
                )),
                ('supplier_ean', models.CharField(
                    blank=True,
                    help_text='cEAN da NF-e (pode diferir do código interno)',
                    max_length=14,
                    verbose_name='EAN do Fornecedor'
                )),
                ('supplier_name', models.CharField(
                    blank=True,
                    help_text='xProd da NF-e',
                    max_length=120,
                    verbose_name='Descrição do Fornecedor'
                )),
                ('last_cost', models.DecimalField(
                    blank=True,
                    decimal_places=4,
                    max_digits=12,
                    null=True,
                    verbose_name='Último Custo'
                )),
                ('last_purchase', models.DateField(blank=True, null=True, verbose_name='Última Compra')),
                ('total_purchased', models.PositiveIntegerField(
                    default=0,
                    help_text='Quantidade total já comprada deste fornecedor',
                    verbose_name='Total Comprado'
                )),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('product', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='supplier_mappings',
                    to='products.product',
                    verbose_name='Produto'
                )),
                ('supplier', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='product_mappings',
                    to='partners.supplier',
                    verbose_name='Fornecedor'
                )),
                ('tenant', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    to='tenants.tenant',
                    verbose_name='Tenant'
                )),
                ('variant', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='supplier_mappings',
                    to='products.productvariant',
                    verbose_name='Variação'
                )),
            ],
            options={
                'verbose_name': 'Mapeamento de Produto',
                'verbose_name_plural': 'Mapeamentos de Produtos',
                'ordering': ['-last_purchase', 'supplier_name'],
                'unique_together': {('tenant', 'supplier', 'supplier_sku')},
            },
        ),
        migrations.AddIndex(
            model_name='supplierproductmap',
            index=models.Index(fields=['tenant', 'supplier', 'supplier_sku'], name='partners_map_sku_idx'),
        ),
        migrations.AddIndex(
            model_name='supplierproductmap',
            index=models.Index(fields=['tenant', 'supplier_ean'], name='partners_map_ean_idx'),
        ),
    ]
