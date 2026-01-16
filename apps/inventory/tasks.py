"""
Enhanced Celery Tasks for Import Processing (V10)
- Supports product types (SIMPLE/VARIABLE)
- Handles variants with attributes
- Idempotency via ImportLog
- Retry with exponential backoff
"""
import csv
import io
import hashlib
import xml.etree.ElementTree as ET
from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from django.db import transaction
import pandas as pd

from .models import ImportBatch, ImportLog, StockMovement
from apps.products.models import Product, ProductVariant, Category, Brand, AttributeType, VariantAttributeValue, ProductType
from apps.core.services import StockService


def generate_idempotency_key(batch_id, file_content):
    """Generate unique key for idempotency checking"""
    content_hash = hashlib.md5(file_content).hexdigest()[:16]
    return f"import_{batch_id}_{content_hash}"


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=True,
    soft_time_limit=240,
    time_limit=300
)
def process_import_task(self, batch_id, idempotency_key=None):
    """Process import with idempotency and retry support"""
    try:
        batch = ImportBatch.objects.get(id=batch_id)

        # Generate idempotency key if not provided
        if not idempotency_key:
            with open(batch.file.path, 'rb') as f:
                idempotency_key = generate_idempotency_key(batch_id, f.read())

        # Check if already processed
        existing_log = ImportLog.objects.filter(idempotency_key=idempotency_key).first()
        if existing_log:
            batch.status = 'COMPLETED'
            batch.log = f"Já processado anteriormente em {existing_log.created_at}"
            batch.save()
            return f"Idempotent skip: {idempotency_key}"

        batch.status = 'PROCESSING'
        batch.save()

        if batch.type == 'CSV_PRODUCTS':
            result = process_csv_v10(batch)
        elif batch.type == 'XML_NFE':
            result = process_xml_nfe(batch)
        else:
            result = "Tipo de importação desconhecido."

        batch.status = 'COMPLETED'
        batch.log = result
        batch.save()

        # Log successful processing for idempotency
        ImportLog.objects.create(
            tenant=batch.tenant,
            batch=batch,
            idempotency_key=idempotency_key,
            status='SUCCESS',
            details=result
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


def detect_product_type(row):
    """
    Detect product type from CSV row
    Returns: (type, parent_sku or None)

    Logic:
    - type column starts with VARIANT: -> variant of parent
    - type column is VARIABLE -> parent of variants
    - type column is SIMPLE or empty with no attr_* -> simple product
    """
    type_col = str(row.get('type', '')).strip().upper()

    if type_col.startswith('VARIANT:'):
        parent_sku = type_col.split(':', 1)[1].strip()
        return 'VARIANT', parent_sku

    if type_col == 'VARIABLE':
        return 'VARIABLE', None

    # Heuristic: check if has attribute columns with values
    attr_cols = [c for c in row.keys() if str(c).startswith('attr_')]
    has_attrs = any(row.get(c) and pd.notna(row.get(c)) for c in attr_cols)

    # If has attributes and stock, likely a standalone variant row (auto-detect)
    if has_attrs and row.get('stock') and pd.notna(row.get('stock')):
        # Check if there's a parent_sku column
        parent_sku = row.get('parent_sku', '')
        if parent_sku and pd.notna(parent_sku):
            return 'VARIANT', str(parent_sku)

    return 'SIMPLE', None


def process_csv_v10(batch):
    """
    Enhanced CSV processor with variant support

    Expected format:
    sku,name,type,category,brand,attr_cor,attr_tamanho,stock,cost,minimum_stock

    Types:
    - SIMPLE: Regular product
    - VARIABLE: Parent product for variants (no stock on parent)
    - VARIANT:PARENT-SKU: Variant of a variable product
    """
    tenant = batch.tenant
    df = pd.read_csv(batch.file.path)

    # Normalize column names
    df.columns = [c.strip().lower() for c in df.columns]

    required_cols = ['sku', 'name']
    if not all(col in df.columns for col in required_cols):
        return f"Erro: Colunas obrigatórias ausentes. Necessário: {required_cols}"

    # Find attribute columns
    attr_cols = [c for c in df.columns if c.startswith('attr_')]

    # Ensure AttributeTypes exist for each attr_ column
    attr_type_cache = {}
    for col in attr_cols:
        attr_name = col.replace('attr_', '').title()  # attr_cor -> Cor
        attr_type, _ = AttributeType.objects.get_or_create(
            tenant=tenant,
            name=attr_name
        )
        attr_type_cache[col] = attr_type

    stats = {'simple': 0, 'variable': 0, 'variant': 0, 'errors': []}

    # First pass: create SIMPLE and VARIABLE products
    for idx, row in df.iterrows():
        try:
            product_type, parent_sku = detect_product_type(row)

            if product_type == 'VARIANT':
                continue  # Process variants in second pass

            with transaction.atomic():
                cat_name = str(row.get('category', 'Geral')) if pd.notna(row.get('category')) else 'Geral'
                brand_name = str(row.get('brand', 'Sem Marca')) if pd.notna(row.get('brand')) else 'Sem Marca'

                cat_obj, _ = Category.objects.get_or_create(tenant=tenant, name=cat_name[:100])
                brand_obj, _ = Brand.objects.get_or_create(tenant=tenant, name=brand_name[:100])

                sku = str(row['sku']).strip()
                name = str(row['name']).strip()

                product_defaults = {
                    'name': name,
                    'category': cat_obj,
                    'brand': brand_obj,
                    'product_type': ProductType.VARIABLE if product_type == 'VARIABLE' else ProductType.SIMPLE,
                    'uom': str(row.get('uom', 'UN')) if pd.notna(row.get('uom')) else 'UN',
                    'minimum_stock': int(row.get('minimum_stock', 0)) if pd.notna(row.get('minimum_stock')) else 0,
                }

                # Only set stock/cost for SIMPLE products
                if product_type == 'SIMPLE':
                    product_defaults['avg_unit_cost'] = float(row.get('cost', 0)) if pd.notna(row.get('cost')) else None

                    initial_stock = int(row.get('stock', 0)) if pd.notna(row.get('stock')) else 0
                    product, created = Product.objects.update_or_create(
                        tenant=tenant,
                        sku=sku,
                        defaults=product_defaults
                    )

                    if initial_stock > 0:
                        StockService.create_movement(
                            tenant=tenant,
                            user=batch.user,
                            product=product,
                            movement_type='IN',
                            quantity=initial_stock,
                            reason="Carga inicial via CSV",
                            unit_cost=product.avg_unit_cost
                        )

                    stats['simple'] += 1
                else:
                    Product.objects.update_or_create(
                        tenant=tenant,
                        sku=sku,
                        defaults=product_defaults
                    )
                    stats['variable'] += 1

        except Exception as e:
            stats['errors'].append(f"Linha {idx+2} SKU {row.get('sku')}: {str(e)}")

    # Second pass: create VARIANT products
    for idx, row in df.iterrows():
        try:
            product_type, parent_sku = detect_product_type(row)

            if product_type != 'VARIANT':
                continue

            with transaction.atomic():
                # Find parent product
                parent = Product.objects.filter(
                    tenant=tenant,
                    sku=parent_sku,
                    product_type=ProductType.VARIABLE
                ).first()

                if not parent:
                    stats['errors'].append(f"Linha {idx+2}: Parent {parent_sku} não encontrado ou não é VARIABLE")
                    continue

                sku = str(row['sku']).strip()
                name = str(row.get('name', '')).strip() or None

                variant_defaults = {
                    'product': parent,
                    'name': name,
                    'barcode': str(row.get('barcode', '')) if pd.notna(row.get('barcode')) else None,
                    'avg_unit_cost': float(row.get('cost', 0)) if pd.notna(row.get('cost')) else None,
                    'minimum_stock': int(row.get('minimum_stock', 0)) if pd.notna(row.get('minimum_stock')) else 0,
                }

                variant, created = ProductVariant.objects.update_or_create(
                    tenant=tenant,
                    sku=sku,
                    defaults=variant_defaults
                )

                # Set attribute values
                for col, attr_type in attr_type_cache.items():
                    value = row.get(col)
                    if value and pd.notna(value):
                        VariantAttributeValue.objects.update_or_create(
                            variant=variant,
                            attribute_type=attr_type,
                            defaults={'value': str(value).strip()}
                        )

                # Set stock
                initial_stock = int(row.get('stock', 0)) if pd.notna(row.get('stock')) else 0
                if initial_stock > 0:
                    StockService.create_movement(
                        tenant=tenant,
                        user=batch.user,
                        variant=variant,
                        movement_type='IN',
                        quantity=initial_stock,
                        reason="Carga inicial via CSV",
                        unit_cost=variant.avg_unit_cost
                    )

                stats['variant'] += 1

        except Exception as e:
            stats['errors'].append(f"Linha {idx+2} Variant {row.get('sku')}: {str(e)}")

    error_summary = f" Erros: {len(stats['errors'])}." if stats['errors'] else ""
    error_detail = "\n".join(stats['errors'][:10]) if stats['errors'] else ""

    return f"Importados: {stats['simple']} simples, {stats['variable']} variáveis, {stats['variant']} variações.{error_summary}\n{error_detail}"


def process_xml_nfe(batch):
    """Process XML NF-e - creates SIMPLE products only"""
    tenant = batch.tenant
    try:
        tree = ET.parse(batch.file.path)
        root = tree.getroot()

        ns_list = [
            {'nfe': 'http://www.portalfiscal.inf.br/nfe'},
            {'nfe': ''}
        ]

        infNFe = None
        current_ns = None
        for ns in ns_list:
            infNFe = root.find('.//nfe:infNFe', ns)
            if infNFe is not None:
                current_ns = ns
                break

        if infNFe is None:
            return "Erro: Estrutura infNFe não encontrada."

        nNF = root.find('.//nfe:ide/nfe:nNF', current_ns).text
        serie = root.find('.//nfe:ide/nfe:serie', current_ns).text
        emit_name = root.find('.//nfe:emit/nfe:xNome', current_ns).text
        doc_ref = f"NF {nNF}-{serie} ({emit_name[:15]})"

        success_count = 0
        errors = []

        for det in root.findall('.//nfe:det', current_ns):
            prod = det.find('nfe:prod', current_ns)
            sku = prod.find('nfe:cProd', current_ns).text
            name = prod.find('nfe:xProd', current_ns).text
            qty = float(prod.find('nfe:qCom', current_ns).text)
            uom = prod.find('nfe:uCom', current_ns).text
            unit_val = float(prod.find('nfe:vUnCom', current_ns).text)

            try:
                cat_obj, _ = Category.objects.get_or_create(tenant=tenant, name='Importado XML')
                brand_obj, _ = Brand.objects.get_or_create(tenant=tenant, name=emit_name[:100])

                product, created = Product.objects.update_or_create(
                    tenant=tenant,
                    sku=sku,
                    defaults={
                        'name': name,
                        'uom': uom,
                        'category': cat_obj,
                        'brand': brand_obj,
                        'is_active': True,
                        'product_type': ProductType.SIMPLE,
                    }
                )

                if not product.avg_unit_cost or product.avg_unit_cost == 0:
                    product.avg_unit_cost = unit_val
                    product.save()

                StockService.create_movement(
                    tenant=tenant,
                    user=batch.user,
                    product=product,
                    movement_type='IN',
                    quantity=int(qty),
                    reason=f"Importação NF-e {nNF}",
                    unit_cost=unit_val
                )
                success_count += 1
            except Exception as e:
                errors.append(f"Erro item {sku}: {str(e)}")

        status_msg = f"Sucesso: {success_count} itens."
        if errors:
            status_msg += f" Erros: {len(errors)}. {'; '.join(errors[:3])}"

        return status_msg

    except Exception as e:
        return f"Falha de processamento XML: {str(e)}"
