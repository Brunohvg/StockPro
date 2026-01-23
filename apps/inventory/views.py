"""
Inventory App Views - Stock movements and imports (V10)
"""
import csv

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

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
from .models import ImportBatch, ImportItem, ImportLog, Location, StockMovement


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


@login_required
@admin_required
def pending_product_list(request):
    """Dashboard to review products flagged by AI (V3 Enhanced)"""
    from apps.products.models import Product

    from .models import ImportItem

    pending_items = ImportItem.objects.filter(
        tenant=request.tenant,
        status='PENDING'
    ).select_related('batch', 'matched_product', 'matched_variant')

    # Get existing products for "add as variant" option
    products = Product.objects.filter(
        tenant=request.tenant,
        is_active=True
    ).order_by('name')[:100]

    return render(request, 'inventory/pending_list.html', {
        'pending_items': pending_items,
        'products': products,
    })

@login_required
@admin_required
def pending_product_approve(request, pk):
    # Approves an AI suggestion for a specific ImportItem (V3 Enhanced)

    item = get_object_or_404(ImportItem, pk=pk, tenant=request.tenant)

    if request.method == 'POST':
        try:
            with transaction.atomic():
                target_product = item.matched_product
                target_variant = item.matched_variant

                # Get form data for product type selection
                product_action = request.POST.get('product_action', 'create_simple')
                parent_product_id = request.POST.get('parent_product_id')
                variant_attribute = request.POST.get('variant_attribute', '')
                variant_value = request.POST.get('variant_value', '')

                # If no match yet, create based on action
                if not target_product and not target_variant:
                    suggestion = item.ai_suggestion or {}
                    # Fallback to description if AI suggested name is missing
                    suggested_name = suggestion.get('suggested_name') or item.description or "Produto sem nome"

                    # Use detected category or create default
                    detected_cat = suggestion.get('detected_category')
                    if detected_cat:
                        cat_obj, _ = Category.objects.get_or_create(
                            tenant=request.tenant,
                            name=detected_cat,
                            defaults={'rotation': 'B'}
                        )
                    else:
                        cat_obj, _ = Category.objects.get_or_create(
                            tenant=request.tenant,
                            name="Importação",
                            defaults={'rotation': 'B'}
                        )

                    # Use detected brand or create default
                    detected_brand = suggestion.get('detected_brand')
                    if detected_brand:
                        brand_obj, _ = Brand.objects.get_or_create(
                            tenant=request.tenant,
                            name=detected_brand
                        )
                    else:
                        brand_obj, _ = Brand.objects.get_or_create(
                            tenant=request.tenant,
                            name="Sem Marca"
                        )

                    if product_action == 'create_simple':
                        # Create simple product
                        target_product = Product.objects.create(
                            tenant=request.tenant,
                            name=suggested_name,
                            sku=item.supplier_sku,
                            product_type=ProductType.SIMPLE,
                            barcode=item.ean,
                            avg_unit_cost=item.unit_cost,
                            category=cat_obj,
                            brand=brand_obj,
                            is_active=True
                        )

                    elif product_action == 'create_variable':
                        # Create variable product + first variant
                        target_product = Product.objects.create(
                            tenant=request.tenant,
                            name=suggested_name,
                            sku=item.supplier_sku, # Base SKU for variable
                            product_type=ProductType.VARIABLE,
                            category=cat_obj,
                            brand=brand_obj,
                            is_active=True
                        )

                        # Create attribute type if provided
                        attr_type = None
                        if variant_attribute:
                            attr_type, _ = AttributeType.objects.get_or_create(
                                tenant=request.tenant,
                                name=variant_attribute
                            )

                        # Create first variant
                        target_variant = ProductVariant.objects.create(
                            tenant=request.tenant,
                            product=target_product,
                            name=variant_value or item.description,
                            sku=item.supplier_sku, # Variant SKU
                            barcode=item.ean,
                            avg_unit_cost=item.unit_cost,
                            is_active=True
                        )

                        # Add attribute value if provided
                        if attr_type and variant_value:
                            VariantAttributeValue.objects.create(
                                variant=target_variant,
                                attribute_type=attr_type,
                                value=variant_value
                            )

                    elif product_action == 'add_variant' and parent_product_id:
                        # Add as variant to existing product
                        target_product = Product.objects.filter(
                            pk=parent_product_id,
                            tenant=request.tenant
                        ).first()

                        if target_product:
                            # Ensure product is VARIABLE type
                            if target_product.product_type != ProductType.VARIABLE:
                                target_product.product_type = ProductType.VARIABLE
                                target_product.save()

                            # Create attribute type if provided
                            attr_type = None
                            if variant_attribute:
                                attr_type, _ = AttributeType.objects.get_or_create(
                                    tenant=request.tenant,
                                    name=variant_attribute
                                )

                            target_variant = ProductVariant.objects.create(
                                tenant=request.tenant,
                                product=target_product,
                                name=variant_value or item.description,
                                sku=item.supplier_sku,
                                barcode=item.ean,
                                avg_unit_cost=item.unit_cost,
                                is_active=True
                            )

                            if attr_type and variant_value:
                                VariantAttributeValue.objects.create(
                                    variant=target_variant,
                                    attribute_type=attr_type,
                                    value=variant_value
                                )

                # Execute Stock Movement ONLY if quantity > 0 (XML/Invoice style)
                # For API Staged Creation, quantity is usually 0
                if item.quantity > 0:
                    StockService.create_movement(
                        tenant=request.tenant,
                        user=request.user,
                        product=target_product if not target_variant else None,
                        variant=target_variant,
                        movement_type='IN',
                        quantity=item.quantity,
                        reason=f"Aprovação Manual - Fonte {item.get_source_display()} (ID {item.id})",
                        unit_cost=item.unit_cost
                    )

                item.status = 'DONE'
                item.processed_at = timezone.now()
                item.matched_product = target_product
                item.matched_variant = target_variant
                item.save()

            if request.headers.get('HX-Request'):
                return HttpResponse(status=204)

            messages.success(request, "Item aprovado e estoque atualizado!")
            return redirect('inventory:pending_product_list')
        except Exception as e:
            if request.headers.get('HX-Request'):
                return HttpResponse(f"Erro: {str(e)}", status=400)
            messages.error(request, str(e))

    return redirect('inventory:pending_product_list')

@login_required
@admin_required
def pending_product_reject(request, pk):
    """Rejects an AI suggestion for an ImportItem"""
    from django.utils import timezone

    from .models import ImportItem
    item = get_object_or_404(ImportItem, pk=pk, tenant=request.tenant)

    item.status = 'REJECTED'
    item.processed_at = timezone.now()
    item.save()

    if request.headers.get('HX-Request'):
        return HttpResponse(status=204)

    messages.info(request, "Sugestão rejeitada.")
    return redirect('inventory:pending_product_list')


@login_required
@admin_required
def pending_product_bulk_approve(request):
    # Bulk approve multiple ImportItems at once

    if request.method != 'POST':
        return redirect('inventory:pending_product_list')

    item_ids = request.POST.getlist('item_ids')
    if not item_ids:
        messages.warning(request, "Nenhum item selecionado.")
        return redirect('inventory:pending_product_list')

    # Defensive parsing: remove any thousand separators (dots) that might have leaked from localized templates
    clean_ids = []
    for oid in item_ids:
        try:
            clean_ids.append(int(str(oid).replace('.', '').replace(',', '')))
        except ValueError:
            continue

    items = ImportItem.objects.filter(
        pk__in=clean_ids,
        tenant=request.tenant,
        status='PENDING'
    )

    success_count = 0
    error_count = 0

    # Get or create default category/brand
    cat_obj, _ = Category.objects.get_or_create(
        tenant=request.tenant,
        name="Importação",
        defaults={'rotation': 'B'}
    )
    brand_obj, _ = Brand.objects.get_or_create(
        tenant=request.tenant,
        name="Sem Marca"
    )

    for item in items:
        try:
            with transaction.atomic():
                target_product = item.matched_product
                target_variant = item.matched_variant

                # If no match, create simple product
                if not target_product and not target_variant:
                    suggestion = item.ai_suggestion or {}
                    suggested_name = suggestion.get('suggested_name', item.description)

                    target_product = Product.objects.create(
                        tenant=request.tenant,
                        name=suggested_name,
                        product_type=ProductType.SIMPLE,
                        barcode=item.ean,
                        avg_unit_cost=item.unit_cost,
                        category=cat_obj,
                        brand=brand_obj,
                        is_active=True
                    )

                # Execute Stock Movement
                StockService.create_movement(
                    tenant=request.tenant,
                    user=request.user,
                    product=target_product if not target_variant else None,
                    variant=target_variant,
                    movement_type='IN',
                    quantity=item.quantity,
                    reason=f"Aprovação em Lote (Lote {item.batch.id})",
                    unit_cost=item.unit_cost
                )

                item.status = 'DONE'
                item.processed_at = timezone.now()
                item.matched_product = target_product
                item.matched_variant = target_variant
                item.save()
                success_count += 1

        except Exception as e:
            error_count += 1
            print(f"Bulk approve error for item {item.pk}: {e}")

    if success_count > 0:
        messages.success(request, f"✅ {success_count} item(s) aprovado(s) com sucesso!")
    if error_count > 0:
        messages.warning(request, f"⚠️ {error_count} item(s) com erro durante aprovação.")

    return redirect('inventory:pending_product_list')


@login_required
@admin_required
def pending_product_bulk_reject(request):
    """Bulk reject multiple ImportItems at once"""
    from django.utils import timezone

    from .models import ImportItem

    if request.method != 'POST':
        return redirect('inventory:pending_product_list')

    item_ids = request.POST.getlist('item_ids')
    if not item_ids:
        messages.warning(request, "Nenhum item selecionado.")
        return redirect('inventory:pending_product_list')

    count = ImportItem.objects.filter(
        pk__in=item_ids,
        tenant=request.tenant,
        status='PENDING'
    ).update(status='REJECTED', processed_at=timezone.now())

    messages.info(request, f"🚫 {count} item(s) rejeitado(s).")
    return redirect('inventory:pending_product_list')

