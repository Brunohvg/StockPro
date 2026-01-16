"""
Products App Views - Product catalog CRUD (V10 - Normalized Architecture)
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q, Sum, Count
from django.http import JsonResponse
from django.core.paginator import Paginator

from .models import Product, ProductVariant, Category, Brand, AttributeType, VariantAttributeValue, ProductType
from .forms import ProductForm, ProductVariantForm, QuickVariantForm, AttributeTypeForm
from apps.tenants.middleware import trial_allows_read

ITEMS_PER_PAGE = 24  # Grid friendly (divisible by 2, 3, 4)


@login_required
def product_list(request):
    """Lista de produtos com paginação e filtros"""
    tenant = request.tenant
    products = Product.objects.filter(tenant=tenant).select_related('category', 'brand').prefetch_related('variants').order_by('name')

    query = request.GET.get('q', '')
    category = request.GET.get('category', '')
    product_type = request.GET.get('type', '')
    stock_filter = request.GET.get('stock', '')
    view_mode = request.GET.get('view', 'grid')  # grid or table

    if query:
        products = products.filter(
            Q(sku__icontains=query) |
            Q(name__icontains=query) |
            Q(description__icontains=query)
        )
    if category:
        products = products.filter(category_id=category)
    if product_type:
        products = products.filter(product_type=product_type)
    if stock_filter == 'low':
        products = products.filter(
            Q(product_type=ProductType.SIMPLE, current_stock__lte=10) |
            Q(product_type=ProductType.VARIABLE, variants__current_stock__lte=10)
        ).distinct()
    elif stock_filter == 'out':
        products = products.filter(
            Q(product_type=ProductType.SIMPLE, current_stock=0) |
            Q(product_type=ProductType.VARIABLE, variants__current_stock=0)
        ).distinct()

    # Pagination
    paginator = Paginator(products, ITEMS_PER_PAGE)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    categories = Category.objects.filter(tenant=tenant).order_by('name')
    brands = Brand.objects.filter(tenant=tenant).order_by('name')

    # Stats
    total_count = products.count()

    return render(request, 'products/product_list.html', {
        'products': page_obj,
        'page_obj': page_obj,
        'categories': categories,
        'brands': brands,
        'search_query': query,
        'selected_category': category,
        'selected_type': product_type,
        'stock_filter': stock_filter,
        'view_mode': view_mode,
        'total_count': total_count,
        'ProductType': ProductType,
    })


@login_required
@trial_allows_read
def product_create(request):
    """Criar novo produto (simples ou variável)"""
    tenant = request.tenant
    if request.method == 'POST':
        form = ProductForm(request.POST, request.FILES)
        if form.is_valid():
            product = form.save(commit=False)
            product.tenant = tenant
            product.save()
            messages.success(request, f"Produto '{product.name}' criado com sucesso!")

            # Se for variável, redireciona para adicionar variações
            if product.is_variable:
                return redirect('products:product_detail', pk=product.pk)
            return redirect('products:product_list')
    else:
        form = ProductForm()

    return render(request, 'products/product_form.html', {
        'form': form,
        'is_edit': False,
        'title': 'Novo Produto'
    })


@login_required
@trial_allows_read
def product_edit(request, pk):
    """Editar produto existente"""
    product = get_object_or_404(Product, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        form = ProductForm(request.POST, request.FILES, instance=product)
        if form.is_valid():
            form.save()
            messages.success(request, f"Produto '{product.name}' atualizado!")
            return redirect('products:product_detail', pk=product.pk)
    else:
        form = ProductForm(instance=product)

    return render(request, 'products/product_form.html', {
        'form': form,
        'is_edit': True,
        'product': product,
        'title': f'Editar: {product.name}'
    })


@login_required
def product_detail(request, pk):
    """Detalhes do produto com variações (se variável)"""
    from apps.inventory.models import StockMovement

    product = get_object_or_404(
        Product.objects.select_related('category', 'brand').prefetch_related(
            'variants__attribute_values__attribute_type'
        ),
        pk=pk,
        tenant=request.tenant
    )

    # Movimentações do produto (para simples) ou consolidadas (para variável)
    if product.is_simple:
        movements = StockMovement.objects.filter(
            product=product,
            tenant=request.tenant
        ).select_related('user').order_by('-created_at')[:50]
    else:
        # Para variável, mostra movimentações de todas as variantes
        variant_ids = product.variants.values_list('id', flat=True)
        movements = StockMovement.objects.filter(
            variant_id__in=variant_ids,
            tenant=request.tenant
        ).select_related('user', 'variant').order_by('-created_at')[:50]

    # Tipos de atributo disponíveis para novas variações
    attribute_types = AttributeType.objects.filter(tenant=request.tenant)

    context = {
        'product': product,
        'movements': movements,
        'variants': product.variants.all() if product.is_variable else None,
        'attribute_types': attribute_types,
        'ProductType': ProductType,
    }
    return render(request, 'products/product_detail.html', context)


@login_required
@trial_allows_read
def variant_create(request, product_pk):
    """Criar nova variação para um produto variável"""
    product = get_object_or_404(Product, pk=product_pk, tenant=request.tenant, product_type=ProductType.VARIABLE)
    attribute_types = AttributeType.objects.filter(tenant=request.tenant)

    if request.method == 'POST':
        form = ProductVariantForm(request.POST, request.FILES)
        if form.is_valid():
            variant = form.save(commit=False)
            variant.product = product
            variant.tenant = request.tenant
            variant.save()

            # Processar atributos
            for attr_type in attribute_types:
                value = request.POST.get(f'attr_{attr_type.id}')
                if value:
                    VariantAttributeValue.objects.create(
                        variant=variant,
                        attribute_type=attr_type,
                        value=value.strip()
                    )

            messages.success(request, f"Variação '{variant.display_name}' adicionada!")
            return redirect('products:product_detail', pk=product.pk)
    else:
        form = ProductVariantForm(initial={
            'name': f"{product.name} - ",
            'avg_unit_cost': product.avg_unit_cost
        })

    return render(request, 'products/variant_form.html', {
        'form': form,
        'product': product,
        'attribute_types': attribute_types,
        'title': f'Nova Variação: {product.name}'
    })


@login_required
@trial_allows_read
def variant_edit(request, pk):
    """Editar variação existente"""
    variant = get_object_or_404(ProductVariant, pk=pk, tenant=request.tenant)
    attribute_types = AttributeType.objects.filter(tenant=request.tenant)

    if request.method == 'POST':
        form = ProductVariantForm(request.POST, request.FILES, instance=variant)
        if form.is_valid():
            form.save()

            # Atualizar atributos
            for attr_type in attribute_types:
                value = request.POST.get(f'attr_{attr_type.id}')
                attr_value, created = VariantAttributeValue.objects.get_or_create(
                    variant=variant,
                    attribute_type=attr_type,
                    defaults={'value': value.strip() if value else ''}
                )
                if not created and value:
                    attr_value.value = value.strip()
                    attr_value.save()

            messages.success(request, f"Variação atualizada!")
            return redirect('products:product_detail', pk=variant.product.pk)
    else:
        form = ProductVariantForm(instance=variant)

    # Pré-carregar valores de atributos
    attr_values = {av.attribute_type_id: av.value for av in variant.attribute_values.all()}

    return render(request, 'products/variant_form.html', {
        'form': form,
        'product': variant.product,
        'variant': variant,
        'attribute_types': attribute_types,
        'attr_values': attr_values,
        'title': f'Editar: {variant.display_name}'
    })


@login_required
@trial_allows_read
def variant_delete(request, pk):
    """Excluir variação"""
    variant = get_object_or_404(ProductVariant, pk=pk, tenant=request.tenant)
    product_pk = variant.product.pk

    if request.method == 'POST':
        variant.delete()
        messages.success(request, "Variação removida.")

    return redirect('products:product_detail', pk=product_pk)


@login_required
@trial_allows_read
def product_delete(request, pk):
    """Excluir produto (e todas as variações)"""
    product = get_object_or_404(Product, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        name = product.name
        product.delete()
        messages.success(request, f"Produto '{name}' removido.")
        return redirect('products:product_list')
    return redirect('products:product_detail', pk=pk)


# ============== CATEGORIAS E MARCAS ==============

@login_required
def category_brand_list(request):
    """Lista de categorias, marcas e tipos de atributo"""
    tenant = request.tenant
    categories = Category.objects.filter(tenant=tenant).order_by('name')
    brands = Brand.objects.filter(tenant=tenant).order_by('name')
    attribute_types = AttributeType.objects.filter(tenant=tenant).order_by('name')

    return render(request, 'products/category_brand_list.html', {
        'categories': categories,
        'brands': brands,
        'attribute_types': attribute_types
    })


@login_required
@trial_allows_read
def category_create(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        if name:
            Category.objects.create(name=name, tenant=request.tenant)
            messages.success(request, f"Categoria '{name}' criada!")
    return redirect('products:category_brand_list')


@login_required
@trial_allows_read
def brand_create(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        if name:
            Brand.objects.create(name=name, tenant=request.tenant)
            messages.success(request, f"Marca '{name}' criada!")
    return redirect('products:category_brand_list')


@login_required
def attribute_type_create(request):
    """Criar novo tipo de atributo (Cor, Tamanho, etc.)"""
    if request.method == 'POST':
        name = request.POST.get('name')
        if name:
            AttributeType.objects.create(name=name, tenant=request.tenant)
            messages.success(request, f"Atributo '{name}' criado!")
    return redirect('products:category_brand_list')


@login_required
def category_delete(request, pk):
    cat = get_object_or_404(Category, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        cat.delete()
        messages.success(request, "Categoria removida.")
    return redirect('products:category_brand_list')


@login_required
def brand_delete(request, pk):
    brand = get_object_or_404(Brand, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        brand.delete()
        messages.success(request, "Marca removida.")
    return redirect('products:category_brand_list')


@login_required
def attribute_type_delete(request, pk):
    attr = get_object_or_404(AttributeType, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        attr.delete()
        messages.success(request, "Tipo de atributo removido.")
    return redirect('products:category_brand_list')


# ============== API HELPERS ==============

@login_required
def product_search_api(request):
    """API para busca rápida de produtos/variantes (autocomplete)"""
    query = request.GET.get('q', '')
    tenant = request.tenant

    results = []

    # Buscar produtos simples
    products = Product.objects.filter(
        tenant=tenant,
        product_type=ProductType.SIMPLE,
        is_active=True
    ).filter(
        Q(sku__icontains=query) |
        Q(name__icontains=query) |
        Q(barcode__icontains=query)
    )[:10]

    for p in products:
        results.append({
            'type': 'product',
            'id': p.id,
            'sku': p.sku,
            'name': p.name,
            'stock': p.current_stock,
            'display': f"{p.name} (SKU: {p.sku})"
        })

    # Buscar variantes
    variants = ProductVariant.objects.filter(
        tenant=tenant,
        is_active=True
    ).filter(
        Q(sku__icontains=query) |
        Q(name__icontains=query) |
        Q(barcode__icontains=query) |
        Q(product__name__icontains=query)
    ).select_related('product')[:10]

    for v in variants:
        results.append({
            'type': 'variant',
            'id': v.id,
            'sku': v.sku,
            'name': v.display_name,
            'stock': v.current_stock,
            'display': f"{v.display_name} (SKU: {v.sku})"
        })

    return JsonResponse({'results': results})
