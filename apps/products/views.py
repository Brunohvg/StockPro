"""
Products App Views - Product catalog CRUD
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q

from .models import Product, Category, Brand
from .forms import ProductForm


@login_required
def product_list(request):
    tenant = request.tenant
    products = Product.objects.filter(tenant=tenant).select_related('category', 'brand').order_by('name')

    query = request.GET.get('q', '')
    category = request.GET.get('category', '')
    stock_filter = request.GET.get('stock', '')

    if query:
        products = products.filter(
            Q(sku__icontains=query) |
            Q(name__icontains=query) |
            Q(description__icontains=query)
        )
    if category:
        products = products.filter(category_id=category)
    if stock_filter == 'low':
        products = products.filter(current_stock__lte=10)
    elif stock_filter == 'out':
        products = products.filter(current_stock=0)

    categories = Category.objects.filter(tenant=tenant).order_by('name')
    brands = Brand.objects.filter(tenant=tenant).order_by('name')

    return render(request, 'products/product_list.html', {
        'products': products,
        'categories': categories,
        'brands': brands,
        'search_query': query,
        'selected_category': category,
        'stock_filter': stock_filter,
    })


@login_required
def product_create(request):
    tenant = request.tenant
    if request.method == 'POST':
        form = ProductForm(request.POST)
        if form.is_valid():
            product = form.save(commit=False)
            product.tenant = tenant
            product.save()
            messages.success(request, f"Produto '{product.name}' criado com sucesso!")
            return redirect('products:product_list')
    else:
        form = ProductForm()
    return render(request, 'products/product_form.html', {'form': form, 'is_edit': False})


@login_required
def product_edit(request, pk):
    product = get_object_or_404(Product, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        form = ProductForm(request.POST, instance=product)
        if form.is_valid():
            form.save()
            messages.success(request, f"Produto '{product.name}' atualizado!")
            return redirect('products:product_list')
    else:
        form = ProductForm(instance=product)
    return render(request, 'products/product_form.html', {'form': form, 'is_edit': True, 'product': product})


@login_required
def product_detail(request, pk):
    from apps.inventory.models import StockMovement
    product = get_object_or_404(Product.objects.select_related('category', 'brand'), pk=pk, tenant=request.tenant)
    movements = StockMovement.objects.filter(product=product, tenant=request.tenant).select_related('user').order_by('-created_at')
    return render(request, 'products/product_detail.html', {'product': product, 'movements': movements[:50]})


@login_required
def product_delete(request, pk):
    product = get_object_or_404(Product, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        name = product.name
        product.delete()
        messages.success(request, f"Produto '{name}' removido.")
        return redirect('products:product_list')
    return redirect('products:product_detail', pk=pk)


@login_required
def category_brand_list(request):
    tenant = request.tenant
    categories = Category.objects.filter(tenant=tenant).order_by('name')
    brands = Brand.objects.filter(tenant=tenant).order_by('name')
    return render(request, 'products/category_brand_list.html', {'categories': categories, 'brands': brands})


@login_required
def category_create(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        if name:
            Category.objects.create(name=name, tenant=request.tenant)
            messages.success(request, f"Categoria '{name}' criada!")
    return redirect('products:category_brand_list')


@login_required
def brand_create(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        if name:
            Brand.objects.create(name=name, tenant=request.tenant)
            messages.success(request, f"Marca '{name}' criada!")
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
