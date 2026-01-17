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

        # Check if already processed successfully
        existing_log = ImportLog.objects.filter(idempotency_key=idempotency_key, status='SUCCESS').first()
        if existing_log:
            batch.status = 'COMPLETED'
            batch.log = f"Já processado com sucesso anteriormente em {existing_log.created_at}"
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
    Enhanced CSV processor with AI-powered column mapping and variant support
    """
    tenant = batch.tenant
    df = pd.read_csv(batch.file.path)

    # Normalize column names (lowercase, strip whitespace)
    df.columns = [c.strip().lower() for c in df.columns]

    batch.total_rows = len(df)
    batch.processed_rows = 0
    batch.save()

    required_cols = ['sku', 'name']

    # If required columns are missing, try AI mapping
    if not all(col in df.columns for col in required_cols):
        ai_mapping = ai_map_csv_columns(batch.file.path)

        if ai_mapping and ai_mapping.get('column_mapping'):
            df, detected_type = normalize_csv_with_mapping(df, ai_mapping)

            # Log AI mapping success
            import logging
            logging.getLogger(__name__).info(
                f"AI mapped CSV columns: {ai_mapping.get('column_mapping')} "
                f"(confidence: {ai_mapping.get('confidence', 'unknown')})"
            )
        else:
            return f"Erro: Colunas obrigatórias ausentes ({required_cols}). A IA não conseguiu mapear automaticamente. Verifique se o CSV tem colunas de código e nome do produto."

    # Validate again after potential AI mapping
    if not all(col in df.columns for col in required_cols):
        return f"Erro: Mesmo após mapeamento IA, colunas obrigatórias ausentes. Necessário: {required_cols}"

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
        batch.processed_rows = idx + 1
        if (idx + 1) % 5 == 0:  # Update DB every 5 rows to reduce overhead
            batch.save()

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

                    if initial_stock > 0 or batch.type == 'CSV_INVENTORY':
                        # Se for Modo Inventário, o ajuste deve ser ABSOLUTO
                        if batch.type == 'CSV_INVENTORY':
                            # No Modo Inventário, ignoramos se o stock na planilha é 0 ou nulo de propósito (pode ser contagem literal 0)
                            stock_to_set = int(row.get('stock', 0)) if pd.notna(row.get('stock')) else 0

                            # Só cria movimento se o estoque for diferente do atual para evitar logs inúteis
                            if product.current_stock != stock_to_set:
                                StockService.create_movement(
                                    tenant=tenant,
                                    user=batch.user,
                                    product=product,
                                    movement_type='ADJ',
                                    quantity=stock_to_set, # ADJ no StockService é absoluto
                                    reason="Ajuste via Inventário (Planilha)",
                                    unit_cost=product.avg_unit_cost
                                )
                        elif initial_stock > 0:
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
                if initial_stock > 0 or batch.type == 'CSV_INVENTORY':
                    if batch.type == 'CSV_INVENTORY':
                        stock_to_set = initial_stock
                        if variant.current_stock != stock_to_set:
                            StockService.create_movement(
                                tenant=tenant,
                                user=batch.user,
                                variant=variant,
                                movement_type='ADJ',
                                quantity=stock_to_set,
                                reason="Ajuste via Inventário (Planilha)",
                                unit_cost=variant.avg_unit_cost
                            )
                    elif initial_stock > 0:
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
    """Process XML NF-e with deduplication and barcode support"""
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
        emit_node = root.find('.//nfe:emit', current_ns)
        emit_name = emit_node.find('nfe:xNome', current_ns).text
        emit_cnpj = emit_node.find('nfe:CNPJ', current_ns).text

        # Deduplication check: generate source_doc and check if already imported
        source_doc = f"NFE-{emit_cnpj}-{serie}-{nNF}"

        existing_import = ImportBatch.objects.filter(
            tenant=tenant,
            source_doc=source_doc,
            status='COMPLETED'
        ).first()

        if existing_import:
            batch.status = 'COMPLETED'
            batch.log = f"Esta nota já foi importada anteriormente em {existing_import.created_at.strftime('%d/%m/%Y %H:%M')}."
            batch.source_doc = source_doc
            batch.save()
            return batch.log

        # Save source_doc for future deduplication
        batch.source_doc = source_doc
        batch.save()

        doc_ref = f"NF {nNF}-{serie} ({emit_name[:15]})"

        # Create/get supplier
        from apps.partners.models import Supplier
        supplier_obj, _ = Supplier.get_or_create_from_nfe(
            tenant=tenant,
            cnpj=emit_cnpj,
            company_name=emit_name
        )

        items = root.findall('.//nfe:det', current_ns)
        batch.total_rows = len(items)
        batch.processed_rows = 0
        batch.save()

        # Create category and brand for this import (AI-powered brand extraction)
        cat_obj, _ = Category.objects.get_or_create(tenant=tenant, name='Importado XML')
        clean_brand_name = ai_extract_brand_name(emit_name)
        brand_obj, _ = Brand.objects.get_or_create(tenant=tenant, name=clean_brand_name)

        # Use intelligent variant detection
        return process_nfe_with_variants(
            batch=batch,
            items=items,
            current_ns=current_ns,
            tenant=tenant,
            supplier_obj=supplier_obj,
            brand_obj=brand_obj,
            cat_obj=cat_obj,
            nNF=nNF
        )

    except Exception as e:
        return f"Falha de processamento XML: {str(e)}"


def ai_map_csv_columns(file_path):
    """
    Use AI to intelligently map CSV columns to our internal schema.
    Returns a mapping dict or None if AI fails.
    """
    import json
    from apps.core.services import AIService

    try:
        # Read first 3 rows as sample
        df = pd.read_csv(file_path, nrows=3)
        csv_sample = df.to_csv(index=False)

        prompt = f"""Você é um assistente de mapeamento de dados para um sistema de estoque. Analise o cabeçalho e as 2 primeiras linhas deste CSV e retorne um JSON com:

1. **Mapeamento de Colunas**: Identifique qual coluna corresponde a cada campo do nosso schema.
2. **Tipo de Produto**: Detecte se o CSV contém produtos SIMPLES ou VARIÁVEIS (com variações como cor, tamanho, voltagem).

**Pistas para detectar Produtos Variáveis:**
- Colunas com nomes como "cor", "tamanho", "voltagem", "atributo", "variacao", "opcao"
- SKUs repetidos com valores diferentes em outras colunas
- Padrão de nome como "Camiseta - Azul - M"

**Schema Interno:**
- sku (código do produto)
- name (nome/descrição)
- barcode (código de barras / EAN / GTIN)
- stock (estoque/quantidade)
- cost (custo/preço)
- category (categoria)
- brand (marca)
- attr_* (atributos de variação: attr_cor, attr_tamanho, etc.)

CSV:
{csv_sample}

Retorne APENAS um JSON no formato:
{{
  "product_type": "SIMPLE",
  "column_mapping": {{
    "sku_column": "nome_da_coluna_ou_null",
    "name_column": "nome_da_coluna_ou_null",
    "barcode_column": "nome_da_coluna_ou_null",
    "stock_column": "nome_da_coluna_ou_null",
    "cost_column": "nome_da_coluna_ou_null",
    "category_column": "nome_da_coluna_ou_null",
    "brand_column": "nome_da_coluna_ou_null"
  }},
  "attribute_columns": [],
  "confidence": "HIGH",
  "notes": ""
}}"""

        response = AIService.call_ai(prompt, schema="json")
        if not response:
            return None

        # Parse JSON from response
        start = response.find('{')
        end = response.rfind('}')
        if start != -1 and end != -1:
            json_str = response[start:end+1]
            return json.loads(json_str)

        return None
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"AI CSV mapping failed: {e}")
        return None


def normalize_csv_with_mapping(df, mapping):
    """
    Rename CSV columns based on AI mapping to match internal schema.
    """
    column_rename = {}
    col_map = mapping.get('column_mapping', {})

    if col_map.get('sku_column'):
        column_rename[col_map['sku_column']] = 'sku'
    if col_map.get('name_column'):
        column_rename[col_map['name_column']] = 'name'
    if col_map.get('barcode_column'):
        column_rename[col_map['barcode_column']] = 'barcode'
    if col_map.get('stock_column'):
        column_rename[col_map['stock_column']] = 'stock'
    if col_map.get('cost_column'):
        column_rename[col_map['cost_column']] = 'cost'
    if col_map.get('category_column'):
        column_rename[col_map['category_column']] = 'category'
    if col_map.get('brand_column'):
        column_rename[col_map['brand_column']] = 'brand'

    # Rename attribute columns
    for attr_col in mapping.get('attribute_columns', []):
        if attr_col in df.columns:
            column_rename[attr_col] = f'attr_{attr_col.lower()}'

    df = df.rename(columns=column_rename)
    return df, mapping.get('product_type', 'SIMPLE')


def ai_extract_brand_name(supplier_name):
    """
    Use AI to extract a clean, marketable brand name from a supplier/company name.

    Examples:
    - "INDUSTRIA DE FELTROS SANTA FE S/A" → "Santa Fé"
    - "CIRCULO LTDA" → "Círculo"
    - "COATS CORRENTE LTDA" → "Coats Corrente"

    Returns the original name if AI fails.
    """
    import json
    from apps.core.services import AIService

    if not supplier_name or len(supplier_name) < 3:
        return supplier_name

    prompt = f"""Você é um especialista em branding. Extraia o NOME DA MARCA comercial do nome desta empresa fornecedora:

"{supplier_name}"

Regras:
1. Remova termos jurídicos: LTDA, S/A, S.A., ME, EPP, EIRELI, CIA, IND, COM, IMP, EXP, etc.
2. Remova termos genéricos: INDUSTRIA, INDUSTRIAS, COMERCIO, IMPORTADORA, DISTRIBUIDORA, FABRICA
3. Mantenha o nome principal/fantasia da marca
4. Use capitalização correta (ex: "Santa Fé", não "SANTA FE")
5. Se houver acentuação provável, adicione (ex: "CIRCULO" → "Círculo")

Retorne APENAS um JSON: {{"brand": "Nome da Marca"}}"""

    try:
        response = AIService.call_ai(prompt, schema="json")
        if response:
            start = response.find('{')
            end = response.rfind('}')
            if start != -1 and end != -1:
                data = json.loads(response[start:end+1])
                brand = data.get('brand', '').strip()
                if brand and len(brand) >= 2:
                    return brand[:100]  # Limit to 100 chars
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"AI brand extraction failed: {e}")

    # Fallback: basic cleanup
    cleaned = supplier_name.upper()
    for term in ['LTDA', 'S/A', 'S.A.', ' ME', ' EPP', ' EIRELI', ' CIA', ' IND', ' COM']:
        cleaned = cleaned.replace(term, '')
    return cleaned.strip().title()[:100]


def ai_group_nfe_products(product_list):
    """
    Use AI to analyze NF-e product names and detect variable product groupings.

    Args:
        product_list: List of dicts with {sku, name, qty, cost, barcode}

    Returns:
        Dict with groupings: {
            'parent_name': {
                'attribute': 'Cor',
                'variants': [
                    {'sku': '...', 'name': '...', 'attr_value': 'Azul Baby', ...},
                ]
            }
        }
        Or None if no groupings detected.
    """
    import json
    from apps.core.services import AIService

    if len(product_list) < 2:
        return None  # Need at least 2 products to group

    # Prepare product list for AI
    product_names = "\n".join([f"- SKU: {p['sku']}, Nome: {p['name']}" for p in product_list[:30]])  # Limit to 30

    prompt = f"""Você é um assistente de catalogação de produtos. Analise esta lista de produtos de uma NF-e e identifique quais são VARIAÇÕES de um mesmo produto base.

**Exemplos de variações:**
- "FELTRO SANTA FE 10M AZUL BABY 140CM" e "FELTRO SANTA FE 10M VERMELHO 140CM" → Variações de "FELTRO SANTA FE 10M 140CM" com atributo "Cor"
- "CAMISETA BÁSICA P PRETA" e "CAMISETA BÁSICA G BRANCA" → Variações de "CAMISETA BÁSICA" com atributos "Tamanho" e "Cor"
- "TNT VERDE BILHAR 50G/M2 140CM 50M" e "TNT PRETO 50G/M2 140CM 50M" → Variações de "TNT 50G/M2 140CM 50M" com atributo "Cor"

**Lista de Produtos:**
{product_names}

**Instruções:**
1. Identifique grupos de produtos que são variações do mesmo item base
2. Para cada grupo, determine o nome do produto pai e qual atributo varia (Cor, Tamanho, Voltagem, etc.)
3. Se um produto não tem variações, NÃO o inclua no resultado

Retorne APENAS um JSON no formato:
{{
  "groups": [
    {{
      "parent_name": "FELTRO SANTA FE 10M 140CM",
      "attribute": "Cor",
      "variants": [
        {{"sku": "123", "attr_value": "AZUL BABY"}},
        {{"sku": "456", "attr_value": "VERMELHO"}}
      ]
    }}
  ]
}}

Se não houver grupos detectados, retorne: {{"groups": []}}"""

    try:
        response = AIService.call_ai(prompt, schema="json")
        if not response:
            return None

        # Parse JSON from response
        start = response.find('{')
        end = response.rfind('}')
        if start != -1 and end != -1:
            json_str = response[start:end+1]
            result = json.loads(json_str)
            if result.get('groups'):
                return result

        return None
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"AI NF-e grouping failed: {e}")
        return None


def process_nfe_with_variants(batch, items, current_ns, tenant, supplier_obj, brand_obj, cat_obj, nNF):
    """
    Process NF-e items with intelligent variant detection.
    """
    from decimal import Decimal

    # Step 1: Collect all product info
    product_list = []
    for det in items:
        prod = det.find('nfe:prod', current_ns)
        sku = prod.find('nfe:cProd', current_ns).text
        name = prod.find('nfe:xProd', current_ns).text
        qty = Decimal(prod.find('nfe:qCom', current_ns).text)
        uom = prod.find('nfe:uCom', current_ns).text
        unit_val = Decimal(prod.find('nfe:vUnCom', current_ns).text)

        barcode_node = prod.find('nfe:cEAN', current_ns)
        barcode = None
        if barcode_node is not None and barcode_node.text and barcode_node.text != 'SEM GTIN':
            barcode = barcode_node.text.strip()

        product_list.append({
            'sku': sku,
            'name': name,
            'qty': qty,
            'uom': uom,
            'cost': unit_val,
            'barcode': barcode
        })

    # Step 2: Try AI grouping
    groupings = ai_group_nfe_products(product_list)

    success_count = 0
    errors = []

    # Create SKU lookup from groupings
    sku_to_group = {}
    if groupings and groupings.get('groups'):
        for group in groupings['groups']:
            parent_name = group['parent_name']
            attribute = group['attribute']

            # Add explicitly listed variants
            for variant in group.get('variants', []):
                sku_to_group[variant['sku']] = {
                    'parent_name': parent_name,
                    'attribute': attribute,
                    'attr_value': variant['attr_value']
                }

            # AGGRESSIVE FALLBACK: Find other products that match this parent
            # Look for products whose name contains the parent name (fuzzy match)
            parent_words = set(parent_name.upper().split())

            for p in product_list:
                if p['sku'] in sku_to_group:
                    continue  # Already mapped

                # Check if product name contains most of the parent words
                product_words = set(p['name'].upper().split())
                common_words = parent_words & product_words

                # If 70%+ of parent words are in product name, it's likely a variant
                if len(common_words) >= len(parent_words) * 0.7:
                    # Extract the attribute value from the name difference
                    diff_words = product_words - parent_words
                    attr_value = ' '.join(sorted(diff_words)) if diff_words else p['name']

                    sku_to_group[p['sku']] = {
                        'parent_name': parent_name,
                        'attribute': attribute,
                        'attr_value': attr_value.title()
                    }

    # Step 3: Process products
    parent_cache = {}  # Cache for parent VARIABLE products

    for idx, p in enumerate(product_list):
        batch.processed_rows = idx + 1
        batch.save()

        try:
            if p['sku'] in sku_to_group:
                # This is a variant
                group_info = sku_to_group[p['sku']]
                parent_name = group_info['parent_name']

                # Get or create parent VARIABLE product
                if parent_name not in parent_cache:
                    parent_sku = f"VAR-{parent_name[:20].replace(' ', '-').upper()}"
                    parent, _ = Product.objects.update_or_create(
                        tenant=tenant,
                        name=parent_name,
                        product_type=ProductType.VARIABLE,
                        defaults={
                            'sku': parent_sku,
                            'category': cat_obj,
                            'brand': brand_obj,
                            'default_supplier': supplier_obj,
                            'is_active': True,
                        }
                    )
                    parent_cache[parent_name] = parent

                parent = parent_cache[parent_name]

                # Get or create attribute type
                attr_type, _ = AttributeType.objects.get_or_create(
                    tenant=tenant,
                    name=group_info['attribute']
                )

                # Create variant
                variant, created = ProductVariant.objects.update_or_create(
                    tenant=tenant,
                    sku=p['sku'],
                    defaults={
                        'product': parent,
                        'name': p['name'],
                        'barcode': p['barcode'],
                        'avg_unit_cost': p['cost'],
                    }
                )

                # Set attribute value
                VariantAttributeValue.objects.update_or_create(
                    variant=variant,
                    attribute_type=attr_type,
                    defaults={'value': group_info['attr_value']}
                )

                # Create stock movement for variant
                StockService.create_movement(
                    tenant=tenant,
                    user=batch.user,
                    variant=variant,
                    movement_type='IN',
                    quantity=int(p['qty']),
                    reason=f"Importação NF-e {nNF}",
                    unit_cost=p['cost']
                )
            else:
                # Simple product (no grouping detected)
                product, created = Product.objects.update_or_create(
                    tenant=tenant,
                    sku=p['sku'],
                    defaults={
                        'name': p['name'],
                        'uom': p['uom'],
                        'category': cat_obj,
                        'brand': brand_obj,
                        'default_supplier': supplier_obj,
                        'barcode': p['barcode'],
                        'is_active': True,
                        'product_type': ProductType.SIMPLE,
                    }
                )

                if not product.avg_unit_cost or product.avg_unit_cost == 0:
                    product.avg_unit_cost = p['cost']
                    product.save()

                StockService.create_movement(
                    tenant=tenant,
                    user=batch.user,
                    product=product,
                    movement_type='IN',
                    quantity=int(p['qty']),
                    reason=f"Importação NF-e {nNF}",
                    unit_cost=p['cost']
                )

            success_count += 1
        except Exception as e:
            errors.append(f"Erro item {p['sku']}: {str(e)}")

    # Build status message
    grouped_count = len(sku_to_group)
    simple_count = success_count - grouped_count

    status_msg = f"Sucesso: {success_count} itens"
    if grouped_count > 0:
        status_msg += f" ({grouped_count} variações agrupadas, {simple_count} simples)"
    status_msg += "."

    if errors:
        status_msg += f" Erros: {len(errors)}. {'; '.join(errors[:3])}"

    return status_msg
