"""
Category and Brand views
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages

from ..models import Category, Brand


@login_required
def category_brand_list(request):
    """Unified view to manage categories and brands"""
    tenant = request.tenant
    categories = Category.objects.filter(tenant=tenant).order_by('name')
    brands = Brand.objects.filter(tenant=tenant).order_by('name')
    return render(request, 'core/category_brand_list.html', {
        'categories': categories,
        'brands': brands,
    })


@login_required
def category_create(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        if name:
            Category.objects.create(name=name, tenant=request.tenant)
            messages.success(request, f"Categoria '{name}' criada!")
    return redirect('category_brand_list')


@login_required
def brand_create(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        if name:
            Brand.objects.create(name=name, tenant=request.tenant)
            messages.success(request, f"Marca '{name}' criada!")
    return redirect('category_brand_list')


@login_required
def category_delete(request, pk):
    cat = get_object_or_404(Category, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        cat.delete()
        messages.success(request, "Categoria removida.")
    return redirect('category_brand_list')


@login_required
def brand_delete(request, pk):
    brand = get_object_or_404(Brand, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        brand.delete()
        messages.success(request, "Marca removida.")
    return redirect('category_brand_list')
