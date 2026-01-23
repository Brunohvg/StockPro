"""
Products App Views - Product catalog CRUD (V10 - Normalized Architecture)
"""
import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.tenants.middleware import plan_limit_required, trial_allows_read

from .forms import ProductForm, ProductVariantForm
from .models import (
    AttributeType,
    Brand,
    Category,
    Product,
    ProductType,
    ProductVariant,
    VariantAttributeValue,
)

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
    view_mode = request.GET.get('view', 'table')  # table or grid

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
@plan_limit_required('products')
def product_create(request):
    """Criar novo produto (simples ou variável)"""
    tenant = request.tenant
    if request.method == 'POST':
        form = ProductForm(request.POST, request.FILES, tenant=tenant)
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
        form = ProductForm(tenant=tenant)

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
        form = ProductForm(request.POST, request.FILES, instance=product, tenant=request.tenant)
        if form.is_valid():
            form.save()
            messages.success(request, f"Produto '{product.name}' atualizado!")
            return redirect('products:product_detail', pk=product.pk)
    else:
        form = ProductForm(instance=product, tenant=request.tenant)

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
        form = ProductVariantForm(request.POST, request.FILES, tenant=request.tenant)
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
        form = ProductVariantForm(tenant=request.tenant, initial={
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
        form = ProductVariantForm(request.POST, request.FILES, instance=variant, tenant=request.tenant)
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

            messages.success(request, "Variação atualizada!")
            return redirect('products:product_detail', pk=variant.product.pk)
    else:
        form = ProductVariantForm(instance=variant, tenant=request.tenant)

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
        from apps.inventory.models import StockMovement

        if not variant.can_be_safely_deleted:
            messages.error(
                request,
                "Não é possível excluir esta variação pois existem movimentações de saída vinculadas."
            )
            return redirect('products:product_detail', pk=product_pk)

        # Excluir movimentações primeiro
        StockMovement.objects.filter(variant=variant).delete()
        variant.delete()
        messages.success(request, "Variação e suas movimentações foram removidas!")

    return redirect('products:product_detail', pk=product_pk)


@login_required
@trial_allows_read
def product_delete(request, pk):
    """
    Excluir produto com verificação de segurança.
    - Só exclui se não houver movimentações de SAÍDA (OUT)
    - Se tiver apenas entradas, exclui as movimentações junto
    """
    from apps.inventory.models import StockMovement

    product = get_object_or_404(Product, pk=pk, tenant=request.tenant)

    if request.method == 'POST':
        name = product.name

        if not product.can_be_safely_deleted:
            messages.error(
                request,
                f"Não é possível excluir '{name}' pois existem movimentações de saída vinculadas. "
                f"Desative o produto ao invés de excluí-lo."
            )
            return redirect('products:product_detail', pk=pk)

        try:
            # Excluir movimentações de entrada/ajuste primeiro
            if product.is_variable:
                for variant in product.variants.all():
                    StockMovement.objects.filter(variant=variant).delete()
            else:
                StockMovement.objects.filter(product=product).delete()

            # Agora pode excluir o produto
            product.delete()
            messages.success(request, f"Produto '{name}' e suas movimentações foram removidos com sucesso!")
            return redirect('products:product_list')

        except Exception as e:
            messages.error(request, f"Erro ao excluir: {str(e)}")
            return redirect('products:product_detail', pk=pk)

    return redirect('products:product_detail', pk=pk)

# ============== BULK DELETE ==============

@login_required
def bulk_delete(request):
    """
    Exclusão em massa de produtos selecionados.
    Só exclui produtos sem movimentações de saída.
    """
    if request.method != 'POST':
        return redirect('products:product_list')

    from apps.inventory.models import StockMovement

    product_ids = request.POST.getlist('product_ids')

    if not product_ids:
        messages.warning(request, "Nenhum produto selecionado.")
        return redirect('products:product_list')

    products = Product.objects.filter(tenant=request.tenant, pk__in=product_ids)

    deleted_count = 0
    skipped_count = 0

    for product in products:
        if product.can_be_safely_deleted:
            if product.is_variable:
                for variant in product.variants.all():
                    StockMovement.objects.filter(variant=variant).delete()
            else:
                StockMovement.objects.filter(product=product).delete()
            product.delete()
            deleted_count += 1
        else:
            skipped_count += 1

    if deleted_count > 0:
        messages.success(request, f"✅ {deleted_count} produto(s) excluído(s)!")
    if skipped_count > 0:
        messages.warning(request, f"⚠️ {skipped_count} produto(s) protegido(s) por terem saídas.")

    return redirect('products:product_list')


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
        name = request.POST.get('name', '').strip()
        if name:
            if Category.objects.filter(tenant=request.tenant, name=name).exists():
                messages.error(request, f"A categoria '{name}' já existe.")
            else:
                Category.objects.create(name=name, tenant=request.tenant)
                messages.success(request, f"Categoria '{name}' criada!")
    return redirect('products:category_brand_list')


@login_required
@trial_allows_read
def brand_create(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        if name:
            if Brand.objects.filter(tenant=request.tenant, name=name).exists():
                messages.error(request, f"A marca '{name}' já existe.")
            else:
                Brand.objects.create(name=name, tenant=request.tenant)
                messages.success(request, f"Marca '{name}' criada!")
    return redirect('products:category_brand_list')


@login_required
def attribute_type_create(request):
    """Criar novo tipo de atributo (Cor, Tamanho, etc.)"""
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        if name:
            if AttributeType.objects.filter(tenant=request.tenant, name=name).exists():
                messages.error(request, f"O atributo '{name}' já existe.")
            else:
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
@login_required
def ai_enhance_product_api(request):
    """API para preenchimento inteligente via IA baseado no nome do produto"""
    name = request.GET.get('name', '')
    if not name or len(name) < 3:
        return JsonResponse({'error': 'Nome muito curto'}, status=400)

    from apps.core.services import AIService

    prompt = f"""
    Tarefa: Enriquecer dados de um produto comercial para inventário.
    NOME DO PRODUTO: "{name}"

    Gere um JSON com os seguintes campos (em Português do Brasil):
    - description: Uma descrição EXTREMAMENTE CURTA, profissional e técnica de no MÁXIMO 2 parágrafos pequenos.
    - category_suggestion: Sugestão de categoria (Ex: Bebidas, Ferramentas, Eletrônicos).
    - brand_suggestion: Sugestão de marca caso esteja no nome.
    - tags: 3 a 5 palavras-chave.

    Retorne APENAS o JSON.
    """

    content = AIService.call_ai(prompt, schema="json")
    if not content:
        return JsonResponse({'error': 'Falha na IA'}, status=500)

    try:
        # Busca o primeiro '{' e o último '}' para extrair o objeto JSON
        start = content.find('{')
        end = content.rfind('}')
        if start != -1 and end != -1:
            json_str = content[start:end+1]
            data = json.loads(json_str)
            return JsonResponse(data)

        return JsonResponse({'error': 'JSON não encontrado na resposta'}, status=500)
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Erro ao parsear IA: {str(e)} | Content: {content}")
        return JsonResponse({'error': f'Falha ao processar: {str(e)}'}, status=500)


# ============== CONSOLIDATION VIEWS ==============

@login_required
def consolidation_suggestions(request):
    """
    Lista sugestões de consolidação de produtos SIMPLES em VARIÁVEIS.
    Detecta padrões como 'AMIGURUMI - COR 6006' e sugere agrupamento.
    """
    from .services import ConsolidationService

    service = ConsolidationService(request.tenant)
    candidates = service.detect_candidates()

    return render(request, 'products/consolidation_suggestions.html', {
        'candidates': candidates,
        'total_candidates': len(candidates),
        'total_products': sum(c['count'] for c in candidates),
    })


@login_required
def consolidation_execute(request):
    """
    Executa a consolidação de produtos selecionados.
    POST com: parent_name, attribute, product_ids[]
    """
    if request.method != 'POST':
        return redirect('products:consolidation_suggestions')

    from .services import ConsolidationService

    parent_name = request.POST.get('parent_name', '').strip()
    attribute = request.POST.get('attribute', 'Cor').strip()
    product_ids = request.POST.getlist('product_ids')

    if not parent_name or len(product_ids) < 2:
        messages.error(request, "Selecione pelo menos 2 produtos e informe o nome do produto pai.")
        return redirect('products:consolidation_suggestions')

    try:
        service = ConsolidationService(request.tenant)
        parent = service.consolidate(parent_name, attribute, product_ids)

        messages.success(
            request,
            f"✅ Consolidação realizada! '{parent_name}' agora tem {len(product_ids)} variações."
        )
        return redirect('products:product_detail', pk=parent.pk)

    except Exception as e:
        messages.error(request, f"Erro na consolidação: {str(e)}")
        return redirect('products:consolidation_suggestions')
