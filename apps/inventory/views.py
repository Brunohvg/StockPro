"""
Inventory App Views - Stock movements and imports (V10)
"""
import csv

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.db.models import ProtectedError

from django.db import transaction
from django.utils import timezone

from apps.core.services import StockService
from apps.products.models import (
    AttributeType,
    Brand,
    Category,
    Product,
    ProductType,
    ProductVariant,
    VariantAttributeValue,
)
from apps.tenants.middleware import admin_required, trial_allows_read

from .forms import ImportBatchForm, LocationForm
from .models import ImportBatch, ImportLog, StockMovement, Location, ExportBatch
from .tasks import process_import_task


@login_required
def movement_list(request):
    tenant = request.tenant
    movements = StockMovement.objects.filter(tenant=tenant).select_related(
        'product', 'variant', 'variant__product', 'user'
    ).order_by('-created_at')

    query = request.GET.get('q', '')
    if query:
        movements = movements.filter(
            Q(product__sku__icontains=query) |
            Q(product__name__icontains=query) |
            Q(variant__sku__icontains=query) |
            Q(variant__product__name__icontains=query) |
            Q(user__username__icontains=query) |
            Q(reason__icontains=query)
        )

    return render(request, 'inventory/movement_list.html', {
        'movements': movements[:100],
        'search_query': query
    })


@login_required
@trial_allows_read
def create_movement(request):
    tenant = request.tenant

    # Pre-fetch locations
    locations = Location.objects.filter(tenant=tenant, is_active=True).order_by('-is_default', 'name')

    # Pre-fetch products for datalist
    simple_products = Product.objects.filter(
        tenant=tenant,
        product_type=ProductType.SIMPLE,
        is_active=True
    ).order_by('name')

    variants = ProductVariant.objects.filter(
        tenant=tenant,
        is_active=True
    ).select_related('product').order_by('product__name')

    if request.method == 'POST':
        product_identifier = request.POST.get('product_identifier', '').strip()
        movement_type = request.POST.get('type')
        quantity = int(request.POST.get('quantity', 0))
        reason = request.POST.get('reason', '')
        unit_cost = request.POST.get('unit_cost')
        location_id = request.POST.get('location')

        try:
            # Try to find by SKU (variant first, then simple product)
            variant = ProductVariant.objects.filter(
                Q(sku=product_identifier) | Q(barcode=product_identifier),
                tenant=tenant
            ).first()

            product = None
            if not variant:
                product = Product.objects.filter(
                    Q(sku=product_identifier) | Q(barcode=product_identifier),
                    tenant=tenant,
                    product_type=ProductType.SIMPLE
                ).first()

            if not variant and not product:
                # Try by name
                variant = ProductVariant.objects.filter(
                    product__name__icontains=product_identifier,
                    tenant=tenant
                ).first()
                if not variant:
                    product = Product.objects.filter(
                        name__icontains=product_identifier,
                        tenant=tenant,
                        product_type=ProductType.SIMPLE
                    ).first()

            if not variant and not product:
                raise Exception(f"Produto/variação '{product_identifier}' não encontrado.")

            StockService.create_movement(
                tenant=tenant,
                user=request.user,
                movement_type=movement_type,
                quantity=quantity,
                product=product,
                variant=variant,
                reason=reason,
                unit_cost=float(unit_cost) if unit_cost else None,
                location_id=location_id
            )

            target_name = variant.display_name if variant else product.name
            messages.success(request, f"Movimentação de {quantity} unidades registrada para {target_name}!")
            return redirect('inventory:movement_list')
        except Exception as e:
            messages.error(request, f"Erro: {str(e)}")

    return render(request, 'inventory/movement_form.html', {
        'simple_products': simple_products,
        'variants': variants,
        'locations': locations
    })


@login_required
@trial_allows_read
def create_movement_mobile(request):
    tenant = request.tenant

    # Pre-fetch for the initial "Quick Pick" list (last products updated)
    recent_products = Product.objects.filter(
        tenant=tenant,
        is_active=True
    ).order_by('-updated_at')[:10]

    if request.method == 'POST':
        # SKU can come from scanner or search selection
        sku = request.POST.get('sku', '').strip()
        movement_type = request.POST.get('type', 'OUT') # Default to OUT for mobile operational use
        quantity = int(request.POST.get('quantity', 1))
        variant_id = request.POST.get('variant_id') # Explicit variant selection

        try:
            if not sku and not variant_id:
                raise Exception("Nenhum produto selecionado.")

            variant = None
            product = None

            if variant_id:
                variant = ProductVariant.objects.get(pk=variant_id, tenant=tenant)
            else:
                # 1. Try exact SKU/Barcode match
                variant = ProductVariant.objects.filter(
                    Q(sku=sku) | Q(barcode=sku),
                    tenant=tenant
                ).first()

                if not variant:
                    # 2. Try Name case-insensitive
                    product = Product.objects.filter(
                        name__icontains=sku,
                        tenant=tenant
                    ).first()

            if not variant and not product:
                raise Exception(f"Item '{sku}' não encontrado.")

            # Resolve variant if only product was found (and it's SIMPLE)
            if not variant and product:
                if product.is_simple:
                    variant = product.variants.first()
                else:
                    # Variable product found but no variant specified
                    # This case should ideally be handled by JS selecting a variant before POST
                    raise Exception(f"Produto '{product.name}' exige escolha de uma variação.")

            StockService.create_movement(
                tenant=tenant,
                user=request.user,
                movement_type=movement_type,
                quantity=quantity,
                variant=variant,
                reason=f"Baixa Mobile por {request.user.username} (Mobile-Fast)"
            )

            messages.success(request, f"✓ {movement_type}: {quantity}x {variant.display_name}")
            return redirect('inventory:create_movement_mobile')
        except Exception as e:
            messages.error(request, str(e))

    return render(request, 'inventory/movement_mobile.html', {
        'recent_products': recent_products,
    })


@login_required
def import_list(request):
    tenant = request.tenant
    imports = ImportBatch.objects.filter(tenant=tenant).order_by('-created_at')
    completed_count = imports.filter(status='COMPLETED').count()
    error_count = imports.filter(status='ERROR').count()
    return render(request, 'inventory/import_list.html', {
        'imports': imports,
        'completed_count': completed_count,
        'error_count': error_count
    })


@login_required
def import_create(request):
    if request.method == 'POST':
        form = ImportBatchForm(request.POST, request.FILES)
        if form.is_valid():
            batch = form.save(commit=False)
            batch.user = request.user
            batch.tenant = request.tenant
            batch.save()

            try:
                from .tasks import process_import_task
                process_import_task.delay(str(batch.id))
                messages.info(request, "Arquivo enviado! O processamento iniciará em segundo plano.")
            except Exception as e:
                # Se o Celery/Redis falhar, avisamos mas salvamos o lote (sem jargão técnico para o usuário)
                messages.warning(request, "Arquivo recebido! O processamento automático está temporariamente indisponível, mas seu lote foi salvo. Ele será processado assim que o serviço for restabelecido.")
                print(f"Celery Error: {e}")

            return redirect('inventory:import_list')
    else:
        form = ImportBatchForm()
    return render(request, 'inventory/import_form.html', {'form': form})

@login_required
@admin_required
def import_reprocess(request, pk):
    """Reinicia o processamento de um lote"""
    batch = get_object_or_404(ImportBatch, id=pk, tenant=request.tenant)

    if batch.status == 'COMPLETED':
        messages.warning(request, "Este lote já foi processado com sucesso.")
        return redirect('inventory:import_list')

    # Deletamos logs de erro anteriores para permitir nova tentativa limpa
    ImportLog.objects.filter(batch=batch, status='ERROR').delete()

    batch.status = 'PENDING'
    batch.log = "Reprocessamento solicitado pelo usuário..."
    batch.save()

    try:
        from .tasks import process_import_task
        process_import_task.delay(str(batch.id))
        messages.success(request, f"O reprocessamento do lote {batch.id} foi iniciado.")
    except Exception as e:
        messages.warning(request, "Lote agendado, mas o serviço de fila está offline. O processamento ocorrerá assim que possível.")
        print(f"Celery Error: {e}")

    return redirect('inventory:import_list')

@login_required
def import_detail(request, pk):
    batch = get_object_or_404(ImportBatch, pk=pk, tenant=request.tenant)
    return render(request, 'inventory/import_detail.html', {'batch': batch})


@login_required
def delete_import(request, pk):
    batch = get_object_or_404(ImportBatch, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        batch.delete()
        messages.success(request, "Importação removida.")
    return redirect('inventory:import_list')


@login_required
@admin_required
def bulk_delete_imports(request):
    """Exclusão em massa de lotes de importação selecionados"""
    if request.method != 'POST':
        return redirect('inventory:import_list')

    import_ids = request.POST.getlist('import_ids')

    if not import_ids:
        messages.warning(request, "Nenhum lote selecionado.")
        return redirect('inventory:import_list')

    batches = ImportBatch.objects.filter(tenant=request.tenant, pk__in=import_ids)
    count = batches.count()

    if count > 0:
        batches.delete()
        messages.success(request, f"✅ {count} lote(s) de importação excluído(s)!")

    return redirect('inventory:import_list')
@login_required
@admin_required
def location_list(request):
    """List all inventory locations for the tenant"""
    tenant = request.tenant
    locations = Location.objects.filter(tenant=tenant).order_by('-is_default', 'name')
    return render(request, 'inventory/location_list.html', {'locations': locations})


@login_required
@admin_required
@trial_allows_read
def location_create(request):
    """Create a new inventory location"""
    if request.method == 'POST':
        form = LocationForm(request.POST, tenant=request.tenant)
        if form.is_valid():
            location = form.save(commit=False)
            location.tenant = request.tenant
            location.save()
            messages.success(request, f"Localização '{location.name}' criada com sucesso!")
            return redirect('inventory:location_list')
    else:
        form = LocationForm(tenant=request.tenant)
    return render(request, 'inventory/location_form.html', {'form': form})


@login_required
@admin_required
@trial_allows_read
def location_edit(request, pk):
    """Edit an existing inventory location"""
    location = get_object_or_404(Location, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        form = LocationForm(request.POST, instance=location, tenant=request.tenant)
        if form.is_valid():
            form.save()
            messages.success(request, f"Localização '{location.name}' atualizada!")
            return redirect('inventory:location_list')
    else:
        form = LocationForm(instance=location, tenant=request.tenant)
    return render(request, 'inventory/location_form.html', {'form': form, 'location': location})
@login_required
@admin_required
def download_csv_template(request):
    """Gera um arquivo CSV modelo para importação (Catalog ou Stock Sync)"""
    import_type = request.GET.get('type', 'CATALOG_DIRECT')

    response = HttpResponse(content_type='text/csv')
    filename = "modelo_estoque_movimentacao.csv" if import_type == 'STOCK_SYNC' else "modelo_catalogo_produtos.csv"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    writer = csv.writer(response)

    if import_type == 'STOCK_SYNC':
        # Modelo Simplificado para Movimentação (Soma/Subtração)
        # Header
        header = ['sku', 'quantidade', 'nome_produto', 'custo_unitario']
        writer.writerow(header)

        # Exemplo 1: Entrada (Compra)
        writer.writerow(['PAR-008', '100', 'Parafuso Sextavado (Ref. Visual)', '0.55'])

        # Exemplo 2: Saída (Ajuste/Venda Correção)
        writer.writerow(['CAM-BAS-BR-P', '-5', 'Camiseta Branca P (Ref. Visual)', ''])

    else:
        # Modelo Completo (Catálogo)
        # Header - Alinhado com os aliases do tasks.py
        header = [
            'nome', 'sku', 'sku_pai', 'atributos', 'codigo_barras', 'unidade', 'custo_medio',
            'estoque_atual', 'categoria', 'marca', 'fornecedor', 'cnpj', 'local'
        ]
        writer.writerow(header)

        # Exemplo 1: Produto Simples completo
        writer.writerow([
            'Parafuso Sextavado 8mm', 'PAR-008', '', '', '789100000001', 'UN', '0.55',
            '1000', 'Fixadores', 'Metalfix', 'Fornecedor Industrial LTDA', '03223361000131', 'Depósito Central'
        ])

        # Exemplo 2: Produto com Variações (Pai: Camiseta)
        writer.writerow([
            'Camiseta Básica - Branca P', 'CAM-BAS-BR-P', 'CAM-BASICA', 'Cor:Branca; Tamanho:P', '789100000002', 'PC', '25.90',
            '50', 'Vestuário', 'Hering', 'Malharia Conforto', '33000160000138', 'Loja Principal'
        ])

        # Exemplo 3: Outra variação do mesmo pai
        writer.writerow([
            'Camiseta Básica - Azul M', 'CAM-BAS-AZ-M', 'CAM-BASICA', 'Cor:Azul; Tamanho:M', '789100000003', 'PC', '25.90',
            '30', 'Vestuário', 'Hering', 'Malharia Conforto', '33000160000138', 'Loja Principal'
        ])

    return response


# ==========================================
# 5. Export Management (Async)
# ==========================================

@login_required
def export_list(request):
    """Redirect to new export page"""
    return redirect('reports:export_page')

@login_required
def export_create(request):
    """Redirect to new export page"""
    return redirect('reports:export_page')

@login_required
def export_download(request, pk):
    """Secure download of exported file"""
    batch = get_object_or_404(ExportBatch, pk=pk, tenant=request.tenant)

    if not batch.file:
        messages.error(request, "Arquivo não encontrado ou ainda não gerado.")
        return redirect('inventory:export_list')

    from django.http import FileResponse
    import os

    # Determine extension and filename
    ext = 'csv'
    if batch.export_type == 'EXCEL':
        ext = 'xlsx'
    elif batch.export_type == 'JSON':
        ext = 'json'

    # Use the original filename provided by the task if possible, else generate one
    filename = os.path.basename(batch.file.name)
    if not filename.endswith(ext):
         filename = f"export_{batch.resource.lower()}_{batch.created_at.strftime('%Y%m%d')}.{ext}"

    return FileResponse(batch.file.open(), as_attachment=True, filename=filename)

@login_required
def delete_export(request, pk):
    """Delete an export job and its file"""
    batch = get_object_or_404(ExportBatch, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        # File is deleted via signal or manual cleanup if needed,
        # but standard Django behavior on some storages might leave it.
        # For safety/explicit cleanup:
        if batch.file:
            batch.file.delete(save=False)
        batch.delete()
        messages.success(request, "Exportação removida com sucesso.")
    return redirect('inventory:export_list')

    return redirect('inventory:export_list')


@login_required
@admin_required
def delete_location(request, pk):
    """Delete a single stock location"""
    location = get_object_or_404(Location, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        try:
            location.delete()
            messages.success(request, f"Local '{location.name}' removido com sucesso.")
        except ProtectedError:
            messages.error(request, f"Não é possível excluir o local '{location.name}' pois existem movimentações de estoque associadas a ele.")
        except Exception as e:
            messages.error(request, f"Erro ao excluir local: {str(e)}")

    return redirect('inventory:location_list')


@login_required
@admin_required
def delete_locations_batch(request):
    """Delete multiple stock locations"""
    if request.method == 'POST':
        ids = request.POST.getlist('selected_ids')
        if ids:
            try:
                # Filter by tenant to ensure security
                deleted_count, _ = Location.objects.filter(
                    tenant=request.tenant,
                    id__in=ids
                ).delete()
                messages.success(request, f"{deleted_count} locais foram removidos com sucesso.")
            except ProtectedError:
                messages.error(request, "Não foi possível excluir alguns locais pois eles possuem movimentações de estoque associadas.")
            except Exception as e:
                messages.error(request, f"Erro ao excluir locais: {str(e)}")
        else:
            messages.warning(request, "Nenhum local selecionado.")

    return redirect('inventory:location_list')
