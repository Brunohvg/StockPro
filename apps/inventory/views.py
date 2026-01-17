"""
Inventory App Views - Stock movements and imports (V10)
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
import csv
from django.http import HttpResponse

from .models import StockMovement, ImportBatch
from .models_v2 import Location
from .forms import ImportBatchForm, LocationForm
from apps.products.models import Product, ProductVariant, ProductType
from apps.core.services import StockService
from apps.tenants.middleware import trial_allows_read, admin_required


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

    # Pre-fetch for autocomplete
    simple_products = Product.objects.filter(
        tenant=tenant,
        product_type=ProductType.SIMPLE,
        is_active=True
    ).order_by('name')[:50]

    variants = ProductVariant.objects.filter(
        tenant=tenant,
        is_active=True
    ).select_related('product').order_by('product__name')[:50]

    if request.method == 'POST':
        # Accept both 'sku' and 'product' field names for flexibility
        sku = request.POST.get('sku', '') or request.POST.get('product', '')
        sku = sku.strip()
        movement_type = request.POST.get('type', 'IN')
        quantity = int(request.POST.get('quantity', 1))
        reason = request.POST.get('reason', '')

        try:
            if not sku:
                raise Exception("Nenhum produto selecionado.")

            # Try variant first
            variant = ProductVariant.objects.filter(
                Q(sku=sku) | Q(barcode=sku),
                tenant=tenant
            ).first()

            product = None
            if not variant:
                product = Product.objects.filter(
                    Q(sku=sku) | Q(barcode=sku),
                    tenant=tenant,
                    product_type=ProductType.SIMPLE
                ).first()

            # If not found by exact SKU, try by name
            if not variant and not product:
                variant = ProductVariant.objects.filter(
                    Q(product__name__icontains=sku) | Q(name__icontains=sku),
                    tenant=tenant
                ).first()
                if not variant:
                    product = Product.objects.filter(
                        name__icontains=sku,
                        tenant=tenant,
                        product_type=ProductType.SIMPLE
                    ).first()

            if not variant and not product:
                raise Exception(f"Produto/variação '{sku}' não encontrado.")

            StockService.create_movement(
                tenant=tenant,
                user=request.user,
                movement_type=movement_type,
                quantity=quantity,
                product=product,
                variant=variant,
                reason=reason or f"Mobile por {request.user.username}"
            )

            target_name = variant.display_name if variant else product.name
            messages.success(request, f"✓ {movement_type}: {quantity}x {target_name}")
            return redirect('inventory:create_movement_mobile')
        except Exception as e:
            messages.error(request, str(e))

    return render(request, 'inventory/movement_mobile.html', {
        'simple_products': simple_products,
        'variants': variants
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
    """Gera um arquivo CSV modelo para importação de produtos"""
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="modelo_importacao_produtos.csv"'

    writer = csv.writer(response)
    # Header
    writer.writerow(['nome', 'sku', 'codigo_barras', 'custo_medio', 'estoque_atual', 'estoque_minimo', 'categoria', 'marca'])
    # Example rows
    writer.writerow(['Produto Exemplo A', 'SKU-001', '7891234567890', '10.50', '100', '10', 'Ferramentas', 'Bosch'])
    writer.writerow(['Produto Exemplo B', 'SKU-002', '7891234567891', '55.00', '50', '5', 'Elétrica', 'Tramontina'])

    return response
