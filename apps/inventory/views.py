"""
Inventory App Views - Stock movements and imports
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q

from .models import StockMovement, ImportBatch
from .forms import ImportBatchForm
from apps.products.models import Product
from apps.core.services import StockService


@login_required
def movement_list(request):
    tenant = request.tenant
    movements = StockMovement.objects.filter(tenant=tenant).select_related('product', 'user').order_by('-created_at')

    query = request.GET.get('q', '')
    if query:
        movements = movements.filter(
            Q(product__sku__icontains=query) |
            Q(product__name__icontains=query) |
            Q(user__username__icontains=query) |
            Q(reason__icontains=query)
        )

    return render(request, 'inventory/movement_list.html', {'movements': movements[:100], 'search_query': query})


@login_required
def create_movement(request):
    tenant = request.tenant
    products = Product.objects.filter(tenant=tenant, is_active=True).order_by('name')

    if request.method == 'POST':
        product_id = request.POST.get('product')
        movement_type = request.POST.get('type')
        quantity = int(request.POST.get('quantity', 0))
        reason = request.POST.get('reason', '')
        unit_cost = request.POST.get('unit_cost')

        try:
            product = Product.objects.get(pk=product_id, tenant=tenant)
            StockService.create_movement(
                tenant=tenant,
                user=request.user,
                product_sku=product.sku,
                movement_type=movement_type,
                quantity=quantity,
                reason=reason,
                unit_cost=float(unit_cost) if unit_cost else None
            )
            messages.success(request, f"Movimentação de {quantity} unidades registrada!")
            return redirect('inventory:movement_list')
        except Exception as e:
            messages.error(request, f"Erro: {str(e)}")

    return render(request, 'inventory/movement_form.html', {'products': products})


@login_required
def create_movement_mobile(request):
    tenant = request.tenant

    if request.method == 'POST':
        sku = request.POST.get('sku', '').strip()
        movement_type = request.POST.get('type', 'IN')
        quantity = int(request.POST.get('quantity', 1))
        reason = request.POST.get('reason', '')

        try:
            product = Product.objects.get(tenant=tenant, sku=sku)
            StockService.create_movement(
                tenant=tenant,
                user=request.user,
                product_sku=sku,
                movement_type=movement_type,
                quantity=quantity,
                reason=reason or f"Movimentação mobile por {request.user.username}"
            )
            if request.headers.get('HX-Request'):
                return render(request, 'inventory/partials/mobile_search_results.html', {
                    'success': True,
                    'message': f"{movement_type} de {quantity}x {product.name} registrada!",
                    'product': product
                })
            messages.success(request, f"Movimentação registrada para {product.name}!")
            return redirect('inventory:create_movement_mobile')
        except Product.DoesNotExist:
            error_msg = f"Produto com SKU '{sku}' não encontrado."
            if request.headers.get('HX-Request'):
                return render(request, 'inventory/partials/mobile_search_results.html', {'error': error_msg})
            messages.error(request, error_msg)
        except Exception as e:
            error_msg = str(e)
            if request.headers.get('HX-Request'):
                return render(request, 'inventory/partials/mobile_search_results.html', {'error': error_msg})
            messages.error(request, error_msg)

    return render(request, 'inventory/movement_mobile.html')


@login_required
def import_list(request):
    tenant = request.tenant
    imports = ImportBatch.objects.filter(tenant=tenant).order_by('-created_at')
    completed_count = imports.filter(status='COMPLETED').count()
    error_count = imports.filter(status='ERROR').count()
    return render(request, 'inventory/import_list.html', {'imports': imports, 'completed_count': completed_count, 'error_count': error_count})


@login_required
def import_create(request):
    if request.method == 'POST':
        form = ImportBatchForm(request.POST, request.FILES)
        if form.is_valid():
            batch = form.save(commit=False)
            batch.user = request.user
            batch.tenant = request.tenant
            batch.save()
            from .tasks import process_import_task
            process_import_task.delay(batch.id)
            messages.info(request, "Arquivo enviado! O processamento iniciará em segundo plano.")
            return redirect('inventory:import_list')
    else:
        form = ImportBatchForm()
    return render(request, 'inventory/import_form.html', {'form': form})


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
