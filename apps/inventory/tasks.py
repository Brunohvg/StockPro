"""
Enhanced Celery Tasks for Import Processing (V10)
- Supports product types (SIMPLE/VARIABLE)
- Handles variants with attributes
- Idempotency via ImportLog
- Retry with exponential backoff
"""
import hashlib
import xml.etree.ElementTree as ET
from decimal import Decimal

import pandas as pd
from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from django.db import transaction

from apps.core.services import StockService
from apps.products.models import Brand, Category

from .models import ImportBatch, ImportLog


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
            batch=batch,
            row_number=0,
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


def process_xml_nfe(batch):
    """Process XML NFe for inventory updates (V3 - Smart Matcher)."""
    tenant = batch.tenant
    file_path = batch.file.path

    try:
        tree = ET.parse(file_path)
        root = tree.getroot()

        # Define namespaces
        namespaces = {
            'nfe': 'http://www.portalfiscal.inf.br/nfe'
        }

        # Extract general NFe info
        ide = root.find('.//nfe:ide', namespaces)
        emit = root.find('.//nfe:emit', namespaces)

        nNF = ide.find('nfe:nNF', namespaces).text if ide is not None else 'N/A'
        supplier_cnpj = emit.find('nfe:CNPJ', namespaces).text if emit is not None else 'N/A'
        supplier_name = emit.find('nfe:xNome', namespaces).text if emit is not None else 'N/A'

        # Get or create Supplier
        from apps.partners.models import Supplier
        supplier_obj, _ = Supplier.objects.get_or_create(
            tenant=tenant,
            cnpj=supplier_cnpj,
            defaults={'company_name': supplier_name}
        )

        # Placeholder for brand and category (can be extracted from NFe or set to defaults)
        brand_obj, _ = Brand.objects.get_or_create(tenant=tenant, name="NFe Brand")
        cat_obj, _ = Category.objects.get_or_create(tenant=tenant, name="NFe Category")

        # Step 2: Extract totals for proportional distribution
        total_node = root.find('.//nfe:total/nfe:ICMSTot', namespaces)
        total_freight = Decimal('0')
        total_seg = Decimal('0')
        total_outro = Decimal('0')

        if total_node is not None:
            def get_total_decimal(path):
                node = total_node.find(path, namespaces)
                return Decimal(node.text) if node is not None and node.text else Decimal('0')

            total_freight = get_total_decimal('nfe:vFrete')
            total_seg = get_total_decimal('nfe:vSeg')
            total_outro = get_total_decimal('nfe:vOutro')

        # Step 3: Extract items and prepare for AI grouping
        items = root.findall('.//nfe:det', namespaces)
        total_items_value = Decimal('0')
        items_data = []

        for det in items:
            p = det.find('nfe:prod', namespaces)
            if p is None:
                continue

            # Safe extraction helper
            def get_clean_decimal(node, path):
                found = node.find(path, namespaces)
                if found is not None and found.text:
                    try:
                        return Decimal(found.text)
                    except:
                        return Decimal('0')
                return Decimal('0')

            vProd = get_clean_decimal(p, 'nfe:vProd')
            total_items_value += vProd

            barcode_node = p.find('nfe:cEAN', namespaces)
            barcode = barcode_node.text.strip() if barcode_node is not None and barcode_node.text and barcode_node.text != 'SEM GTIN' else None

            items_data.append({
                'sku': (p.find('nfe:cProd', namespaces).text or 'S/SKU') if p.find('nfe:cProd', namespaces) is not None else 'S/SKU',
                'name': (p.find('nfe:xProd', namespaces).text or 'Sem Nome') if p.find('nfe:xProd', namespaces) is not None else 'Sem Nome',
                'qty': get_clean_decimal(p, 'nfe:qCom'),
                'unit_val': get_clean_decimal(p, 'nfe:vUnCom'),
                'uom': p.find('nfe:uCom', namespaces).text if p.find('nfe:uCom', namespaces) is not None else 'UN',
                'vProd': vProd,
                'barcode': barcode,
                'vIPI': get_clean_decimal(det, './/nfe:vIPI'),
                'vDesc': get_clean_decimal(p, 'nfe:vDesc'),
                'infAdProd': det.find('nfe:infAdProd', namespaces).text if det.find('nfe:infAdProd', namespaces) is not None else "",
                'det_node': det
            })

        # Call AI for grouping before creating records
        ai_groups = ai_group_nfe_products(items_data, tenant=tenant, user=batch.user)
        group_map = {}
        if ai_groups and 'groups' in ai_groups:
            for group in ai_groups['groups']:
                parent_info = {
                    'parent_name': group.get('parent_name'),
                    'attribute': group.get('attribute'),
                }
                for variant in group.get('variants', []):
                    group_map[variant.get('sku')] = {
                        **parent_info,
                        'attr_value': variant.get('attr_value')
                    }

        # Step 4: Create ImportItem records with AI group metadata
        from apps.inventory.models import ImportItem
        for data in items_data:
            sku = data['sku']
            vProd = data['vProd']
            qty = data['qty']
            unit_val = data['unit_val']

            # Precision Factor: item_value / total_items_value
            cost_factor = vProd / total_items_value if total_items_value > 0 else 0

            # Additional costs to distribute
            # Landed Cost = (Base - Discount) + (Freight+Seg+Outro)*Factor/Qty + DirectTaxes/Qty
            if qty > 0:
                indirect_costs = (total_freight + total_seg + total_outro) * cost_factor
                # Apply item-specific discount
                discount_per_unit = data['vDesc'] / qty
                landed_cost = (unit_val - discount_per_unit) + (indirect_costs / qty) + (data['vIPI'] / qty)
            else:
                landed_cost = unit_val

            # Check if AI grouped this item
            ai_meta = group_map.get(sku, {})

            ImportItem.objects.create(
                tenant=tenant,
                batch=batch,
                supplier_sku=sku,
                description=data['name'],
                ean=data['barcode'],
                quantity=qty,
                unit_cost=landed_cost,
                raw_data={
                    'uom': data['uom'],
                    'vProd': str(vProd),
                    'vIPI': str(data['vIPI']),
                    'infAdProd': data['infAdProd'],
                },
                ai_suggestion={
                    'group_info': ai_meta,
                    'is_variant': bool(ai_meta)
                } if ai_meta else None,
                ai_logic_summary="Agrupamento IA (Whole Invoice) detectado" if ai_meta else ""
            )

        # Step 3: Call the V3 Smart Matcher
        result_summary = process_batch_v3_intelligence(batch, tenant, supplier_obj, brand_obj, cat_obj, nNF)

        batch.status = 'COMPLETED' if "Sucesso" in result_summary else 'PENDING_REVIEW'
        batch.log = result_summary
        batch.save()

        return result_summary

    except Exception as e:
        batch.status = 'ERROR'
        batch.log = f"Critical Error: {str(e)}"
        batch.save()
        raise e


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

    # Step 3: Create Granular ImportItems and Process (V3)
    from decimal import Decimal

    from apps.inventory.models import ImportItem
    from apps.partners.models import Supplier
    from apps.products.models import Brand, Category

    # Placeholder Brand/Category if not provided in CSV
    brand_obj, _ = Brand.objects.get_or_create(tenant=tenant, name="CSV Import")
    cat_obj, _ = Category.objects.get_or_create(tenant=tenant, name="CSV Import")
    supplier_obj = batch.supplier # Use the batch one or fallback
    if not supplier_obj:
        # Fallback if batch.supplier is not set (e.g., for direct CSV upload)
        supplier_obj, _ = Supplier.objects.get_or_create(tenant=tenant, company_name="Importação CSV", cnpj="00000000000000")

    for _, row in df.iterrows():
        ImportItem.objects.create(
            tenant=tenant,
            batch=batch,
            supplier_sku=str(row.get('sku', '')),
            description=str(row.get('name', '')),
            ean=str(row.get('barcode', '')) if pd.notna(row.get('barcode')) else None,
            quantity=Decimal(str(row.get('stock', 0))) if pd.notna(row.get('stock')) else Decimal('0'),
            unit_cost=Decimal(str(row.get('cost', 0))) if pd.notna(row.get('cost')) else Decimal('0'),
            raw_data=row.to_dict()
        )

    # Call the Universal V3 Intelligence Helper
    result_summary = process_batch_v3_intelligence(batch, tenant, supplier_obj, brand_obj, cat_obj, "CSV-BATCH")

    batch.status = 'COMPLETED' if "Sucesso" in result_summary else 'PENDING_REVIEW'
    batch.notes = result_summary
    batch.save()

    return result_summary


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


def ai_group_nfe_products(product_list, tenant=None, user=None):
    """
    Use AI to analyze NF-e product names and detect variable product groupings.

    Args:
        product_list: List of dicts with {sku, name, qty, cost, barcode}

    Returns:
        Dict with groupings and confidence metadata.
    """
    import json

    from apps.core.services import AIService

    if len(product_list) < 2:
        return None  # Need at least 2 products to group

    # Prepare product list for AI
    product_names = "\n".join([f"- SKU: {p['sku']}, Nome: {p['name']}" for p in product_list[:50]])  # Limit to 50 items

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
4. Para cada variação, extraia o nome completo e o código de barras (se disponível) do produto original.

Se não houver grupos detectados, retorne: {{"groups": [], "confidence_score": 1.0, "logic": "No groups found"}}

Retorne APENAS um JSON no formato:
{{
  "confidence_score": 0.95,
  "logic": "Matches based on color prefix pattern",
  "groups": [
    {{
      "parent_name": "FELTRO SANTA FE 10M 140CM",
      "attribute": "Cor",
      "variants": [
        {{"sku": "123", "name": "FELTRO SANTA FE 10M AZUL BABY 140CM", "barcode": "7891234567890", "attr_value": "AZUL BABY"}},
        {{"sku": "456", "name": "FELTRO SANTA FE 10M VERMELHO 140CM", "barcode": "7890987654321", "attr_value": "VERMELHO"}}
      ]
    }}
  ]
}}"""

    try:
        from apps.core.models import AIDecisionLog

        response = AIService.call_ai(prompt, schema="json")
        if not response:
            return None

        # Parse JSON from response
        start = response.find('{')
        end = response.rfind('}')
        if start != -1 and end != -1:
            json_str = response[start:end+1]
            result = json.loads(json_str)

            # Log the decision
            if tenant:
                AIDecisionLog.objects.create(
                    tenant=tenant,
                    user=user,
                    feature='NFE_GROUPING',
                    provider='XAI', # Default in settings
                    model_name='grok-2-latest',
                    prompt_text=prompt,
                    response_json=result,
                    confidence_score=Decimal(str(result.get('confidence_score', 0)))
                )

            return result

        return None
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"AI NF-e grouping failed: {e}")
        return None


def process_batch_v3_intelligence(batch, tenant, supplier_obj, brand_obj, cat_obj, source_ref):
    """
    V3 Intelligent Ingestion: Orchestrates the classification and processing
    of each ImportItem in the batch.
    """
    from decimal import Decimal

    from django.utils import timezone

    from apps.core.models import SystemSetting
    from apps.inventory.services.matcher import ProductMatcher

    settings = SystemSetting.get_settings(tenant)
    threshold = settings.ai_auto_approve_threshold if settings else Decimal('0.90')
    mode = settings.ai_import_mode if settings else 'HYBRID'

    items = batch.items.all()
    success_count = 0
    pending_count = 0
    errors = []

    for item in items:
        # Match using the V3 Intelligence Layer
        result = ProductMatcher.match(item, tenant, supplier_obj)

        # Save intelligence metadata back to item
        item.ai_confidence = result.confidence
        item.ai_logic_summary = result.logic
        item.ai_suggestion = result.suggestion_data

        # Decision Logic: Auto or Staging
        should_auto = (mode == 'AUTO') or (mode == 'HYBRID' and result.confidence >= threshold)

        if should_auto and (result.product or result.variant):
            try:
                with transaction.atomic():
                    if result.variant:
                        StockService.create_movement(
                            tenant=tenant,
                            user=batch.user,
                            variant=result.variant,
                            movement_type='IN',
                            quantity=item.quantity,
                            reason=f"Importação {source_ref} (Auto-match V3)",
                            unit_cost=item.unit_cost
                        )
                        item.matched_variant = result.variant
                        # Update variant confidence/review if auto-matched
                        result.variant.ai_confidence = result.confidence
                        result.variant.requires_review = (result.confidence < threshold)
                        result.variant.save(update_fields=['ai_confidence', 'requires_review'])
                    else:
                        StockService.create_movement(
                            tenant=tenant,
                            user=batch.user,
                            product=result.product,
                            movement_type='IN',
                            quantity=item.quantity,
                            reason=f"Importação {source_ref} (Auto-match V3)",
                            unit_cost=item.unit_cost
                        )
                        item.matched_product = result.product
                        # Update product confidence/review if auto-matched
                        result.product.ai_confidence = result.confidence
                        result.product.requires_review = (result.confidence < threshold)
                        result.product.save(update_fields=['ai_confidence', 'requires_review'])

                    item.status = 'DONE'
                    item.processed_at = timezone.now()
                    success_count += 1
            except Exception as e:
                item.status = 'ERROR'
                item.ai_logic_summary += f" | Erro no processamento: {str(e)}"
                errors.append(f"Erro item {item.supplier_sku}: {str(e)}")
        else:
            # Flag for Manual Review
            item.status = 'PENDING'
            pending_count += 1

        item.save()

    msg = f"Sucesso: {success_count}. Pendentes p/ Revisão: {pending_count}."
    if errors:
        msg += f" Erros: {len(errors)}"
    return msg


# DEPRECATED: Keeping for backward compatibility during transition if needed,
# but process_xml_nfe now uses process_nfe_v3_intelligence.
def process_nfe_with_variants(batch, items, current_ns, tenant, supplier_obj, brand_obj, cat_obj, nNF):
    return "Removido em favor da V3 Inteligente"
    if grouped_count > 0:
        status_msg += f" ({grouped_count} variações agrupadas, {simple_count} simples)"
    status_msg += "."

    if errors:
        status_msg += f" Erros: {len(errors)}. {'; '.join(errors[:3])}"

    return status_msg
