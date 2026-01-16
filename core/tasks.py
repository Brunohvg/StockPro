import csv
import io
import xml.etree.ElementTree as ET
from celery import shared_task
from django.db import transaction
from django.contrib.auth.models import User
from .models import Product, StockMovement, ImportBatch, Category, Brand
from .services import StockService
import pandas as pd

@shared_task(bind=True)
def process_import_task(self, batch_id):
    try:
        batch = ImportBatch.objects.get(id=batch_id)
        batch.status = 'PROCESSING'
        batch.save()

        if batch.type == 'CSV_PRODUCTS':
            result = process_csv(batch)
        elif batch.type == 'XML_NFE':
            result = process_xml_nfe(batch)
        else:
            result = "Tipo de importação desconhecido."

        batch.status = 'COMPLETED'
        batch.log = result
        batch.save()

    except Exception as e:
        if 'batch' in locals():
            batch.status = 'ERROR'
            batch.log = f"Falha crítica no worker: {str(e)}"
            batch.save()
        raise e

def process_csv(batch):
    tenant = batch.tenant
    df = pd.read_csv(batch.file.path)
    required_cols = ['sku', 'name', 'category']
    if not all(col in df.columns for col in required_cols):
        return f"Erro: Colunas obrigatórias ausentes. Necessário: {required_cols}"

    success_count = 0
    errors = []

    for _, row in df.iterrows():
        try:
            with transaction.atomic():
                # Get or Create Relations (Normalized V5)
                cat_name = str(row.get('category', 'Geral'))
                brand_name = str(row.get('brand', 'Sem Marca'))

                cat_obj, _ = Category.objects.get_or_create(tenant=tenant, name=cat_name[:100])
                brand_obj, _ = Brand.objects.get_or_create(tenant=tenant, name=brand_name[:100])

                # Get or Create Product
                product, created = Product.objects.update_or_create(
                    tenant=tenant,
                    sku=str(row['sku']),
                    defaults={
                        'name': str(row['name']),
                        'category': cat_obj,
                        'brand': brand_obj,
                        'uom': str(row.get('uom', 'UN')),
                        'minimum_stock': int(row.get('minimum_stock', 0)),
                        'avg_unit_cost': float(row.get('cost', 0)) if not pd.isna(row.get('cost')) else None
                    }
                )

                # If it's a new product or we want to initialize stock
                initial_qty = int(row.get('initial_stock', 0))
                if initial_qty > 0:
                    StockService.create_movement(
                        tenant=tenant,
                        user=batch.user,
                        product_sku=product.sku,
                        movement_type='IN',
                        quantity=initial_qty,
                        reason="Carga inicial via CSV",
                        source="CSV",
                        unit_cost=product.avg_unit_cost,
                        source_doc=f"Batch {batch.id}"
                    )

                success_count += 1
        except Exception as e:
            errors.append(f"SKU {row.get('sku')}: {str(e)}")

    return f"Sucesso: {success_count} itens. Erros: {len(errors)}. {chr(10).join(errors[:5])}"

def process_xml_nfe(batch):
    tenant = batch.tenant
    try:
        tree = ET.parse(batch.file.path)
        root = tree.getroot()

        # Multiple common namespaces for NF-e
        ns_list = [
            {'nfe': 'http://www.portalfiscal.inf.br/nfe'},
            {'nfe': ''} # Fallback
        ]

        infNFe = None
        current_ns = None
        for ns in ns_list:
            infNFe = root.find('.//nfe:infNFe', ns)
            if infNFe is not None:
                current_ns = ns
                break

        if infNFe is None:
            return "Erro: Estrutura infNFe não encontrada. Certifique-se que o arquivo é um XML de NF-e válido."

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

            # Additional metadata if available
            ean = getattr(prod.find('nfe:cEAN', current_ns), 'text', '')

            try:
                # Normalized Relations (V5)
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
                    }
                )

                # Update cost if 0 or new
                if not product.avg_unit_cost or product.avg_unit_cost == 0:
                    product.avg_unit_cost = unit_val
                    product.save()

                StockService.create_movement(
                    tenant=tenant,
                    user=batch.user,
                    product_sku=product.sku,
                    movement_type='IN',
                    quantity=int(qty),
                    reason=f"Importação NF-e {nNF}",
                    source="XML",
                    unit_cost=unit_val,
                    source_doc=doc_ref
                )
                success_count += 1
            except Exception as e:
                errors.append(f"Erro item {sku}: {str(e)}")

        status_msg = f"Sucesso: {success_count} itens. "
        if errors:
            status_msg += f"Erros: {len(errors)}. {'; '.join(errors[:3])}"

        return status_msg

    except Exception as e:
        return f"Falha de processamento XML: {str(e)}"
