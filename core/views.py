from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth import login
from django.db import models, transaction
from django.db.models import Q, F, Sum, Count, Avg, Case, When, Value, DecimalField
from django.contrib import messages
from django.contrib.auth.models import User
from django.utils import timezone
from .models import Product, StockMovement, Category, Brand, ImportBatch, SystemSetting, Tenant, UserProfile, Plan
from .forms import ProductForm, ImportBatchForm, EmployeeForm, SystemSettingForm
from .services import StockService


def landing_page(request):
    """Public landing page with plans and features"""
    plans = Plan.objects.all().order_by('price')
    features = [
        {'icon': 'smartphone', 'title': 'Operação Mobile', 'description': 'Escaneie códigos de barras direto do celular para entradas e saídas.'},
        {'icon': 'bar-chart-2', 'title': 'Business Intelligence', 'description': 'Gráficos de tendência, Curva ABC e composição de valor por categoria.'},
        {'icon': 'building-2', 'title': 'Multi-Empresa', 'description': 'Gerencie várias unidades de negócio com isolamento total de dados.'},
        {'icon': 'upload-cloud', 'title': 'Importação XML/CSV', 'description': 'Importe produtos e notas fiscais eletrônicas automaticamente.'},
        {'icon': 'shield-check', 'title': 'Auditoria Completa', 'description': 'Histórico imutável de todas as movimentações com rastreio de usuário.'},
        {'icon': 'settings', 'title': 'Configurações Flexíveis', 'description': 'Personalize alertas, regras de estoque e identidade visual.'},
    ]
    return render(request, 'core/landing.html', {'plans': plans, 'features': features})


@transaction.atomic
def signup_view(request):
    """Self-service signup that creates Tenant + User"""
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        company_name = request.POST.get('company_name', '').strip()
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        plan_name = request.GET.get('plan', 'FREE')

        errors = {}
        if not company_name:
            errors['company_name'] = 'Nome da empresa é obrigatório.'
        if not email:
            errors['email'] = 'E-mail é obrigatório.'
        if User.objects.filter(email=email).exists():
            errors['email'] = 'Este e-mail já está cadastrado.'
        if len(password) < 6:
            errors['password'] = 'Senha deve ter pelo menos 6 caracteres.'

        if errors:
            return render(request, 'registration/signup.html', {'form': {'errors': errors}})

        # Get or create the plan
        plan, _ = Plan.objects.get_or_create(name=plan_name, defaults={'display_name': plan_name.title(), 'price': 0})

        # Get CNPJ (optional field)
        cnpj = request.POST.get('cnpj', '').strip() or None

        # Create Tenant
        tenant = Tenant.objects.create(name=company_name, cnpj=cnpj, plan=plan)

        # Create User
        username = email.split('@')[0][:30]
        if User.objects.filter(username=username).exists():
            username = f"{username}_{tenant.pk}"
        user = User.objects.create_user(username=username, email=email, password=password, first_name=first_name, last_name=last_name, is_staff=True)

        # Link User to Tenant
        UserProfile.objects.create(user=user, tenant=tenant)

        # Create default SystemSetting for the tenant
        SystemSetting.objects.create(tenant=tenant, company_name=company_name)

        # Auto-login
        login(request, user)
        messages.success(request, f"Bem-vindo ao StockPro, {first_name}! Sua empresa '{company_name}' está pronta.")
        return redirect('dashboard')

    return render(request, 'registration/signup.html', {})


@login_required
def dashboard(request):
    tenant = request.tenant
    products = Product.objects.filter(tenant=tenant)
    total_products = products.count()
    low_stock_qs = products.filter(current_stock__lte=F('minimum_stock'))
    low_stock = low_stock_qs.count()

    # Valuation and daily movements
    total_value = products.aggregate(
        total=Sum(F('current_stock') * F('avg_unit_cost'), output_field=models.DecimalField())
    )['total'] or 0

    today = timezone.now().date()
    total_movements_today = StockMovement.objects.filter(tenant=tenant, created_at__date=today).count()

    recent_movements = StockMovement.objects.filter(tenant=tenant).select_related('product', 'user').order_by('-created_at')[:10]

    # Analytics grouping
    # Distribution Stats (Normalized V5)
    brand_stats = products.values('brand__name').annotate(
        count=Count('id'),
        total_qty=Sum('current_stock')
    ).exclude(brand__isnull=True).order_by('-total_qty')[:5]

    category_stats = products.values('category__name').annotate(
        count=Count('id'),
        total_qty=Sum('current_stock')
    ).exclude(category__isnull=True).order_by('-total_qty')[:5]

    context = {
        'total_products': total_products,
        'low_stock': low_stock,
        'low_stock_products': low_stock_qs[:5],
        'total_value': total_value,
        'total_movements_today': total_movements_today,
        'recent_movements': recent_movements,
        'brand_stats': brand_stats,
        'category_stats': category_stats,
    }
    return render(request, 'core/dashboard.html', context)

@login_required
def product_list(request):
    tenant = request.tenant
    query = request.GET.get('q', '')
    category_val = request.GET.get('category', '')
    brand_val = request.GET.get('brand', '')

    products = Product.objects.filter(tenant=tenant).select_related('category', 'brand').order_by('name')

    # Simple Filters
    if query:
        products = products.filter(
            Q(sku__icontains=query) |
            Q(name__icontains=query) |
            Q(brand__name__icontains=query) |
            Q(category__name__icontains=query)
        )
    if category_val:
        products = products.filter(category=category_val)
    if brand_val:
        products = products.filter(brand=brand_val)

    # Get unique lists for filter dropdowns (Normalized V5)
    categories = Category.objects.filter(tenant=tenant).order_by('name')
    brands = Brand.objects.filter(tenant=tenant).order_by('name')

    context = {
        'products': products,
        'categories': categories,
        'brands': brands,
        'current_category': category_val,
        'current_brand': brand_val,
        'search_query': query
    }

    if request.htmx:
        if request.GET.get('mobile'):
            return render(request, 'core/partials/mobile_search_results.html', context)
        return render(request, 'core/partials/product_table.html', context)

    return render(request, 'core/product_list.html', context)

@login_required
def product_create(request):
    tenant = request.tenant
    if request.method == 'POST':
        form = ProductForm(request.POST)
        if form.is_valid():
            product = form.save(commit=False)
            product.tenant = tenant
            product.save()
            messages.success(request, 'Produto cadastrado com sucesso!')
            return redirect('product_list')
    else:
        form = ProductForm()
    return render(request, 'core/product_form.html', {'form': form, 'title': 'Novo Produto'})

@login_required
def product_edit(request, pk):
    product = get_object_or_404(Product, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        form = ProductForm(request.POST, instance=product)
        if form.is_valid():
            form.save()
            messages.success(request, 'Produto atualizado com sucesso!')
            return redirect('product_list')
    else:
        form = ProductForm(instance=product)
    return render(request, 'core/product_form.html', {'form': form, 'title': f'Editar {product.sku}'})

@login_required
def product_detail(request, pk):
    product = get_object_or_404(Product.objects.select_related('category', 'brand'), pk=pk, tenant=request.tenant)
    movements = StockMovement.objects.filter(product=product, tenant=request.tenant).select_related('user').order_by('-created_at')

    # Simple history stats
    total_in = movements.filter(type='IN').aggregate(total=Sum('quantity'))['total'] or 0
    total_out = movements.filter(type='OUT').aggregate(total=Sum('quantity'))['total'] or 0

    return render(request, 'core/product_detail.html', {
        'product': product,
        'movements': movements[:50],
        'total_in': total_in,
        'total_out': total_out
    })

@login_required
def product_delete(request, pk):
    product = get_object_or_404(Product, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        product.delete()
        messages.success(request, f"Produto '{product.sku}' removido permanentemente.")
    return redirect('product_list')

@login_required
def create_movement(request):
    tenant = request.tenant
    products = Product.objects.filter(tenant=tenant, is_active=True).order_by('name')

    if request.method == 'POST':
        product_sku = request.POST.get('product')
        movement_type = request.POST.get('type')
        quantity = int(request.POST.get('quantity', 0))
        reason = request.POST.get('reason')

        try:
            StockService.create_movement(
                user=request.user,
                product_sku=product_sku,
                movement_type=movement_type,
                quantity=quantity,
                reason=reason,
                source='MANUAL',
                source_doc=f"Manual User: {request.user.username}"
            )
            messages.success(request, "Movimentação registrada com sucesso!")
            return redirect('dashboard')
        except Exception as e:
            messages.error(request, f"Erro ao registrar: {str(e)}")

    return render(request, 'core/movement_form.html', {'products': products})

@login_required
def movement_list(request):
    tenant = request.tenant
    movements = StockMovement.objects.filter(tenant=tenant).select_related('product', 'user').order_by('-created_at')

    # Simple search
    query = request.GET.get('q', '')
    if query:
        movements = movements.filter(
            Q(product__sku__icontains=query) |
            Q(product__name__icontains=query) |
            Q(user__username__icontains=query) |
            Q(reason__icontains=query)
        )

    return render(request, 'core/movement_list.html', {
        'movements': movements[:100],
        'search_query': query
    })


@login_required
def create_movement_mobile(request):
    """Specific view for mobile devices with focused UX"""
    if request.method == 'POST':
        product_sku = request.POST.get('product')
        movement_type = request.POST.get('type')
        quantity = int(request.POST.get('quantity', 0))

        try:
            StockService.create_movement(
                user=request.user,
                product_sku=product_sku,
                movement_type=movement_type,
                quantity=quantity,
                reason="Lançamento Mobile",
                source='MOBILE',
                source_doc=f"Mobile Operador: {request.user.username}"
            )
            messages.success(request, f"{movement_type} de {quantity} registrado!")
            return redirect('create_movement_mobile')
        except Exception as e:
            messages.error(request, f"Erro: {str(e)}")

    return render(request, 'core/movement_mobile.html')

@login_required
def import_list(request):
    tenant = request.tenant
    imports = ImportBatch.objects.filter(tenant=tenant).order_by('-created_at')

    # Calculate stats for the template
    completed_count = imports.filter(status='COMPLETED').count()
    error_count = imports.filter(status='ERROR').count()

    return render(request, 'core/import_list.html', {
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

            from .tasks import process_import_task
            process_import_task.delay(batch.id)
            messages.info(request, "Arquivo enviado! O processamento iniciará em segundo plano.")

            return redirect('import_list')
    else:
        form = ImportBatchForm()
    return render(request, 'core/import_form.html', {'form': form})

@login_required
def employee_list(request):
    employees = User.objects.all().order_by('username')
    return render(request, 'core/employee_list.html', {'employees': employees})

@login_required
def employee_create(request):
    if request.method == 'POST':
        form = EmployeeForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Funcionário cadastrado com sucesso!')
            return redirect('employee_list')
    else:
        form = EmployeeForm()
    return render(request, 'core/employee_form.html', {'form': form})

@login_required
def delete_import(request, pk):
    batch = get_object_or_404(ImportBatch, pk=pk)
    if request.method == 'POST':
        batch.delete()
        messages.success(request, "Lote de importação removido com sucesso.")
    return redirect('import_list')

@login_required
def import_detail(request, pk):
    batch = get_object_or_404(ImportBatch, pk=pk)
    return render(request, 'core/import_detail.html', {'batch': batch})

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

def employee_detail(request, user_id):
    employee = get_object_or_404(User, id=user_id)
    movements = StockMovement.objects.filter(tenant=request.tenant, user=employee).order_by('-created_at')[:50]
    return render(request, 'core/employee_detail.html', {'employee': employee, 'movements': movements})


@login_required
def inventory_reports(request):
    """Business Intelligence View with Chart.js data"""
    tenant = request.tenant
    # 1. Composition by Category (Value)
    category_qs = Category.objects.filter(tenant=tenant).annotate(
        total_value=Sum(F('products__current_stock') * F('products__avg_unit_cost'), output_field=models.DecimalField())
    ).values('name', 'total_value').order_by('-total_value')

    # 2. Daily Movement Trend (Last 15 days)
    end_date = timezone.now().date()
    start_date = end_date - timezone.timedelta(days=14)

    movements_trend = list(StockMovement.objects.filter(
        tenant=tenant,
        created_at__date__range=[start_date, end_date]
    ).values('created_at__date', 'type').annotate(
        total_qty=Sum('quantity')
    ).order_by('created_at__date'))

    # 3. ABC Analysis (Simplified: Top 10 by Stock Value)
    top_products = Product.objects.filter(tenant=tenant).annotate(
        stock_value=F('current_stock') * F('avg_unit_cost')
    ).order_by('-stock_value')[:10]

    return render(request, 'core/reports.html', {
        'category_labels': [c['name'] for c in category_qs if c['total_value']],
        'category_values': [float(c['total_value'] or 0) for c in category_qs if c['total_value']],
        'top_products': top_products,
        'movements_trend': movements_trend,
    })

@login_required
def system_settings(request):
    """Global system configuration"""
    tenant = request.tenant
    settings_obj = SystemSetting.get_settings(tenant)
    if request.method == 'POST':
        form = SystemSettingForm(request.POST, instance=settings_obj)
        if form.is_valid():
            form.save()
            messages.success(request, "Configurações globais atualizadas.")
            return redirect('system_settings')
    else:
        form = SystemSettingForm(instance=settings_obj)

    return render(request, 'core/settings_form.html', {'form': form, 'settings': settings_obj})


# ===========================================
# BILLING & PLAN MANAGEMENT
# ===========================================

@login_required
def billing_view(request):
    """View current plan and upgrade options"""
    tenant = request.tenant
    plans = Plan.objects.all().order_by('price')
    current_plan = tenant.plan if tenant else None

    return render(request, 'core/billing.html', {
        'tenant': tenant,
        'current_plan': current_plan,
        'plans': plans,
    })


@login_required
def billing_upgrade(request, plan_id):
    """Upgrade tenant to a new plan"""
    if request.method == 'POST':
        tenant = request.tenant
        new_plan = get_object_or_404(Plan, pk=plan_id)

        # Update tenant plan
        tenant.plan = new_plan
        tenant.subscription_status = 'ACTIVE'
        tenant.save()

        messages.success(request, f"Plano atualizado para {new_plan.display_name}!")
        return redirect('billing')

    return redirect('billing')


# ===========================================
# ADMIN PANEL (Superuser Only)
# ===========================================

@login_required
def admin_panel_view(request):
    """Admin panel for managing all tenants - superuser only"""
    if not request.user.is_superuser:
        messages.error(request, "Acesso restrito a administradores.")
        return redirect('dashboard')

    tenants = Tenant.objects.select_related('plan').order_by('-created_at')
    plans = Plan.objects.all().order_by('price')

    # Filters
    q = request.GET.get('q', '')
    status = request.GET.get('status', '')
    plan_filter = request.GET.get('plan', '')

    if q:
        tenants = tenants.filter(Q(name__icontains=q) | Q(cnpj__icontains=q))
    if status:
        tenants = tenants.filter(subscription_status=status)
    if plan_filter:
        tenants = tenants.filter(plan_id=plan_filter)

    # Stats
    active_count = Tenant.objects.filter(subscription_status='ACTIVE').count()
    trial_count = Tenant.objects.filter(subscription_status='TRIAL').count()

    return render(request, 'core/admin_panel.html', {
        'tenants': tenants,
        'plans': plans,
        'active_count': active_count,
        'trial_count': trial_count,
    })


@login_required
def admin_tenant_update(request):
    """Update tenant plan and status - superuser only"""
    if not request.user.is_superuser:
        messages.error(request, "Acesso restrito a administradores.")
        return redirect('dashboard')

    if request.method == 'POST':
        tenant_id = request.POST.get('tenant_id')
        plan_id = request.POST.get('plan_id')
        subscription_status = request.POST.get('subscription_status')
        is_active = request.POST.get('is_active') == 'on'

        tenant = get_object_or_404(Tenant, pk=tenant_id)

        if plan_id:
            tenant.plan = get_object_or_404(Plan, pk=plan_id)
        tenant.subscription_status = subscription_status
        tenant.is_active = is_active
        tenant.save()

        messages.success(request, f"Empresa '{tenant.name}' atualizada com sucesso!")

    return redirect('admin_panel')
