"""
Enhanced Celery Tasks for Import Processing (V10)
- Supports product types (SIMPLE/VARIABLE)
- Handles variants with attributes
- Idempotency via ImportLog
- Retry with exponential backoff
"""
import hashlib
import uuid
import xml.etree.ElementTree as ET
from decimal import Decimal

import pandas as pd
from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from django.db import models, transaction

from apps.core.services import StockService
from apps.products.models import Brand, Category

from .models import ExportBatch, ImportBatch, ImportLog


def parse_decimal_br(value) -> 'Decimal | None':
    """
    Converte string decimal em formato BR ou internacional para Decimal.
    Suporta: '1.250,00' -> 1250.00 | '1250.00' -> 1250.00 | '1250,00' -> 1250.00
    Retorna None se inválido.
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s or s.lower() == 'nan':
        return None
    # Formato BR com milhar: 1.250,00
    if ',' in s and '.' in s:
        s = s.replace('.', '').replace(',', '.')
    # Formato BR sem milhar: 1250,00
    elif ',' in s:
        s = s.replace(',', '.')
    # Formato internacional: 1250.00 - já ok
    try:
        return Decimal(s)
    except Exception:
        return None


def generate_idempotency_key(batch_id, file_content):
    """Generate unique key for idempotency checking"""
    content_hash = hashlib.md5(file_content).hexdigest()[:16]
    return f"import_{batch_id}_{content_hash}"


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def process_import_task(self, batch_id, idempotency_key=None):
    """Process import with idempotency and retry support"""
    try:
        batch = ImportBatch.objects.get(id=batch_id)

        # Generate idempotency key if not provided
        if not idempotency_key:
            with open(batch.file.path, 'rb') as f:
                idempotency_key = generate_idempotency_key(batch_id, f.read())

        # Check if already processed successfully
        existing_log = ImportLog.objects.filter(idempotency_key=idempotency_key, status='SUCCESS').first()
        if existing_log:
            batch.status = 'COMPLETED'
            batch.log = f"Já processado com sucesso anteriormente em {existing_log.created_at}"
            batch.save()
            return f"Idempotent skip: {idempotency_key}"

        batch.status = 'PROCESSING'
        batch.save()

        if batch.type in ['CATALOG_DIRECT', 'CSV_PRODUCTS']:
            result = process_csv_catalog_direct(batch)
        elif batch.type in ['STOCK_SYNC', 'CSV_INVENTORY']:
            result = process_csv_stock_adjustment(batch)
        else:
            result = "Tipo de importação descontinuado (NF-e/Legado)."

        batch.status = 'COMPLETED'
        batch.log = result
        batch.save()

        # Log successful processing for idempotency
        ImportLog.objects.create(
            batch=batch,
            row_number=0,
            idempotency_key=idempotency_key,
            status='ERROR' if ("Erro crítico" in result) else 'SUCCESS',
            message=result
        )

    except SoftTimeLimitExceeded:
        if 'batch' in locals():
            batch.status = 'PARTIAL'
            batch.log = "Timeout - processamento parcial. Tente dividir o arquivo."
            batch.save()
        raise
    except Exception as e:
        if 'batch' in locals():
            batch.status = 'ERROR'
            batch.log = f"Falha crítica no worker: {str(e)}"
            batch.save()
        raise


def process_csv_stock_adjustment(batch):
    """
    Strict Stock Adjustment via CSV (V10 Hardy).
    Format: sku, name, quantity, avg_unit_cost
    - Match ONLY by SKU
    - Never create products
    - Name used for logging only
    - Atomic transaction
    """
    tenant = batch.tenant
    try:
        df = pd.read_csv(batch.file.path)
    except Exception as e:
        return f"Erro ao ler CSV: {e}"

    # Normalize columns
    df.columns = [c.strip().lower() for c in df.columns]

    # Required columns: sku, quantity
    if 'sku' not in df.columns or 'quantity' not in df.columns:
        return "Erro: Colunas 'sku' e 'quantity' são obrigatórias no CSV de inventário."

    batch.total_rows = len(df)
    batch.save()

    from apps.products.models import ProductVariant

    success_count = 0
    error_count = 0
    log_entries = []

    try:
        with transaction.atomic():
            for index, row in df.iterrows():
                sku = str(row.get('sku', '')).strip()
                name_visual = str(row.get('name', '')).strip()
                qty_raw = row.get('quantity', 0)
                cost_raw = row.get('avg_unit_cost')

                if not sku:
                    log_entries.append(f"Linha {index+1}: SKU ignorado (vazio).")
                    error_count += 1
                    continue

                try:
                    qty = Decimal(str(qty_raw))
                except:
                    log_entries.append(f"Linha {index+1} (SKU {sku}): Quantidade inválida '{qty_raw}'.")
                    error_count += 1
                    continue

                # STRICT MATCHING: ONLY SKU + TENANT
                variant = ProductVariant.objects.filter(tenant=tenant, sku=sku).first()

                if not variant:
                    log_entries.append(f"Linha {index+1}: SKU '{sku}' ('{name_visual}') não encontrado no sistema.")
                    error_count += 1
                    continue

                # GENERATE STOCK MOVEMENT (NEVER UPDATE DIRECTLY)
                try:
                    unit_cost = Decimal(str(cost_raw)) if pd.notna(cost_raw) and cost_raw else None
                except:
                    unit_cost = None

                StockService.create_movement(
                    tenant=tenant,
                    user=batch.user,
                    variant=variant,
                    movement_type='IN' if qty >= 0 else 'OUT',
                    quantity=abs(qty),
                    reason=f"Ajuste via CSV Inventário (Ref: {name_visual})",
                    unit_cost=unit_cost
                )

                success_count += 1
                batch.processed_rows = index + 1
                if index % 10 == 0:
                    batch.save()

        summary = f"Processamento concluído. Sucessos: {success_count}. Erros: {error_count}."
        if log_entries:
            summary += "\nDetalhes:\n" + "\n".join(log_entries[:20])
            if len(log_entries) > 20:
                summary += "\n... (e mais erros)"
        return summary

    except Exception as e:
        return f"Erro crítico durante transação: {e}"


def process_csv_catalog_direct(batch):
    """
    Direct Catalog Import (Criação/Update Blindado).
    Campos: sku, name, category, brand, barcode, unit, avg_unit_cost, stock
    - SKU é a chave única.
    - Se existe variant, dá UPDATE.
    - Se não existe, dá CREATE (Product + Variant).
    - Estoque via ADJ (Saldo Absoluto).
    - Atômico.
    """
    tenant = batch.tenant
    try:
        df = pd.read_csv(batch.file.path)
    except Exception as e:
        return f"Erro ao ler CSV: {e}"

    # Normalização de colunas
    df.columns = [c.strip().lower() for c in df.columns]

    # Mapeamento de colunas flexível por apelidos (aliases)
    mapping = {
        'sku': ['sku', 'codigo', 'cod', 'id'],
        'name': ['name', 'nome', 'descricao', 'description', 'titulo'],
        'category': ['category', 'categoria', 'cat'],
        'brand': ['brand', 'marca'],
        'barcode': ['barcode', 'cod_barras', 'codigo_barras', 'ean', 'gtin'],
        'unit': ['unit', 'unidade', 'uom'],
        'cost': ['cost', 'avg_unit_cost', 'custo', 'custo_medio', 'preço_custo'],
        'stock': ['stock', 'estoque', 'estoque_atual', 'saldo', 'quantidade', 'qty'],
        'supplier': ['supplier', 'fornecedor', 'forn'],
        'location': ['location', 'local', 'deposito', 'armazem'],
        'cnpj': ['cnpj', 'document', 'cpf_cnpj'],
        'sku_pai': ['sku_pai', 'parent_sku', 'pai', 'sku_mestre', 'master_sku'],
        'attributes': ['attributes', 'atributos', 'caracteristicas', 'specs']
    }

    def get_val(row, target):
        for alias in mapping.get(target, []):
            if alias in df.columns and pd.notna(row.get(alias)):
                return str(row.get(alias)).strip()
        return None

    batch.total_rows = len(df)
    batch.save()

    from apps.products.models import Brand, Category, Product, ProductType, ProductVariant

    success_count = 0
    error_count = 0
    log_entries = []

    try:
        with transaction.atomic():
            for index, row in df.iterrows():
                sku = get_val(row, 'sku')
                name = get_val(row, 'name')
                sku_pai = get_val(row, 'sku_pai')
                attrs_raw = get_val(row, 'attributes')

                if not sku or not name:
                    log_entries.append(f"Linha {index+1}: SKU ou Nome ausentes. Ignorado.")
                    error_count += 1
                    continue

                # 1. BUSCA EXISTENTE
                variant = ProductVariant.objects.filter(tenant=tenant, sku=sku).first()
                is_update = bool(variant)

                # 2. RESOLVE CATEGORIA E MARCA
                cat_name = get_val(row, 'category')
                cat_obj = None
                if cat_name:
                    c_name = cat_name.strip()
                    # Tenta encontrar ignorando maiúsculas/minúsculas (evita duplicatas)
                    cat_obj = Category.objects.filter(tenant=tenant, name__iexact=c_name).first()
                    if not cat_obj:
                        # Se não existir, cria padronizado como Título (Ex: "nike" -> "Nike")
                        cat_obj = Category.objects.create(tenant=tenant, name=c_name.title()[:100])

                brand_name = get_val(row, 'brand')
                brand_obj = None
                if brand_name:
                    b_name = brand_name.strip()
                    # Tenta encontrar ignorando maiúsculas/minúsculas
                    brand_obj = Brand.objects.filter(tenant=tenant, name__iexact=b_name).first()
                    if not brand_obj:
                        # Se não existir, cria padronizado
                        brand_obj = Brand.objects.create(tenant=tenant, name=b_name.title()[:100])

                # 2.1 RESOLVE FORNECEDOR E LOCAL
                supplier_name = get_val(row, 'supplier')
                supplier_cnpj = get_val(row, 'cnpj')
                supplier_obj = None

                from apps.partners.models import Supplier
                if supplier_cnpj:
                    cnpj_clean = "".join(filter(str.isdigit, supplier_cnpj))
                    supplier_obj = Supplier.objects.filter(tenant=tenant, cnpj=cnpj_clean).first()

                if not supplier_obj and supplier_name:
                    # Busca por nome fantasia ou razão social
                    supplier_obj = Supplier.objects.filter(
                        tenant=tenant
                    ).filter(
                        models.Q(trade_name__iexact=supplier_name) |
                        models.Q(company_name__iexact=supplier_name)
                    ).first()

                # SMART CREATE: Se não encontrou mas tem dados mínimos, cria para não travar
                if not supplier_obj and supplier_name:
                    # Tenta validar o CNPJ se fornecido. Se for inválido, usa TEMP.
                    final_cnpj = None
                    if supplier_cnpj:
                        sc = "".join(filter(str.isdigit, supplier_cnpj))
                        if len(sc) == 14:
                            from apps.partners.models import validate_cnpj
                            try:
                                validate_cnpj(sc)
                                final_cnpj = sc
                            except: pass

                    if not final_cnpj:
                        # Antes de criar com TEMP-, verifica se já existe um com TEMP e mesmo nome
                        existing_temp = Supplier.objects.filter(
                            tenant=tenant,
                            cnpj__startswith='TEMP-'
                        ).filter(
                            models.Q(trade_name__iexact=supplier_name) |
                            models.Q(company_name__iexact=supplier_name)
                        ).first()
                        if existing_temp:
                            supplier_obj = existing_temp
                        else:
                            final_cnpj = f"TEMP-{uuid.uuid4().hex[:8]}"

                if not supplier_obj and supplier_name and 'final_cnpj' in dir() and final_cnpj:
                    supplier_obj = Supplier.objects.create(
                        tenant=tenant,
                        cnpj=final_cnpj,
                        company_name=supplier_name[:200],
                        trade_name=supplier_name[:200],
                        is_active=True
                    )

                location_name = get_val(row, 'location')
                location_obj = None
                if location_name:
                    from apps.inventory.models import Location
                    location_obj = Location.objects.filter(tenant=tenant, name__iexact=location_name).first()
                    if not location_obj:
                         location_obj = Location.objects.create(tenant=tenant, name=location_name[:100], code=location_name[:10].upper())

                # 3. CREATE OU UPDATE
                if is_update:
                    # UPDATE VARIANT
                    variant.name = name[:255]
                    barcode = get_val(row, 'barcode')
                    if barcode: variant.barcode = barcode[:100]

                    cost = get_val(row, 'cost')
                    if cost:
                        parsed_cost = parse_decimal_br(cost)
                        if parsed_cost is not None:
                            variant.avg_unit_cost = parsed_cost

                    variant.save()

                    # UPDATE PARENT PRODUCT
                    product = variant.product
                    product.name = name[:255] if not sku_pai else product.name # Se for variável, não sobrescreve nome do pai com nome da variante
                    if cat_obj: product.category = cat_obj
                    if brand_obj: product.brand = brand_obj
                    if supplier_obj: product.default_supplier = supplier_obj
                    if location_obj: product.default_location = location_obj
                    uom = get_val(row, 'unit')
                    if uom: product.uom = uom[:10]
                    product.save()
                else:
                    # CREATE LOGIC
                    if sku_pai:
                        # VARIABLE PRODUCT LOGIC
                        parent, _ = Product.objects.get_or_create(
                            tenant=tenant,
                            sku=sku_pai[:50],
                            defaults={
                                'name': name[:255].split('-')[0].strip(), # Tenta pegar o nome base antes do '-'
                                'product_type': ProductType.VARIABLE,
                                'category': cat_obj,
                                'brand': brand_obj,
                                'default_supplier': supplier_obj,
                                'default_location': location_obj,
                                'uom': (get_val(row, 'unit') or 'UN')[:10]
                            }
                        )
                        # Se já existia, garante que é variável
                        if parent.product_type != ProductType.VARIABLE:
                            parent.product_type = ProductType.VARIABLE
                            parent.save()

                        # Cria a variante
                        variant = ProductVariant.objects.create(
                            tenant=tenant,
                            product=parent,
                            sku=sku,
                            name=name[:255],
                            barcode=get_val(row, 'barcode'),
                            avg_unit_cost=parse_decimal_br(get_val(row, 'cost')) or Decimal('0'),
                            is_active=True
                        )
                    else:
                        # SIMPLE PRODUCT LOGIC
                        product = Product.objects.create(
                            tenant=tenant,
                            sku=sku[:50],
                            name=name[:255],
                            product_type=ProductType.SIMPLE,
                            category=cat_obj,
                            brand=brand_obj,
                            default_supplier=supplier_obj,
                            default_location=location_obj,
                            uom=(get_val(row, 'unit') or 'UN')[:10]
                        )
                        # O save() do Product SIMPLE cria uma variant padrão.
                        variant = product.variants.first()
                        variant.sku = sku[:50]
                        variant.name = name[:255]
                        barcode = get_val(row, 'barcode')
                        if barcode: variant.barcode = barcode[:100]
                        cost = get_val(row, 'cost')
                        if cost:
                            parsed_cost = parse_decimal_br(cost)
                            if parsed_cost is not None:
                                variant.avg_unit_cost = parsed_cost
                        variant.save()

                # 4. PARSE ATRIBUTOS (Para ambos se houver attrs_raw)
                if attrs_raw:
                    from apps.products.models import VariantAttributeValue, AttributeType
                    # Formato: Cor:Azul; Tamanho:G
                    parts = [p.strip() for p in attrs_raw.split(';') if ':' in p]
                    for part in parts:
                        attr_key, attr_val = part.split(':', 1)
                        attr_key = attr_key.strip()[:50]
                        attr_val = attr_val.strip()[:100]

                        a_type, _ = AttributeType.objects.get_or_create(tenant=tenant, name=attr_key)
                        VariantAttributeValue.objects.get_or_create(
                            variant=variant,
                            attribute_type=a_type,
                            defaults={'value': attr_val}
                        )

                # 5. ESTOQUE (ADJ ABSOLUTO SE FORNECIDO)
                stock_val = get_val(row, 'stock')
                if stock_val is not None:
                    try:
                        new_qty = parse_decimal_br(stock_val)
                        if new_qty is None:
                            log_entries.append(f"Linha {index+1} (SKU {sku}): Valor de estoque inválido '{stock_val}'.")
                        elif not is_update or variant.current_stock != new_qty:
                            StockService.create_movement(
                                tenant=tenant,
                                user=batch.user,
                                variant=variant,
                                movement_type='ADJ',
                                quantity=new_qty,
                                reason="Ajuste via Importação Direta de Catálogo"
                            )
                    except Exception as stock_err:
                        log_entries.append(f"Linha {index+1} (SKU {sku}): Erro no estoque: {stock_err}")

                success_count += 1
                batch.processed_rows = index + 1
                if index % 10 == 0:
                    batch.save()

        summary = f"Catálogo processado. {success_count} itens criados/atualizados. {error_count} erros."
        if log_entries:
            summary += "\nDetalhes:\n" + "\n".join(log_entries[:20])
        return summary


    except Exception as e:
        return f"Erro crítico: {e}"


        raise


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def process_export_catalog(self, batch_id):
    """
    Generate export file (CSV/Excel/JSON) in background
    Uses the unified ProductExporter from reports app
    """
    from .models import ExportBatch
    from apps.reports.exports import ProductExporter
    from django.core.files.base import ContentFile
    import pandas as pd
    import json

    try:
        batch = ExportBatch.objects.get(id=batch_id)
        batch.status = 'PROCESSING'
        batch.save()

        tenant = batch.tenant
        exporter = ProductExporter(tenant)

        # Parse params
        params = json.loads(batch.params) if batch.params else {}
        include_variants = params.get('variants', True)
        include_inactive = params.get('inactive', False)
        days = params.get('days', 30)

        # Determine content and filename based on format
        content = None
        ext = 'csv'

        if batch.export_type == 'CSV':
            ext = 'csv'
            if batch.resource == 'PRODUCTS':
                content = exporter.export_csv(include_variants=include_variants, include_inactive=include_inactive)
            elif batch.resource == 'MOVEMENTS':
                 content = exporter.export_movements_csv(days=days)

        elif batch.export_type == 'EXCEL':
            ext = 'xlsx'
            if batch.resource == 'PRODUCTS':
                content = exporter.export_excel(include_variants=include_variants, include_inactive=include_inactive)

        elif batch.export_type == 'JSON':
            ext = 'json'
            if batch.resource == 'PRODUCTS':
                content = exporter.export_json(include_variants=include_variants, include_inactive=include_inactive)

        if not content:
             raise ValueError(f"Falha ao gerar conteúdo para {batch.resource} ({batch.export_type})")

        filename = f"export_{batch.resource.lower()}_{batch.created_at.strftime('%Y%m%d_%H%M')}.{ext}"

        # Save file
        if isinstance(content, str):
            batch.file.save(filename, ContentFile(content.encode('utf-8')))
        else:
            batch.file.save(filename, ContentFile(content))

        batch.status = 'COMPLETED'
        batch.total_rows = 0 # TODO: Exporter could return count
        batch.completed_at = pd.Timestamp.now()
        batch.save()

        return f"Exported {batch.resource} as {batch.export_type}"

    except Exception as e:
        if 'batch' in locals():
            batch.status = 'FAILED'
            batch.log = str(e)
            batch.save()
        raise e
