"""
Enhanced Celery Tasks for Import Processing (V10)
- Supports product types (SIMPLE/VARIABLE)
- Handles variants with attributes
- Idempotency via ImportLog
- Retry with exponential backoff
"""
import hashlib
import re
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


def run_import(batch, dry_run=False):
    if batch.type in ['CATALOG_DIRECT', 'CSV_PRODUCTS']:
        return process_csv_catalog_direct(batch, dry_run=dry_run)
    if batch.type in ['STOCK_SYNC', 'CSV_INVENTORY']:
        return process_csv_stock_adjustment(batch, dry_run=dry_run)
    return "Erro crítico: tipo de importação descontinuado (NF-e/Legado)."


def preview_import(batch):
    """Executa a importação dentro de uma transação desfeita e guarda o resumo no lote."""
    result = run_import(batch, dry_run=True)
    batch.log = result
    batch.status = 'ERROR' if result.startswith('Erro crítico') else 'PENDING_REVIEW'
    batch.processed_rows = 0
    batch.save()
    return result


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

        batch.error_count = 0
        result = run_import(batch)
        critical = result.startswith('Erro crítico')

        from django.utils import timezone
        batch.status = 'ERROR' if critical else 'COMPLETED'
        batch.log = result
        batch.completed_at = timezone.now()
        batch.save()

        # Só registra sucesso (idempotência) se não houve erro nenhum;
        # assim o usuário pode corrigir a planilha e reenviar.
        ImportLog.objects.create(
            batch=batch,
            row_number=0,
            idempotency_key=idempotency_key,
            status='ERROR' if critical or batch.error_count else 'SUCCESS',
            message=result[:5000]
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


# ==========================================
# Importação por planilha (.xlsx / CSV)
# ==========================================

CATALOG_COLUMNS = {
    'sku': ['sku', 'codigo', 'cod', 'codigo_sku', 'referencia', 'ref', 'id'],
    'name': ['nome', 'name', 'nome_produto', 'produto', 'titulo', 'descricao', 'description'],
    'description': ['descricao_detalhada', 'descricao_completa', 'detalhes', 'observacoes', 'obs'],
    'category': ['categoria', 'category', 'cat', 'grupo'],
    'brand': ['marca', 'brand', 'fabricante'],
    'barcode': ['codigo_de_barras', 'codigo_barras', 'cod_barras', 'barcode', 'ean', 'gtin'],
    'unit': ['unidade', 'unit', 'uom', 'un'],
    'cost': ['custo', 'custo_unitario', 'custo_medio', 'preco_custo', 'preco_de_custo', 'cost', 'avg_unit_cost'],
    'sale_price': ['preco_venda', 'preco_de_venda', 'valor_venda', 'preco', 'sale_price', 'price'],
    'stock': ['estoque', 'estoque_atual', 'saldo', 'quantidade', 'qtd', 'qtde', 'qty', 'stock'],
    'min_stock': ['estoque_minimo', 'minimo', 'min_stock', 'minimum_stock'],
    'supplier': ['fornecedor', 'supplier', 'forn'],
    'cnpj': ['cnpj', 'cnpj_fornecedor', 'document', 'cpf_cnpj'],
    'location': ['local', 'location', 'deposito', 'armazem', 'local_estoque'],
    'sku_pai': ['sku_pai', 'parent_sku', 'pai', 'sku_mestre', 'master_sku', 'produto_pai'],
    'attributes': ['atributos', 'attributes', 'caracteristicas', 'variacao', 'specs'],
    'lot': ['lote', 'lot', 'numero_lote', 'n_lote', 'lot_number'],
    'expiry': ['validade', 'data_validade', 'data_de_validade', 'vencimento', 'data_vencimento', 'expiry', 'expiry_date'],
    'manufacture': ['fabricacao', 'data_fabricacao', 'data_de_fabricacao', 'manufacture_date'],
    'tracks_expiry': ['controla_validade', 'perecivel', 'tracks_expiry'],
}

STOCK_COLUMNS = {
    'sku': CATALOG_COLUMNS['sku'] + ['codigo_de_barras', 'ean'],
    'name': ['nome', 'name', 'nome_produto', 'produto', 'descricao'],
    'quantity': ['quantidade', 'qtd', 'qtde', 'qty', 'quantity', 'movimento', 'estoque', 'saldo'],
    'cost': CATALOG_COLUMNS['cost'],
    'lot': CATALOG_COLUMNS['lot'],
    'expiry': CATALOG_COLUMNS['expiry'],
    'manufacture': CATALOG_COLUMNS['manufacture'],
}

TRUE_WORDS = {'sim', 's', 'yes', 'y', 'true', '1', 'x'}


def _column_map(df, spec):
    """Mapeia campo -> coluna existente (primeiro apelido encontrado)."""
    cols = set(df.columns)
    found = {}
    for field, aliases in spec.items():
        for alias in aliases:
            if alias in cols and alias not in found.values():
                found[field] = alias
                break
    return found


def _getter(colmap):
    def get_val(row, field):
        col = colmap.get(field)
        if not col:
            return None
        value = str(row.get(col, '')).strip()
        return value or None
    return get_val


def _finish(batch, kind, created, updated, errors, log_entries, extra=None, dry_run=False):
    batch.success_count = created + updated
    batch.error_count = errors
    head = "PRÉVIA (nada foi gravado). " if dry_run else ""
    summary = f"{head}{kind}: {created} criados, {updated} atualizados. {errors} erros."
    if extra:
        summary += "\n" + "\n".join(f"• {k}: {v}" for k, v in extra.items() if v)
    if log_entries:
        summary += "\nDetalhes por linha:\n" + "\n".join(log_entries)
    return summary


def process_csv_stock_adjustment(batch, dry_run=False):
    """
    Movimentação por planilha (soma/subtrai) — casa SOMENTE por SKU ou código de barras.
    Quantidade positiva = entrada, negativa = saída (FEFO para produtos com validade).
    Colunas opcionais: custo, lote, validade, fabricacao.
    """
    from apps.products.models import ProductVariant
    from .services.spreadsheet import SpreadsheetError, read_spreadsheet

    tenant = batch.tenant
    try:
        df = read_spreadsheet(batch.file.path)
    except SpreadsheetError as e:
        return f"Erro crítico: {e}"

    colmap = _column_map(df, STOCK_COLUMNS)
    if 'sku' not in colmap or 'quantity' not in colmap:
        return ("Erro crítico: a planilha precisa das colunas 'sku' e 'quantidade'. "
                f"Colunas encontradas: {', '.join(df.columns)}")
    get_val = _getter(colmap)

    batch.total_rows = len(df)
    batch.save()

    done = errors = 0
    log_entries = []

    with transaction.atomic():
        for index, row in df.iterrows():
            line = index + 2  # +1 cabeçalho, +1 base 1
            sku = get_val(row, 'sku')
            try:
                with transaction.atomic():
                    if not sku:
                        raise ValueError("SKU vazio.")
                    qty = parse_decimal_br(get_val(row, 'quantity'))
                    if qty is None:
                        raise ValueError(f"Quantidade inválida '{get_val(row, 'quantity')}'.")
                    if qty == 0:
                        log_entries.append(f"Linha {line} (SKU {sku}): quantidade 0, ignorada.")
                        continue
                    variant = (ProductVariant.objects.filter(tenant=tenant, sku=sku).first()
                               or ProductVariant.objects.filter(tenant=tenant, barcode=sku).first())
                    if not variant:
                        raise ValueError("SKU/código não encontrado no catálogo.")
                    StockService.create_movement(
                        tenant=tenant,
                        user=batch.user,
                        variant=variant,
                        movement_type='IN' if qty > 0 else 'OUT',
                        quantity=abs(qty),
                        reason=f"Movimentação por planilha ({get_val(row, 'name') or variant.sku})",
                        source='IMPORT',
                        unit_cost=parse_decimal_br(get_val(row, 'cost')),
                        lot_number=get_val(row, 'lot'),
                        expiry_date=get_val(row, 'expiry'),
                        manufacture_date=get_val(row, 'manufacture'),
                    )
                    done += 1
            except Exception as row_err:
                errors += 1
                log_entries.append(f"Linha {line} (SKU {sku or '?'}): {row_err}")
            batch.processed_rows = index + 1
        if dry_run:
            transaction.set_rollback(True)

    return _finish(batch, "Movimentação", 0, done, errors, log_entries, dry_run=dry_run)


def process_csv_catalog_direct(batch, dry_run=False):
    """
    Cadastro/atualização de catálogo por planilha.
    - SKU é a chave (sem SKU, procura pelo nome).
    - Categoria, marca, fornecedor (com CNPJ válido) e local são criados/ligados pelo nome.
    - sku_pai + atributos ("Cor:Azul; Tamanho:M") criam produtos com variação.
    - estoque é saldo absoluto (contagem). Com lote/validade, linhas repetidas do mesmo SKU
      somam lotes diferentes.
    - dry_run: executa tudo e desfaz no final (prévia).
    """
    from apps.inventory.models import Location
    from apps.partners.models import Supplier, validate_cnpj
    from apps.products.models import (
        AttributeType, Brand, Category, Product, ProductType, ProductVariant, VariantAttributeValue,
    )
    from .services.spreadsheet import SpreadsheetError, read_spreadsheet

    tenant = batch.tenant
    try:
        df = read_spreadsheet(batch.file.path)
    except SpreadsheetError as e:
        return f"Erro crítico: {e}"

    colmap = _column_map(df, CATALOG_COLUMNS)
    # 'descricao' só é o nome quando não há coluna 'nome'; senão vira a descrição do produto
    if 'descricao' in df.columns and colmap.get('name') != 'descricao' and 'description' not in colmap:
        colmap['description'] = 'descricao'
    if 'name' not in colmap:
        return f"Erro crítico: a planilha precisa da coluna 'nome'. Colunas encontradas: {', '.join(df.columns)}"
    get_val = _getter(colmap)

    batch.total_rows = len(df)
    batch.save()

    created = updated = errors = 0
    new_categories, new_brands, lots_seen = set(), set(), 0
    log_entries = []
    lot_skus_touched = set()  # SKUs que já receberam lote nesta planilha

    def money(field, line):
        raw = get_val(row, field)
        if raw is None:
            return None
        value = parse_decimal_br(raw.replace('R$', '').strip())
        if value is None or value < 0:
            log_entries.append(f"Linha {line}: valor inválido em '{colmap[field]}': '{raw}' (ignorado).")
            return None
        return value

    with transaction.atomic():
        for index, row in df.iterrows():
            line = index + 2
            sku = get_val(row, 'sku')
            try:
                with transaction.atomic():
                    name = get_val(row, 'name')
                    if not name:
                        raise ValueError("Nome vazio.")
                    sku_pai = get_val(row, 'sku_pai')
                    expiry = get_val(row, 'expiry')
                    lot_number = get_val(row, 'lot')
                    manufacture = get_val(row, 'manufacture')
                    # Valida datas cedo para dar erro claro na linha
                    from apps.core.services import parse_date_br
                    parse_date_br(expiry)
                    parse_date_br(manufacture)

                    # 1. EXISTENTE?
                    variant = None
                    if sku:
                        variant = ProductVariant.objects.filter(tenant=tenant, sku__iexact=sku).first()
                    else:
                        existing = Product.objects.filter(tenant=tenant, name__iexact=name).first()
                        if existing:
                            variant = existing.variants.first()
                    is_update = variant is not None

                    # 2. CATEGORIA / MARCA
                    cat_obj = None
                    cat_name = get_val(row, 'category')
                    if cat_name:
                        cat_obj = Category.objects.filter(tenant=tenant, name__iexact=cat_name).first()
                        if not cat_obj:
                            cat_obj = Category.objects.create(tenant=tenant, name=cat_name[:100])
                            new_categories.add(cat_obj.name)
                    brand_obj = None
                    brand_name = get_val(row, 'brand')
                    if brand_name:
                        brand_obj = Brand.objects.filter(tenant=tenant, name__iexact=brand_name).first()
                        if not brand_obj:
                            brand_obj = Brand.objects.create(tenant=tenant, name=brand_name[:100])
                            new_brands.add(brand_obj.name)

                    # 3. FORNECEDOR / LOCAL
                    supplier_obj = None
                    supplier_name = get_val(row, 'supplier')
                    cnpj_raw = get_val(row, 'cnpj')
                    cnpj = "".join(filter(str.isdigit, cnpj_raw or ''))
                    if cnpj:
                        supplier_obj = Supplier.objects.filter(tenant=tenant, cnpj=cnpj).first()
                    if not supplier_obj and supplier_name:
                        supplier_obj = Supplier.objects.filter(tenant=tenant).filter(
                            models.Q(trade_name__iexact=supplier_name) | models.Q(company_name__iexact=supplier_name)
                        ).first()
                    if not supplier_obj and supplier_name and len(cnpj) == 14:
                        try:
                            validate_cnpj(cnpj)
                            supplier_obj = Supplier.objects.create(
                                tenant=tenant, cnpj=cnpj, company_name=supplier_name[:200],
                                trade_name=supplier_name[:200], is_active=True,
                            )
                        except Exception:
                            log_entries.append(f"Linha {line}: CNPJ '{cnpj_raw}' inválido; produto sem fornecedor.")
                    elif not supplier_obj and supplier_name:
                        log_entries.append(f"Linha {line}: fornecedor '{supplier_name}' não cadastrado "
                                           "(informe o CNPJ para criar automaticamente).")

                    location_obj = None
                    location_name = get_val(row, 'location')
                    if location_name:
                        location_obj = Location.objects.filter(tenant=tenant, name__iexact=location_name).first()
                        if not location_obj:
                            code = re.sub(r'[^A-Z0-9]', '', location_name.upper())[:10] or 'LOC'
                            base, n = code, 1
                            while Location.objects.filter(tenant=tenant, code=code).exists():
                                n += 1
                                code = f"{base[:8]}{n}"
                            location_obj = Location.objects.create(tenant=tenant, name=location_name[:100], code=code)

                    unit = (get_val(row, 'unit') or '').upper()[:10] or None
                    cost = money('cost', line)
                    sale_price = money('sale_price', line)
                    min_stock = parse_decimal_br(get_val(row, 'min_stock')) if get_val(row, 'min_stock') else None
                    description = get_val(row, 'description')
                    tracks_flag = get_val(row, 'tracks_expiry')
                    tracks = bool(expiry or lot_number) or (
                        tracks_flag is not None and tracks_flag.strip().lower() in TRUE_WORDS)

                    # 4. CRIA OU ATUALIZA
                    if is_update:
                        product = variant.product
                        if not product.is_active or not variant.is_active:
                            # SKU de produto arquivado na planilha: reativa (conta no limite do plano)
                            if tenant.products_limit_reached:
                                plan = tenant.plan
                                raise ValueError(
                                    f"Produto arquivado não reativado: limite de "
                                    f"{plan.max_products if plan else 0} produtos do plano atingido.")
                            product.is_active = True
                            variant.is_active = True
                            log_entries.append(f"Linha {line}: produto arquivado '{variant.sku}' reativado.")
                        if not sku_pai:
                            product.name = name[:255]
                        variant.name = name[:255] if product.is_variable else variant.name
                    else:
                        if tenant.products_limit_reached:
                            plan = tenant.plan
                            raise ValueError(f"Limite de {plan.max_products if plan else 0} produtos do plano atingido.")
                        if sku_pai:
                            product, _ = Product.objects.get_or_create(
                                tenant=tenant, sku=sku_pai[:50],
                                defaults={'name': name[:255].split(' - ')[0].strip(),
                                          'product_type': ProductType.VARIABLE},
                            )
                            if product.product_type != ProductType.VARIABLE:
                                product.product_type = ProductType.VARIABLE
                            if not product.is_active:
                                product.is_active = True
                                log_entries.append(f"Linha {line}: produto pai arquivado '{product.sku}' reativado.")
                            variant = ProductVariant.objects.create(
                                tenant=tenant, product=product, sku=(sku or '')[:50], name=name[:255],
                            )
                        else:
                            product = Product.objects.create(
                                tenant=tenant, sku=(sku or None) and sku[:50], name=name[:255],
                                product_type=ProductType.SIMPLE,
                            )
                            variant = product.variants.first()

                    if cat_obj:
                        product.category = cat_obj
                    if brand_obj:
                        product.brand = brand_obj
                    if supplier_obj:
                        product.default_supplier = supplier_obj
                    if location_obj:
                        product.default_location = location_obj
                    if unit:
                        product.uom = unit
                    if description:
                        product.description = description
                    if tracks:
                        product.tracks_expiry = True
                    if sale_price is not None and product.is_simple:
                        product.sale_price = sale_price
                    product.save()

                    barcode = get_val(row, 'barcode')
                    if barcode:
                        variant.barcode = barcode[:100]
                    if cost is not None:
                        variant.avg_unit_cost = cost
                    if sale_price is not None and product.is_variable:
                        variant.sale_price = sale_price
                    if min_stock is not None and min_stock >= 0:
                        variant.minimum_stock = min_stock
                    variant.save()

                    # 5. ATRIBUTOS
                    attrs_raw = get_val(row, 'attributes')
                    if attrs_raw:
                        for part in [p.strip() for p in attrs_raw.split(';') if ':' in p]:
                            key, val = part.split(':', 1)
                            a_type, _ = AttributeType.objects.get_or_create(tenant=tenant, name=key.strip()[:50])
                            VariantAttributeValue.objects.update_or_create(
                                variant=variant, attribute_type=a_type, defaults={'value': val.strip()[:100]},
                            )

                    # 6. ESTOQUE (saldo absoluto; lotes repetidos do mesmo SKU somam)
                    stock_raw = get_val(row, 'stock')
                    if stock_raw is not None:
                        new_qty = parse_decimal_br(stock_raw)
                        if new_qty is None or new_qty < 0:
                            raise ValueError(f"Estoque inválido '{stock_raw}'.")
                        has_lot = bool(expiry or lot_number)
                        if has_lot:
                            lots_seen += 1
                        if has_lot and variant.pk in lot_skus_touched:
                            if new_qty > 0:
                                StockService.create_movement(
                                    tenant=tenant, user=batch.user, variant=variant, movement_type='IN',
                                    quantity=new_qty, unit_cost=cost, source='IMPORT',
                                    reason="Importação de catálogo (lote adicional)",
                                    lot_number=lot_number, expiry_date=expiry, manufacture_date=manufacture,
                                )
                        elif has_lot or not is_update or variant.current_stock != new_qty:
                            StockService.create_movement(
                                tenant=tenant, user=batch.user, variant=variant, movement_type='ADJ',
                                quantity=new_qty, source='IMPORT',
                                reason="Importação de catálogo (saldo)",
                                lot_number=lot_number, expiry_date=expiry, manufacture_date=manufacture,
                            )
                        if has_lot:
                            lot_skus_touched.add(variant.pk)

                    if is_update:
                        updated += 1
                    else:
                        created += 1
            except Exception as row_err:
                errors += 1
                log_entries.append(f"Linha {line} (SKU {sku or '?'}): {row_err}")
            batch.processed_rows = index + 1
            if not dry_run and index % 50 == 0:
                ImportBatch.objects.filter(pk=batch.pk).update(processed_rows=batch.processed_rows)
        if dry_run:
            transaction.set_rollback(True)

    extra = {
        'Categorias novas': ', '.join(sorted(new_categories)),
        'Marcas novas': ', '.join(sorted(new_brands)),
        'Linhas com lote/validade': lots_seen,
    }
    return _finish(batch, "Catálogo", created, updated, errors, log_entries, extra, dry_run=dry_run)


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
        batch.total_rows = 0  # TODO: Exporter could return count
        from django.utils import timezone as _tz
        batch.completed_at = _tz.now()
        batch.save()

        return f"Exported {batch.resource} as {batch.export_type}"

    except Exception as e:
        if 'batch' in locals():
            batch.status = 'FAILED'
            batch.log = str(e)
            batch.save()
        raise e
