"""
Products App Views - Product catalog CRUD (V10 - Normalized Architecture)
"""
import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.tenants.middleware import admin_required, plan_limit_required, trial_allows_read

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

    status_filter = request.GET.get('status', '')  # '' ativos | archived | all
    if status_filter == 'archived':
        products = products.filter(is_active=False)
    elif status_filter != 'all':
        products = products.filter(is_active=True)

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
        'status_filter': status_filter,
        'archived_count': Product.objects.filter(tenant=tenant, is_active=False).count(),
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
            from apps.core.services import StockService
            initial_stock = form.cleaned_data.get('current_stock') or 0
            product = form.save(commit=False)
            product.tenant = tenant
            # O saldo da variante so pode ser alterado pelo ledger.
            product.current_stock = 0
            try:
                with transaction.atomic():
                    product.save()
                    if product.is_simple and initial_stock > 0:
                        StockService.create_movement(
                            tenant, request.user, 'IN', initial_stock,
                            product=product, source='MANUAL', reason='Estoque inicial no cadastro',
                            unit_cost=form.cleaned_data.get('avg_unit_cost'),
                            lot_number=form.cleaned_data.get('initial_lot_number'),
                            expiry_date=form.cleaned_data.get('initial_expiry_date'),
                            manufacture_date=form.cleaned_data.get('initial_manufacture_date'),
                        )
            except ValueError as exc:
                form.add_error(None, str(exc))
            else:
                messages.success(request, f"Produto '{product.name}' criado com sucesso!")
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
    from apps.inventory.models import StockLot
    context['lots'] = StockLot.objects.filter(
        tenant=request.tenant, variant__product=product, quantity__gt=0
    ).select_related('variant')
    return render(request, 'products/product_detail.html', context)


@login_required
@trial_allows_read
@plan_limit_required('products')
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


def _zero_stock_requested(request):
    # Checkbox "zerar saldo" vem marcado por padrão no formulário
    return request.POST.get('zero_stock', 'off') in ('on', '1', 'true')


@login_required
@admin_required
@trial_allows_read
def variant_delete(request, pk):
    """Exclui a variação sem movimentações; com histórico, arquiva."""
    from .services import ProductArchiveService

    variant = get_object_or_404(ProductVariant, pk=pk, tenant=request.tenant)
    product_pk = variant.product.pk

    if request.method == 'POST':
        try:
            result = ProductArchiveService.remove_variant(
                variant, request.user, zero_stock=_zero_stock_requested(request))
        except ValueError as e:
            messages.error(request, f"Não foi possível arquivar: {e}")
            return redirect('products:product_detail', pk=product_pk)
        if result == 'deleted':
            messages.success(request, "Variação excluída (não tinha movimentações).")
        else:
            messages.success(request, "Variação arquivada. O histórico de movimentações foi preservado.")

    return redirect('products:product_detail', pk=product_pk)


@login_required
@admin_required
@trial_allows_read
def product_delete(request, pk):
    """
    Remove um produto sem apagar histórico:
    - sem nenhuma movimentação: exclui de vez;
    - com movimentações: arquiva (e zera o saldo com ajuste registrado, se marcado).
    """
    from .services import ProductArchiveService

    product = get_object_or_404(Product, pk=pk, tenant=request.tenant)

    if request.method == 'POST':
        name = product.name
        try:
            result = ProductArchiveService.remove_product(
                product, request.user, zero_stock=_zero_stock_requested(request))
        except ValueError as e:
            messages.error(request, f"Não foi possível arquivar '{name}': {e}")
            return redirect('products:product_detail', pk=pk)
        if result == 'deleted':
            messages.success(request, f"Produto '{name}' excluído (não tinha movimentações).")
            return redirect('products:product_list')
        messages.success(
            request,
            f"Produto '{name}' arquivado. O histórico foi preservado e ele pode ser reativado em Produtos > Arquivados.")
        return redirect('products:product_detail', pk=pk)

    return redirect('products:product_detail', pk=pk)


@login_required
@admin_required
@trial_allows_read
def product_restore(request, pk):
    """Reativa um produto arquivado (respeita o limite do plano)."""
    from .services import ArchiveError, ProductArchiveService

    product = get_object_or_404(Product, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        try:
            ProductArchiveService.restore_product(product)
            messages.success(request, f"Produto '{product.name}' reativado.")
        except ArchiveError as e:
            messages.error(request, str(e))
    return redirect('products:product_detail', pk=pk)

# ============== BULK DELETE ==============

@login_required
@admin_required
@trial_allows_read
def bulk_delete(request):
    """
    Remoção em massa: exclui os produtos sem movimentações e arquiva os demais.
    """
    if request.method != 'POST':
        return redirect('products:product_list')

    from .services import ProductArchiveService

    product_ids = request.POST.getlist('product_ids')

    if not product_ids:
        messages.warning(request, "Nenhum produto selecionado.")
        return redirect('products:product_list')

    products = Product.objects.filter(tenant=request.tenant, pk__in=product_ids, is_active=True)
    zero_stock = _zero_stock_requested(request)

    counts = {'deleted': 0, 'archived': 0}
    failed = []
    for product in products:
        try:
            counts[ProductArchiveService.remove_product(product, request.user, zero_stock=zero_stock)] += 1
        except ValueError as e:
            failed.append(f"{product.name}: {e}")

    if counts['deleted']:
        messages.success(request, f"{counts['deleted']} produto(s) sem movimentações excluído(s).")
    if counts['archived']:
        messages.success(request, f"{counts['archived']} produto(s) com histórico arquivado(s).")
    for msg in failed[:5]:
        messages.error(request, msg)

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
@trial_allows_read
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
@admin_required
def category_delete(request, pk):
    cat = get_object_or_404(Category, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        cat.delete()
        messages.success(request, "Categoria removida.")
    return redirect('products:category_brand_list')


@login_required
@admin_required
def brand_delete(request, pk):
    brand = get_object_or_404(Brand, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        brand.delete()
        messages.success(request, "Marca removida.")
    return redirect('products:category_brand_list')


@login_required
@admin_required
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
        is_active=True,
        product__is_active=True,
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
    from apps.core.services import AIService, AIUnavailable

    try:
        AIService.check_tenant_access(request.tenant)
    except AIUnavailable as e:
        return JsonResponse({'error': str(e)}, status=e.status)
    name = request.GET.get('name', '')
    if not name or len(name) < 3:
        return JsonResponse({'error': 'Nome muito curto'}, status=400)

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

    try:
        content = AIService.call_for_tenant(request.tenant, prompt, schema="json")
    except AIUnavailable as e:
        return JsonResponse({'error': str(e)}, status=e.status)
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
@admin_required
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


